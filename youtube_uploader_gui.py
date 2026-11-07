"""Same channel management as the original tool, with a video-first queue."""
import json
import threading
from pathlib import Path
import sys

import os

import tkinter as tk
from tkinter import filedialog, messagebox
from tiktok_youtube_gui import TikTokYouTubeGUI
from broadcast_queue import BroadcastQueue

BASE = Path(__file__).resolve().parent

class BroadcastGUI(TikTokYouTubeGUI):
    def build_controls(self, parent):
        # Build exactly the original upload controls and their variables.
        super().build_controls(parent)
        self.broadcast_stop = threading.Event()
        self.monitor_active = False
        self._selected_targets = None
        self._one_video = False
        settings = BASE / 'broadcast_config.json'
        self.broadcast_config = json.loads(settings.read_text(encoding='utf-8-sig')) if settings.exists() else {}
        self.source_var = tk.StringVar()
        self.uploaded_var = tk.StringVar()
        self.tiktok_var = tk.StringVar()
        self.use_sheets_var = tk.BooleanVar(value=True)

    def sync_shared_source(self):
        enabled = [c for c in self.channels_config.values() if c.get('enabled', True)]
        if not enabled:
            raise ValueError('Enable at least one channel')
        shared = enabled[0]
        # Source settings use the first enabled channel, just as configured in
        # the original channel editor. Every destination receives that source.
        local = shared.get('source_type', 'tiktok') == 'local_folder'
        self.source_var.set(shared.get('video_source_folder', '') if local else '')
        self.uploaded_var.set(shared.get('video_uploaded_folder', '') if local else '')
        self.tiktok_var.set('' if local else shared.get('tiktok_username', ''))
        self.use_sheets_var.set(not shared.get('sheet_free_mode', False))

    def process_selected_channels(self):
        from tiktok_youtube_gui import ChannelSelectionDialog
        if self.is_running:
            return
        result = ChannelSelectionDialog(self.root, self.channels_config).show()
        if result:
            self._selected_targets = set(result['channels'])
            self._one_video = result['mode'] == 'single'
            self.start_automation()

    def refresh_channels(self):
        super().refresh_channels()
        if not hasattr(self, 'broadcast_choices'):
            return
        previous = {key: var.get() for key, var in self.channel_flags.items()}
        for widget in self.broadcast_choices.winfo_children():
            widget.destroy()
        self.channel_flags = {}
        for key, channel in self.channels_config.items():
            var = tk.BooleanVar(value=previous.get(key, channel.get('enabled', True)))
            self.channel_flags[key] = var
            tk.Label(self.broadcast_choices, text=('Enabled: ' if channel.get('enabled', True) else 'Disabled: ') + channel.get('channel_name', key)).pack(anchor='w')

    def browse_folder(self, variable):
        result = filedialog.askdirectory()
        if result:
            variable.set(result)

    def build_live_monitor(self, parent):
        super().build_live_monitor(parent)

    def toggle_live_monitor(self):
        self.monitor_active = not self.monitor_active
        self.monitor_status_label.config(text='Active' if self.monitor_active else 'Stopped')
        if self.monitor_active:
            self.poll_broadcast()

    def manual_check_selected(self):
        self.process_selected_channels()

    def poll_broadcast(self):
        if not self.monitor_active:
            return
        if not self.is_running and self.uploader:
            self.start_automation()
        self.root.after(max(1, int(self.monitor_interval_var.get())) * 60000, self.poll_broadcast)

    def review_pending(self):
        if self.is_running:
            return
        path = BASE / 'broadcast_state.json'
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        for entry in state.values():
            for identity in list(entry['pending']):
                answer = messagebox.askyesnocancel('Check YouTube first', f"{entry['filename']}\nChannel: {identity}\n\nIs this video already uploaded?\nYes: enter YouTube video ID.\nNo: allow a fresh retry.\nCancel: leave unresolved.")
                if answer is None:
                    continue
                if answer:
                    from tkinter.simpledialog import askstring
                    video_id = askstring('YouTube video ID', 'Enter the actual YouTube video ID:')
                    if not video_id or len(video_id.strip()) != 11:
                        continue
                    video_id = video_id.strip()
                    entry['success'][identity] = {'youtube_id': video_id, 'youtube_url': f'https://www.youtube.com/watch?v={video_id}'}
                del entry['pending'][identity]
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(state, indent=2), encoding='utf-8')
        temp.replace(path)

    def prepare_tiktok(self, source, uploaded, username):
        import hashlib
        folder = Path(source)
        folder.mkdir(parents=True, exist_ok=True)
        index_path = BASE / 'tiktok_downloads.json'
        index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {}
        videos = self.uploader.filter_recent_videos(self.uploader.fetch_tiktok_videos(username), self.uploader.fetch_hours_limit)
        for video in videos:
            if self.broadcast_stop.is_set():
                return
            video_id = str(video.get('video_id') or video.get('id') or '')
            if not video_id or not video_id.isdigit():
                continue
            if video_id in index:
                continue
            destination = folder / f'tiktok_{video_id}.mp4'
            if destination.exists() or (Path(uploaded) / destination.name).exists():
                continue
            data = self.uploader.download_video_binary(video.get('play') or video.get('download_addr') or '', video_id)
            if not data:
                self.log(f'TikTok download failed: {video_id}', 'warning')
                continue
            temporary = destination.with_suffix('.part')
            temporary.write_bytes(data)
            temporary.replace(destination)
            index[video_id] = {'sha256': hashlib.sha256(data).hexdigest(), 'info': {
                'video_id': video_id,
                'title': video.get('title') or video.get('desc') or video_id,
                'caption': video.get('desc') or video.get('title') or '',
                'tiktok_url': f'https://www.tiktok.com/@{username}/video/{video_id}'}}

            temp_index = index_path.with_suffix('.tmp')
            temp_index.write_text(json.dumps(index, indent=2), encoding='utf-8')
            temp_index.replace(index_path)
            self.log(f'Downloaded TikTok: {video_id}')

    def start_automation(self):
        if self.is_running or (self.automation_thread and self.automation_thread.is_alive()):
            return
        if not self.uploader:
            messagebox.showerror('Loading', 'Wait for backend initialization.')
            return
        try:
            self.sync_shared_source()
            delay = float(self.interval_var.get()) * 60
            if delay < 0:
                raise ValueError('Delay must be nonnegative')
            username = self.tiktok_var.get().strip().lstrip('@')
            source, uploaded = self.source_var.get().strip(), self.uploaded_var.get().strip()
            if username:
                import re
                if not re.fullmatch(r'[A-Za-z0-9_.]+', username):
                    raise ValueError('Enter a TikTok username, not a URL')
                source = str(BASE / 'tiktok_queue' / username)
                uploaded = str(BASE / 'tiktok_uploaded' / username)
                Path(source).mkdir(parents=True, exist_ok=True)
            if not source or not uploaded:
                raise ValueError('Choose both folders')
            src, dst = Path(source).resolve(), Path(uploaded).resolve()
            if not src.is_dir():
                raise ValueError('Source folder does not exist')
            channels = {k: dict(v) for k, v in self.channels_config.items() if v.get('enabled', True) and (self._selected_targets is None or k in self._selected_targets)}
            if not channels:
                raise ValueError('Enable at least one channel in channel settings')
        except ValueError as error:
            messagebox.showerror('Settings', str(error))
            return
        self.review_pending()
        username = self.tiktok_var.get().strip().lstrip('@')
        use_sheets = self.use_sheets_var.get()
        cfg = dict(self.config)
        cfg.update({
            'credentials_folder': self.creds_entry.get().strip(),
            'spreadsheet_url': self.sheets_entry.get().strip(),
            'channel_interval_minutes': int(float(self.interval_var.get())),
            'schedule_gap_min_hours': float(self.min_hours_var.get()),
            'schedule_gap_max_hours': float(self.max_hours_var.get()),
            'schedule_gap_random_minutes': float(self.random_minutes_var.get()),
            'fetch_hours_limit': 0 if int(self.fetch_hours_var.get()) >= 999999 else int(self.fetch_hours_var.get()),
        })
        (BASE / 'tiktok_uploader_config.json').write_text(json.dumps(cfg, indent=2), encoding='utf-8')
        self.uploader.credentials_folder = Path(cfg['credentials_folder'])
        self.uploader.spreadsheet_url = cfg['spreadsheet_url']
        self.uploader.spreadsheet_id = self.uploader.spreadsheet_url.split('/d/',1)[-1].split('/')[0]
        self.uploader.channel_interval_minutes = cfg['channel_interval_minutes']
        self.uploader.schedule_gap_min_hours = cfg['schedule_gap_min_hours']
        self.uploader.schedule_gap_max_hours = cfg['schedule_gap_max_hours']
        self.uploader.schedule_gap_random_minutes = cfg['schedule_gap_random_minutes']
        self.uploader.fetch_hours_limit = cfg['fetch_hours_limit']
        (BASE / 'broadcast_config.json').write_text(json.dumps({'source': self.source_var.get().strip(), 'uploaded': self.uploaded_var.get().strip(), 'tiktok_username': username, 'use_sheets': use_sheets}, indent=2), encoding='utf-8')
        self.broadcast_stop.clear()
        self.uploader.stop_requested = False
        self.is_running = True
        self.btn_start.config(state='disabled')
        self.btn_stop.config(state='normal')
        phase_mode = self.phase_mode.get()
        def worker():
            try:
                import contextlib
                class LogStream:
                    def write(stream, text):
                        for line in text.splitlines():
                            if line.strip():
                                self.log(line)
                    def flush(stream):
                        pass
                metadata = {}
                if username and phase_mode in ('phase1', 'both'):
                    for channel in channels.values():
                        shared_channel = dict(channel, source_type='tiktok', tiktok_username=username)
                        self.uploader.phase1_completed_channels.clear()
                        with contextlib.redirect_stdout(LogStream()):
                            self.uploader.process_channel(shared_channel, phase_mode='phase1')
                    if phase_mode == 'phase1':
                        return
                if not username and phase_mode == 'phase1':
                    self.log('Phase 1 applies to TikTok fetching. Local source uses Phase 2.')
                    return
                if username:
                    self.prepare_tiktok(source, uploaded, username)
                    index_path = BASE / 'tiktok_downloads.json'
                    if index_path.exists():
                        index = json.loads(index_path.read_text(encoding='utf-8'))
                        metadata = {f'tiktok_{key}.mp4': value.get('info', {}) for key, value in index.items() if isinstance(value, dict)}
                with contextlib.redirect_stdout(LogStream()):
                    BroadcastQueue(self.uploader, BASE / 'broadcast_state.json', self.log, self.broadcast_stop).run(source, uploaded, channels, delay, use_sheets=use_sheets, metadata=metadata, max_videos=1 if self._one_video else None)
            except Exception as error:
                self.log(f'Queue stopped: {error}', 'error')
            finally:
                self.root.after(0, self.finish_broadcast)
        self.automation_thread = threading.Thread(target=worker, daemon=True)
        self.automation_thread.start()

    def close_window(self):
        if self.automation_thread and self.automation_thread.is_alive():
            self.stop_automation()
            self.status_label.config(text='Finishing current operation before closing...')
            self.root.after(500, self.close_window)
        else:
            self.root.destroy()

    def finish_broadcast(self):
        self.is_running = False
        self._selected_targets = None
        self._one_video = False
        self.btn_start.config(state='normal')
        self.btn_stop.config(state='disabled')
        self.status_label.config(text='Queue stopped')

    def stop_automation(self):
        self.broadcast_stop.set()
        self.log('Stop requested. Current upload will finish and be recorded.')

if __name__ == '__main__':
    import msvcrt
    instance_lock = (BASE / 'broadcast.lock').open('a+b')
    instance_lock.write(b'0')
    instance_lock.flush()
    instance_lock.seek(0)
    try:
        msvcrt.locking(instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise SystemExit('This uploader is already open. Use the existing window.')
    root = tk.Tk()
    app = BroadcastGUI(root)
    root.title('Multi-channel Video Uploader - Video First')
    root.protocol('WM_DELETE_WINDOW', app.close_window)
    root.mainloop()
