"""Video-first broadcast queue. No network operations are performed at import."""
import hashlib
import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.webm', '.m4v'}

class BroadcastQueue:
    def __init__(self, backend, state_file, log=print, stop=None):
        self.backend = backend
        self.path = Path(state_file)
        self.log = log
        self.stop = stop or threading.Event()
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)

    def sync_results(self, video, entry, targets, sheet_targets, worksheets, row_maps, status):
        for tab, worksheet in worksheets.items():
            members = [k for k,c in sheet_targets.items() if c['sheet_tab_name'] == tab]
            results = [entry['success'][k] for k in members if k in entry['success']]
            if not results:
                continue
            row, values = row_maps[tab][video.stem]
            current = worksheet.row_values(row)
            if not current or current[0].strip() != video.stem:
                raise ValueError('Sheet rows changed; video retained for recovery')
            update = [[
                '\n'.join(r['youtube_url'] for r in results),
                '\n'.join(r['youtube_id'] for r in results),
                '\n'.join(r.get('upload_time', 'Not recorded by previous version') for r in results),
                '\n'.join(r.get('scheduled_time', '') for r in results), status]]
            worksheet.batch_update([{'range': f'F{row}:J{row}', 'values': update}], value_input_option='RAW')
            if worksheet.get(f'F{row}:J{row}') != update:
                raise ValueError('Sheet verification failed; saved uploads will be skipped on retry')
            self.log(f'Sheet row {row} updated: URLs, IDs, upload times, schedules, status={status}')

    def run(self, source, uploaded, channels, delay=0, use_sheets=False, metadata=None, max_videos=None):
        source, uploaded = Path(source).resolve(), Path(uploaded).resolve()
        if not source.is_dir():
            raise ValueError('Source folder does not exist')
        if not channels:
            raise ValueError('Select at least one channel')
        targets = {}
        for key, channel in channels.items():
            identity = channel.get('youtube_channel_id') or channel.get('channel_id') or key
            if identity in targets:
                raise ValueError('Two selected entries refer to the same channel')
            targets[identity] = dict(channel, channel_id=channel.get('channel_id') or key)
        uploaded.mkdir(parents=True, exist_ok=True)
        sheet_targets = {k: c for k, c in targets.items() if use_sheets and not c.get('sheet_free_mode', False)}
        worksheets = {}
        row_maps = {}
        sheet_files = []
        if sheet_targets:
            if not self.backend.sheets_client:
                raise ValueError('Google Sheets is not connected; no uploads started')
            book = self.backend.sheets_client.open_by_key(self.backend.spreadsheet_id)
            for identity, channel in sheet_targets.items():
                tab = channel.get('sheet_tab_name', '')
                if tab not in worksheets:
                    worksheets[tab] = book.worksheet(tab)
                    rows = worksheets[tab].get_all_values()
                    mapping = {}
                    for number, values in enumerate(rows[1:], start=2):
                        values = list(values) + [''] * max(0, 10-len(values))
                        video_id = values[0].strip()
                        if not video_id:
                            continue
                        if video_id in mapping:
                            raise ValueError(f'Duplicate video ID {video_id} in sheet {tab}; correct it before uploading')
                        mapping[video_id] = (number, values)
                    row_maps[tab] = mapping
                # The first destination's sheet supplies the shared queue order.
                if identity == next(iter(sheet_targets)):
                    for video_id, (number, values) in row_maps[tab].items():
                        if values[9].strip().lower() in ('done', 'scheduled', 'uploaded'):
                            continue
                        matches = [f for f in source.iterdir() if f.is_file() and f.suffix.lower() in EXTENSIONS and f.stem == video_id]
                        if len(matches) > 1:
                            raise ValueError(f'Multiple files match Sheet ID {video_id}')
                        if matches:
                            sheet_files.append(matches[0])
                        else:
                            self.log(f'Sheet ID {video_id}: no matching video file in source')
        # Sheet mode reads existing rows; folder mode scans only the source root.
        files = sheet_files if sheet_targets else sorted((p for p in source.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS), key=lambda p: p.name.lower())
        if max_videos is not None:
            files = files[:max_videos]
        for video in files:
            if self.stop.is_set():
                break
            digest = hashlib.sha256()
            with video.open('rb') as stream:
                for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                    digest.update(chunk)
            fingerprint = digest.hexdigest()
            entry = self.state.setdefault(fingerprint, {'filename': video.name, 'success': {}, 'pending': {}})
            self.log(f'VIDEO: {video.name} -> {len(targets)} channels')
            # Validate every destination row before uploading to any channel.
            for identity, channel in sheet_targets.items():
                tab = channel['sheet_tab_name']
                if video.stem not in row_maps[tab]:
                    raise ValueError(f'Sheet {tab} has no existing row for ID {video.stem}; no new row will be created')
                _, values = row_maps[tab][video.stem]
                if values[9].strip().lower() in ('done', 'scheduled', 'uploaded') and values[6].strip():
                    entry['success'].setdefault(identity, {'youtube_id': values[6], 'youtube_url': values[5], 'scheduled_time': values[8]})
            self.save()
            data = None
            for identity, channel in targets.items():
                if self.stop.is_set():
                    return
                if identity in entry['success']:
                    self.log(f"Already uploaded: {channel.get('channel_name', identity)}")
                    continue
                if identity in entry['pending']:
                    self.log(f'Uncertain previous upload for {identity}. Check YouTube before retrying; queue paused.')
                    return
                if self.backend.is_channel_in_quota_cooldown(channel['channel_id']):
                    self.log(f'Channel quota cooldown: {identity}; video remains in source and queue paused')
                    return
                if data is None:
                    data = video.read_bytes()
                info = {'video_id': video.stem, 'title': video.stem.replace('_', ' '), 'caption': '', 'tiktok_url': ''}
                info.update((metadata or {}).get(video.name, {}))
                if identity in sheet_targets:
                    _, values = row_maps[channel['sheet_tab_name']][video.stem]
                    info.update(video_id=values[0], title=values[2] or video.stem, caption=values[3], scheduled_time=values[8])
                minimum_schedule = datetime.now() + timedelta(minutes=30)
                sheet_tab = channel.get('sheet_tab_name', '')
                schedule_dt = minimum_schedule
                if use_sheets and sheet_tab and not channel.get('sheet_free_mode', False):
                    proposed = info.get('scheduled_time') or self.backend.calculate_schedule_time(sheet_tab)
                    schedule_dt = max(minimum_schedule, datetime.strptime(proposed, '%d-%b-%Y %I:%M %p'))
                schedule = schedule_dt.strftime('%d-%b-%Y %I:%M %p')
                entry['pending'][identity] = {'started': datetime.now().isoformat(), 'schedule': schedule}
                self.save()
                result = self.backend.upload_to_youtube(channel, data, info, schedule)
                if result and result.get('youtube_id'):
                    entry['success'][identity] = dict(result, scheduled_time=schedule, upload_time=datetime.now().strftime('%d-%b-%Y %I:%M %p'))
                    del entry['pending'][identity]
                    self.save()
                    self.log(f"Success: {channel.get('channel_name', identity)}: {result['youtube_url']}")
                    self.sync_results(video, entry, targets, sheet_targets, worksheets, row_maps, 'uploading')
                else:
                    entry['pending'][identity] = {
                        'started': datetime.now().isoformat(),
                        'schedule': schedule,
                        'error': getattr(self.backend, 'last_upload_error', '') or 'No video ID returned; upload outcome needs review.'
                    }
                    self.save()
                    detail = getattr(self.backend, 'last_upload_error', '')
                    self.log(f'Upload failed for {channel.get("channel_name", identity)} ({identity}): {detail or "YouTube API returned no video ID"}. Video remains in source; queue paused.')
                    return
                if identity != next(reversed(targets)):
                    self.log(f'Waiting {delay:g} seconds before next channel...')
                    if self.stop.wait(max(0, delay)):
                        return
            if not all(identity in entry['success'] for identity in targets):
                self.log('Video incomplete; queue paused until all selected channels succeed.')
                return
            self.sync_results(video, entry, targets, sheet_targets, worksheets, row_maps, 'uploaded; thumbnail pending')
            images = [p for p in source.iterdir() if p.is_file() and p.stem == video.stem and p.suffix.lower() in ('.jpg', '.jpeg', '.png')]
            if len(images) > 1:
                raise ValueError(f'Multiple thumbnails match {video.name}; keep one JPG or PNG')
            thumbnail = images[0] if images else None
            thumbnail_failures = []
            if thumbnail:
                image_hash = hashlib.sha256(thumbnail.read_bytes()).hexdigest()
                for identity, channel in targets.items():
                    uploaded_result = entry['success'][identity]
                    if uploaded_result.get('thumbnail_sha256') == image_hash:
                        continue
                    self.log(f'Setting thumbnail: {thumbnail.name} -> {channel.get("channel_name", identity)}')
                    if not self.backend.set_video_thumbnail(channel, uploaded_result['youtube_id'], thumbnail, self.stop):
                        if self.stop.is_set():
                            self.log('Stop requested; completed video uploads saved.')
                            return
                        name = channel.get('channel_name', identity)
                        thumbnail_failures.append(name)
                        uploaded_result['thumbnail_pending'] = True
                        uploaded_result['thumbnail_source'] = str(thumbnail)
                        self.save()
                        self.log(f'Thumbnail failed for {name}; recorded for later retry. Continuing uploads.')
                        continue
                    uploaded_result['thumbnail_sha256'] = image_hash
                    uploaded_result.pop('thumbnail_pending', None)
                    uploaded_result.pop('thumbnail_source', None)
                    self.save()
            else:
                self.log(f'No same-name JPG/PNG found for {video.name}; continuing without custom thumbnail')
            self.sync_results(video, entry, targets, sheet_targets, worksheets, row_maps, 'done' + ('; thumbnail pending: ' + ', '.join(thumbnail_failures) if thumbnail_failures else ''))
            # Move completed videos outside the source tree so subfolder scans
            # cannot enqueue the Uploaded folder again.
            destination = uploaded / video.name
            if destination.exists():
                destination = uploaded / f'{video.stem}_{uuid.uuid4().hex[:10]}{video.suffix}'
            entry['destination'] = str(destination)
            self.save()
            shutil.move(str(video), str(destination))
            self.log(f'Moved to uploaded: {destination.name}')
            if thumbnail:
                thumbnail_dest = uploaded / (destination.stem + thumbnail.suffix)
                if thumbnail_dest.exists():
                    thumbnail_dest = uploaded / f'{destination.stem}_{uuid.uuid4().hex[:10]}{thumbnail.suffix}'
                shutil.move(str(thumbnail), str(thumbnail_dest))
                for result in entry['success'].values():
                    if result.get('thumbnail_pending'):
                        result['thumbnail_source'] = str(thumbnail_dest)
                self.save()
                self.log(f'Moved thumbnail: {thumbnail_dest.name}')
        self.log('Queue finished.')
