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
from library_store import LibraryStore

BASE = Path(__file__).resolve().parent

class BroadcastGUI(TikTokYouTubeGUI):
    def build_controls(self, parent):
        # Build exactly the original upload controls and their variables.
        super().build_controls(parent)
        self.broadcast_stop = threading.Event()
        self.monitor_active = False
        self._closing = False
        self._selected_targets = None
        self._one_video = False
        settings = BASE / 'broadcast_config.json'
        self.broadcast_config = json.loads(settings.read_text(encoding='utf-8-sig')) if settings.exists() else {}
        initial_source=self.broadcast_config.get('source','')
        if not initial_source:
            initial_source=next((c.get('video_source_folder','') for c in self.channels_config.values() if c.get('enabled',True)), '')
        self.source_var = tk.StringVar(value=initial_source)
        self.uploaded_var = tk.StringVar(value=self.broadcast_config.get('uploaded',''))
        self.tiktok_var = tk.StringVar()
        self.use_sheets_var = tk.BooleanVar(value=True)
        library = tk.LabelFrame(parent, text='Permanent shared library')
        library.pack(fill='x', pady=5)
        tk.Label(library, text='Videos stay here. Master tab: Videos. Upload history: library.sqlite3', wraplength=430).pack(anchor='w')
        for label,variable in [('Videos + thumbnails folder (shared by all channels)',self.source_var)]:
            row=tk.Frame(library);row.pack(fill='x',pady=3)
            tk.Label(row,text=label).pack(anchor='w')
            tk.Entry(row,textvariable=variable).pack(side='left',fill='x',expand=True)
            tk.Button(row,text='Browse',command=lambda v=variable:self.browse_folder(v)).pack(side='right')
        tk.Button(library,text='Save shared folder',command=self.save_shared_folder).pack(fill='x')
        tk.Button(library,text='Sync library / Sheets (no video uploads)',command=self.sync_library_only).pack(fill='x')
        tk.Button(library,text='Include existing videos for selected channels',command=self.include_existing).pack(fill='x')
        tracking=tk.LabelFrame(library,text='Metadata and upload results')
        tracking.pack(fill='x',pady=5)
        self.tracking_mode=tk.StringVar(value=self.broadcast_config.get('tracking_mode','google'))
        self.excel_var=tk.StringVar(value=self.broadcast_config.get('excel_path',str(BASE/'VideoLibrary.xlsx')))
        for label,value in [('Google Sheets','google'),('Local Excel (.xlsx)','excel')]:
            tk.Radiobutton(tracking,text=label,variable=self.tracking_mode,value=value,command=self.save_tracking).pack(anchor='w')
        tk.Entry(tracking,textvariable=self.excel_var).pack(fill='x')
        tk.Button(tracking,text='Choose / create Excel workbook',command=self.browse_excel).pack(fill='x')
        self.ingest_requested=False

    def save_shared_folder(self):
        folder=self.source_var.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror('Shared folder','Select the folder containing videos and same-name thumbnails.')
            return
        path=BASE/'broadcast_config.json'
        cfg=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        cfg['source']=folder
        path.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
        self.log(f'Shared videos + thumbnails folder saved for all channels: {folder}')

    def save_tracking(self):
        path=BASE/'broadcast_config.json'
        cfg=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        cfg.update(tracking_mode=self.tracking_mode.get(),excel_path=self.excel_var.get().strip())
        path.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
        if self.uploader and self.tracking_mode.get()=='excel':self.uploader.sheets_client=None

    def browse_excel(self):
        result=filedialog.asksaveasfilename(title='Select existing or create local workbook',defaultextension='.xlsx',filetypes=[('Excel workbook','*.xlsx')],initialfile='VideoLibrary.xlsx',confirmoverwrite=False)
        if result:
            self.excel_var.set(result)
            self.tracking_mode.set('excel')
            self.save_tracking()

    def include_existing(self):
        if self.is_running:return
        from tiktok_youtube_gui import ChannelSelectionDialog
        result=ChannelSelectionDialog(self.root,self.channels_config).show()
        if not result:return
        store=LibraryStore(BASE/'library.sqlite3',BASE/'broadcast_state.json')
        for key in result['channels']:
            c=self.channels_config[key]
            identity=c.get('youtube_channel_id') or c.get('channel_id') or key
            store.register(identity,c.get('channel_name',identity),'all')
            store.sync_policy(identity,'all')
        self.log('Selected channels now include all existing library videos. Successful uploads will still be skipped.')

    def refresh_all_data(self):
        store=LibraryStore(BASE/'library.sqlite3',BASE/'broadcast_state.json')
        with store.connect() as db:
            videos=db.execute('SELECT COUNT(*) FROM videos').fetchone()[0]
            uploads=db.execute("SELECT COUNT(*) FROM uploads WHERE status='success'").fetchone()[0]
        self.stat_labels['Videos'].config(text=str(videos))
        self.stat_labels['Uploaded'].config(text=str(uploads))
        self.stat_labels['Channels'].config(text=str(sum(bool(c.get('enabled',True)) for c in self.channels_config.values())))
        self.refresh_channels()
        self.log(f'Library: {videos} unique videos; {uploads} successful channel uploads')

    def sync_library_only(self):
        self.ingest_requested=True
        self.start_automation()

    def sync_shared_source(self):
        enabled=[c for c in self.channels_config.values() if c.get('enabled',True)]
        if not enabled: raise ValueError('Enable at least one channel')
        shared=enabled[0]
        self.tiktok_var.set(shared.get('tiktok_username','') if shared.get('source_type')=='tiktok' else '')
        self.use_sheets_var.set(not shared.get('sheet_free_mode',False))

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
        store=LibraryStore(BASE / 'library.sqlite3',path)
        state=store.load_state()
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
        store.save_state(state)
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
        if self._closing:
            return
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
            if not source:
                raise ValueError('Choose the shared library folder')
            if not uploaded:uploaded=source
            src, dst = Path(source).resolve(), Path(uploaded).resolve()
            if not src.is_dir():
                raise ValueError('Source folder does not exist')
            channels = {k: dict(v) for k, v in self.channels_config.items() if v.get('enabled', True) and (self._selected_targets is None or k in self._selected_targets)}
            if not channels:
                raise ValueError('Enable at least one channel in channel settings')
        except ValueError as error:
            messagebox.showerror('Settings', str(error))
            return
        store=LibraryStore(BASE / 'library.sqlite3', BASE / 'broadcast_state.json')
        for key,c in channels.items():
            identity=c.get('youtube_channel_id') or c.get('channel_id') or key
            if not store.known(identity):
                history=store.load_state()
                if any(identity in e['success'] or identity in e['pending'] for e in history.values()):
                    c['library_policy']='all'
                else:
                    answer=messagebox.askyesnocancel('New channel library', f"{c.get('channel_name',identity)}: upload existing library videos?\nYes: all existing and future videos.\nNo: only files first discovered after this library run.\nCancel: do not start.")
                    if answer is None:return
                    c['library_policy']='all' if answer else 'future'
        # Channel workbook history is reconciled automatically in the worker.
        username = self.tiktok_var.get().strip().lstrip('@')
        excel_path=self.excel_var.get().strip() if self.tracking_mode.get()=='excel' else None
        if self.tracking_mode.get()=='excel' and not excel_path:
            messagebox.showerror('Workbook','Choose a local .xlsx file')
            return
        if excel_path and Path(excel_path).suffix.lower()!='.xlsx':
            messagebox.showerror('Workbook','Choose an .xlsx workbook')
            return
        self.save_tracking()
        use_sheets = self.tracking_mode.get()=='google' and self.use_sheets_var.get()
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
        (BASE / 'broadcast_config.json').write_text(json.dumps({'source': self.source_var.get().strip(), 'uploaded': self.uploaded_var.get().strip(), 'tiktok_username': username, 'use_sheets': use_sheets, 'tracking_mode':self.tracking_mode.get(), 'excel_path':self.excel_var.get().strip()}, indent=2), encoding='utf-8')
        self.broadcast_stop.clear()
        self.uploader.stop_requested = False
        self.is_running = True
        self.btn_start.config(state='disabled')
        self.btn_stop.config(state='normal')
        phase_mode = self.phase_mode.get()
        ingest_only=self.ingest_requested or phase_mode=='phase1'
        self.ingest_requested=False
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
                if username:
                    self.prepare_tiktok(source, uploaded, username)
                    index_path = BASE / 'tiktok_downloads.json'
                    if index_path.exists():
                        index = json.loads(index_path.read_text(encoding='utf-8'))
                        metadata = {f'tiktok_{key}.mp4': value.get('info', {}) for key, value in index.items() if isinstance(value, dict)}
                with contextlib.redirect_stdout(LogStream()):
                    BroadcastQueue(self.uploader, BASE / 'broadcast_state.json', self.log, self.broadcast_stop).run(source, uploaded, channels, delay, use_sheets=use_sheets, metadata=metadata, max_videos=1 if self._one_video else None, ingest_only=ingest_only, excel_path=excel_path)
            except Exception as error:
                self.log(f'Queue stopped: {error}', 'error')
            finally:
                self.root.after(0, self.finish_broadcast)
        self.automation_thread = threading.Thread(target=worker, daemon=True)
        self.automation_thread.start()

    def close_window(self):
        if self._closing:
            return
        self._closing = True
        self.stop_automation()
        self.btn_start.config(state='disabled')
        self.status_label.config(text='Finishing current operation before closing...')
        self._wait_until_closed()

    def _wait_until_closed(self):
        # Poll completion only: never send another Stop or schedule uploads here.
        if self.automation_thread and self.automation_thread.is_alive():
            self.root.after(500, self._wait_until_closed)
        else:
            self.root.destroy()

    def finish_broadcast(self):
        self.is_running = False
        self._selected_targets = None
        self._one_video = False
        self.btn_stop.config(state='disabled')
        if self._closing:
            return
        self.btn_start.config(state='normal')
        self.status_label.config(text='Queue stopped')
        self.refresh_all_data()

    def stop_automation(self):
        self.monitor_active = False
        if self.uploader:
            self.uploader.stop_requested = True
        self.btn_stop.config(state='disabled')
        if self.broadcast_stop.is_set():
            return
        self.broadcast_stop.set()
        if self.is_running or (self.automation_thread and self.automation_thread.is_alive()):
            self.status_label.config(text='Stopping after current operation...')
            self.log('Stop requested. Current operation will finish and be recorded.')

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
    root.title('Single Video Multichannel Uploader')
    root.protocol('WM_DELETE_WINDOW', app.close_window)
    root.mainloop()
