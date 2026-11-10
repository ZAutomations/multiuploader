"""Permanent shared library, SQLite authority, retryable Google Sheets mirrors."""
import hashlib
import json
import random
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from library_store import LibraryStore

EXTENSIONS = {'.mp4','.mov','.avi','.mkv','.flv','.webm','.m4v'}
FMT = '%d-%b-%Y %I:%M %p'
HEADERS = ['video_id','filename','title','description','thumbnail','yt_video_url','youtube_id','upload_time','schedual_time','status','thumbnail_status','error']
MASTER_HEADERS = ['video_id','filename','title','description','thumbnail','source_url']

def read_rows(ws):
    rows = ws.get_all_values()
    if not rows:
        return {}
    return {r[0]: dict(zip(rows[0], r)) for r in rows[1:] if r and r[0]}

class BroadcastQueue:
    def __init__(self, backend, state_file, log=print, stop=None):
        self.backend, self.path, self.log = backend, Path(state_file), log
        self.stop = stop or threading.Event()
        self.store = LibraryStore(self.path.with_name('library.sqlite3'), self.path)
        self.state = self.store.load_state()
        self.book = None
        self.master = {}
        self.sheets = {}
        self.channel_schedules = {}

    def save(self):
        # SQLite commits first. JSON is only a compatibility/recovery export.
        self.store.save_state(self.state)
        try:
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.state,indent=2),encoding='utf-8')
            temp.replace(self.path)
        except OSError as e:
            self.log(f'JSON export unavailable; SQLite history is saved: {e}')

    def worksheet(self, title, headers):
        if title in self.sheets:
            return self.sheets[title]
        from gspread.exceptions import WorksheetNotFound
        try:
            ws = self.book.worksheet(title)
        except WorksheetNotFound:
            ws = self.book.add_worksheet(title=title, rows=1000, cols=max(12,len(headers)))
        rows = ws.get_all_values()
        if rows and rows[0] != headers:
            raise ValueError(f'Tab {title} has different columns; preserve/rename it before using this library tab')
        if not rows:
            ws.append_row(headers, value_input_option='RAW')
        self.sheets[title] = ws
        return ws

    def upsert(self, ws, headers, values):
        rows = ws.get_all_values()
        matches = [n for n,r in enumerate(rows[1:],2) if r and r[0] == values[0]]
        if len(matches)>1:
            raise ValueError(f'Duplicate video ID in {ws.title}: {values[0]}')
        if matches:
            ws.batch_update([{'range': f'A{matches[0]}:L{matches[0]}' if len(headers)==12 else f'A{matches[0]}:F{matches[0]}', 'values':[values]}],value_input_option='RAW')
        else:
            ws.append_row(values,value_input_option='RAW')

    def mirror(self, video, info, identity, channel, result, pending=None):
        if not self.book:
            return
        try:
            tab = self.store.known(identity)[2]
            ws = self.worksheet(tab,HEADERS)
            thumb = 'set' if result.get('thumbnail_sha256') else ('pending' if info.get('thumbnail') else 'none')
            status = 'uploaded' if result.get('youtube_id') else ('uncertain' if pending else 'pending')
            self.upsert(ws,HEADERS,[info['video_id'],video.name,info['title'],info.get('caption',''),Path(info['thumbnail']).name if info.get('thumbnail') else '',result.get('youtube_url',''),result.get('youtube_id',''),result.get('upload_time',''),result.get('scheduled_time',''),status,thumb,result.get('thumbnail_error','') or (pending or {}).get('error','')])
        except Exception as e:
            self.log(f'Sheet sync pending for {channel.get("channel_name",identity)}: {e}. SQLite saved; uploads continue.')

    def reconcile_channel_history(self, files, targets):
        """Read each channel's existing rows BEFORE writing status/results back."""
        self.skip_rows=set()
        if not self.book:return
        for identity,channel in targets.items():
            tab=self.store.known(identity)[2]
            try:
                rows=read_rows(self.worksheet(tab,HEADERS))
            except Exception as error:
                raise ValueError(f'Cannot read upload history for {channel.get("channel_name",identity)}: {error}. No uploads started.') from error
            self.channel_schedules[identity]=[]
            # Read the whole schedule column, including videos absent from the
            # current disk library, just like the original uploader.
            for saved_row in rows.values():
                try:
                    self.channel_schedules[identity].append(datetime.strptime(str(saved_row.get('schedual_time','')).strip(),FMT))
                except ValueError:
                    pass
            for vid,video in files.items():
                row=rows.get(video.stem)
                if not row:continue
                entry=self.state[vid]
                status=str(row.get('status','')).strip().lower()
                yt_id=str(row.get('youtube_id','')).strip()
                url=str(row.get('yt_video_url','')).strip()
                if not re.fullmatch(r'[A-Za-z0-9_-]{11}',yt_id):
                    match=re.search(r'(?:[?&]v=|youtu\.be/)([A-Za-z0-9_-]{11})(?:[?&#/]|$)',url)
                    yt_id=match.group(1) if match else ''
                completed=status in ('uploaded','done','scheduled','success','completed') or status.startswith('done;')
                if yt_id and (completed or row.get('upload_time') or url):
                    result=entry['success'].setdefault(identity,{})
                    result.update(youtube_id=yt_id,youtube_url=url or f'https://www.youtube.com/watch?v={yt_id}',
                                  scheduled_time=row.get('schedual_time','') or result.get('scheduled_time',''),
                                  upload_time=row.get('upload_time','') or result.get('upload_time',''))
                    entry['pending'].pop(identity,None)
                    self.log(f'Excel/Sheet history: already uploaded {video.stem} -> {channel.get("channel_name",identity)}')
                elif status not in ('','pending','ready','uncertain'):
                    # Original uploader skips non-empty status rows. Do not erase
                    # their metadata or assume a completed upload is missing.
                    self.skip_rows.add((vid,identity))
                    self.log(f'Skipping {video.stem} for {channel.get("channel_name",identity)}: status={status}')
        # Clear only failures which prove that the API rejected the request.
        # Unknown network/interruption outcomes stay pending for safety, without a modal.
        for entry in self.state.values():
            for identity,pending in list(entry['pending'].items()):
                error=pending.get('error','').lower()
                if any(marker in error for marker in ('accessnotconfigured','has not been used in project','could not open youtube service','invalidtitle','invaliddescription','invalidtags','uploadlimitexceeded','quotaexceeded')):
                    entry['pending'].pop(identity,None)
        self.save()

    def schedule(self, identity):
        # Original rule: latest recorded schedule + random hour gap + minute
        # offset. Use now+the same gap only if that result is already past.
        prior=list(self.channel_schedules.get(identity,[]))
        for entry in self.state.values():
            value=entry.get('success',{}).get(identity,{}).get('scheduled_time','')
            try: prior.append(datetime.strptime(value,FMT))
            except ValueError: pass
        now=datetime.now()
        last=max(prior) if prior else now
        min_hours=float(self.backend.schedule_gap_min_hours)
        max_hours=float(self.backend.schedule_gap_max_hours)
        jitter=int(self.backend.schedule_gap_random_minutes)
        if min_hours<0 or max_hours<min_hours or jitter<0:
            raise ValueError('Invalid scheduling gap settings')
        hours=random.uniform(min_hours,max_hours)
        minutes=random.randint(-jitter,jitter)
        gap=timedelta(hours=hours,minutes=minutes)
        if gap.total_seconds()<=0:
            raise ValueError('Scheduling gap must be positive; reduce the random minute offset')
        next_time=last+gap
        if next_time<now:
            next_time=now+gap
        self.log(f'Schedule {identity}: last={last.strftime(FMT)}, gap={hours:.2f}h {minutes:+d}m, next={next_time.strftime(FMT)}')
        return next_time.strftime(FMT)

    def run(self, source, uploaded, channels, delay=0, use_sheets=False, metadata=None, max_videos=None, ingest_only=False, excel_path=None):
        source, uploaded=Path(source).resolve(),Path(uploaded).resolve()
        if not source.is_dir(): raise ValueError('Shared library folder does not exist')
        targets={}
        for key,c in channels.items():
            identity=c.get('youtube_channel_id') or c.get('channel_id') or key
            if identity in targets: raise ValueError('Duplicate destination channel')
            targets[identity]=dict(c,channel_id=c.get('channel_id') or key)
        if not targets: raise ValueError('Select at least one channel')
        # Scan existing archive too, without copying or moving any video/image.
        candidates=list(source.iterdir())
        if uploaded.is_dir() and uploaded!=source: candidates+=list(uploaded.iterdir())
        files={}
        for p in sorted(candidates,key=lambda x:str(x).casefold()):
            if not p.is_file() or p.suffix.lower() not in EXTENSIONS: continue
            digest=hashlib.sha256()
            with p.open('rb') as stream:
                for chunk in iter(lambda:stream.read(4*1024*1024),b''): digest.update(chunk)
            vid=digest.hexdigest()
            if vid in files: continue
            if any(v.stem==p.stem for v in files.values()):
                raise ValueError(f'Two different videos have the same title ID: {p.stem}')
            files[vid]=p
        legacy_metadata={}
        if excel_path:
            from local_workbook import LocalWorkbook
            try:
                self.book=LocalWorkbook(excel_path)
                ws=self.worksheet('Videos',MASTER_HEADERS)
                self.master=read_rows(ws)
                self.log(f'Local Excel tracking: {Path(excel_path).resolve()}')
            except Exception as e:
                self.book=None
                self.log(f'Excel unavailable; SQLite is safe. Sync again after closing Excel: {e}')
        elif use_sheets and self.backend.sheets_client:
            try:
                self.book=self.backend.sheets_client.open_by_key(self.backend.spreadsheet_id)
                ws=self.worksheet('Videos',MASTER_HEADERS)
                self.master=read_rows(ws)
                for tab in {c.get('sheet_tab_name','') for c in channels.values()}:
                    if not tab or tab=='Videos':continue
                    try:
                        rows=self.book.worksheet(tab).get_all_values()
                        for row in rows[1:]:
                            if row and row[0]:legacy_metadata.setdefault(row[0],{'title':row[2] if len(row)>2 else row[0],'caption':row[3] if len(row)>3 else ''})
                    except Exception as e:self.log(f'Legacy metadata tab {tab} unavailable: {e}')
            except Exception as e:
                self.book=None
                self.log(f'Sheets unavailable; local metadata and SQLite tracking active: {e}')
        elif use_sheets:
            self.log('Sheets disconnected; SQLite tracking active. Sync will retry next run.')
        if self.master:
            order={video_id:i for i,video_id in enumerate(self.master)}
            files=dict(sorted(files.items(),key=lambda item:order.get(item[1].stem,len(order))))
        infos={}
        for vid,video in files.items():
            info={'video_id':video.stem,'title':video.stem,'caption':''}
            info.update(self.store.metadata(vid))
            info.update(legacy_metadata.get(video.stem,{}));info.update((metadata or {}).get(video.name,{}))
            info['video_id']=video.stem
            master=self.master.get(video.stem)
            if master: info.update(title=master.get('title') or video.stem,caption=master.get('description',''))
            # video_id is the common filename stem for both assets.
            # Sheet filename/thumbnail cells are generated output, never lookup inputs.
            images=[p for p in video.parent.iterdir() if p.is_file() and p.stem.casefold()==video.stem.casefold() and p.suffix.lower() in ('.png','.jpg','.jpeg')]
            info['thumbnail']=str(images[0]) if len(images)==1 else ''
            if len(images)>1: self.log(f'Multiple thumbnails for {video.name}; keep only one image')
            self.store.add_video(vid,video,info);infos[vid]=info
            self.state.setdefault(vid,{'filename':video.name,'success':{},'pending':{}})
            # filename is optional user input: resolve from video_id/file stem,
            # then fill the real detected filename in the master sheet.
            if self.book and (not master or master.get('filename','') != video.name or master.get('thumbnail','') != (Path(info['thumbnail']).name if info['thumbnail'] else '')):
                try: self.upsert(self.worksheet('Videos',MASTER_HEADERS),MASTER_HEADERS,[video.stem,video.name,info['title'],info['caption'],Path(info['thumbnail']).name if info['thumbnail'] else '',(master or {}).get('source_url') or info.get('tiktok_url','')])
                except Exception as e:self.log(f'Master Videos sync pending: {e}')
        # Register AFTER discovery so 'future' excludes the existing library.
        for identity,c in targets.items():
            # Honor a channel's explicitly named tab; legacy shared tabs such
            # as Multi keep their generated per-channel mappings.
            preferred=c.get('sheet_tab_name') if c.get('sheet_tab_name')==c.get('channel_name') else None
            self.store.register(identity,c.get('channel_name',identity),c.get('library_policy','all'),preferred_tab=preferred)
            self.log(f'Tracking tab for {c.get("channel_name",identity)}: {self.store.known(identity)[2]}')
        self.reconcile_channel_history(files,targets)
        self.save()
        if ingest_only:
            for vid,video in files.items():
                for identity,c in targets.items():
                    if self.store.eligible(vid,identity) and (vid,identity) not in self.skip_rows:
                        self.mirror(video,infos[vid],identity,c,self.state[vid]['success'].get(identity,{}),self.state[vid]['pending'].get(identity))
            self.log("Library indexed and Sheet sync attempted; upload phase skipped.")
            return
        count=0
        for vid,video in files.items():
            if self.stop.is_set(): break
            info=infos[vid];entry=self.state[vid]
            active={i:c for i,c in targets.items() if self.store.eligible(vid,i) and (vid,i) not in self.skip_rows}
            if not active: continue
            needs_upload=any(i not in entry['success'] and i not in entry['pending'] for i in active)
            if needs_upload and max_videos is not None and count>=max_videos: continue
            if needs_upload: count+=1
            self.log(f'LIBRARY: {video.name} -> {len(active)} selected channels')
            data=None
            for identity,c in active.items():
                if self.stop.is_set(): return
                result=entry['success'].get(identity,{})
                pending=entry['pending'].get(identity)
                self.mirror(video,info,identity,c,result,pending)
                if pending:
                    self.log(f'No confirmed result for {c.get("channel_name",identity)}; skipping this uncertain attempt and continuing to the next pending video.')
                    continue
                if not result:
                    if self.backend.is_channel_in_quota_cooldown(c['channel_id']):
                        self.log(f'Quota cooldown: {c.get("channel_name",identity)}; other destinations continue')
                        continue
                    if data is None:data=video.read_bytes()
                    schedule=self.schedule(identity)
                    entry['pending'][identity]={'started':datetime.now().isoformat(),'schedule':schedule}
                    self.save()
                    result=self.backend.upload_to_youtube(c,data,info,schedule)
                    if not result or not result.get('youtube_id'):
                        entry['pending'][identity]['error']=getattr(self.backend,'last_upload_error','Upload not confirmed')
                        self.save();self.mirror(video,info,identity,c,{},entry['pending'][identity]);continue
                    result=dict(result,scheduled_time=schedule,upload_time=datetime.now().strftime(FMT))
                    entry['success'][identity]=result;entry['pending'].pop(identity,None);self.save()
                    self.mirror(video,info,identity,c,result)
                    self.log(f'Uploaded to {c.get("channel_name",identity)}: {result["youtube_url"]}')
                else:self.log(f'Already uploaded: {c.get("channel_name",identity)}')
                if info['thumbnail']:
                    image=Path(info['thumbnail']);image_hash=hashlib.sha256(image.read_bytes()).hexdigest()
                    if result.get('thumbnail_sha256')!=image_hash:
                        if self.backend.set_video_thumbnail(c,result['youtube_id'],image,self.stop):
                            result['thumbnail_sha256']=image_hash;result.pop('thumbnail_error',None)
                        else:result['thumbnail_error']='Thumbnail failed; retry separately on next run'
                        self.save();self.mirror(video,info,identity,c,result)
                if needs_upload and identity!=next(reversed(active)) and self.stop.wait(max(0,delay)):return
        self.log('Library run complete. Videos remain in their original folders for future channels.')
