"""Durable local library and independent (video, channel) upload records."""
from contextlib import contextmanager
import json
import sqlite3
import time
from pathlib import Path

class LibraryStore:
    def __init__(self, path, legacy=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS videos (id TEXT PRIMARY KEY, filename TEXT, path TEXT DEFAULT '', added REAL, metadata TEXT DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS uploads (video TEXT, channel TEXT, status TEXT, payload TEXT, PRIMARY KEY(video, channel));
            CREATE TABLE IF NOT EXISTS channels (id TEXT PRIMARY KEY, name TEXT, policy TEXT, cutoff REAL, tab TEXT);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            ''')
            migrated = db.execute("SELECT 1 FROM settings WHERE key='legacy_imported'").fetchone()
        if not migrated:
            if legacy and Path(legacy).exists():
                self.save_state(json.loads(Path(legacy).read_text(encoding='utf-8-sig')))
            with self.connect() as db:
                db.execute("INSERT OR IGNORE INTO settings VALUES ('legacy_imported','yes')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA journal_mode=WAL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def load_state(self):
        with self.connect() as db:
            state = {r[0]: {'filename': r[1], 'success': {}, 'pending': {}} for r in db.execute('SELECT id,filename FROM videos')}
            for vid, ch, status, payload in db.execute('SELECT video,channel,status,payload FROM uploads'):
                state[vid]['success' if status == 'success' else 'pending'][ch] = json.loads(payload)
            return state

    def save_state(self, state):
        with self.connect() as db:
            for vid, entry in state.items():
                db.execute('INSERT OR IGNORE INTO videos(id,filename,added) VALUES (?,?,?)', (vid,entry['filename'],time.time()))
                db.execute('DELETE FROM uploads WHERE video=?', (vid,))
                for status, section in [('success','success'),('pending','pending')]:
                    for ch, payload in entry.get(section,{}).items():
                        db.execute('INSERT INTO uploads VALUES (?,?,?,?)', (vid,ch,status,json.dumps(payload)))

    def add_video(self, vid, path, metadata):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO videos(id,filename,added) VALUES (?,?,?)', (vid,path.name,time.time()))
            db.execute('UPDATE videos SET path=?,filename=?,metadata=? WHERE id=?', (str(path),path.name,json.dumps(metadata),vid))

    def known(self, channel):
        with self.connect() as db:
            return db.execute('SELECT policy,cutoff,tab FROM channels WHERE id=?',(channel,)).fetchone()

    def register(self, identity, name, policy='all'):
        import re
        tab = 'Uploads - ' + re.sub(r'[\[\]:*?/\\]', '_', name)[:10].strip() + ' - ' + identity[-8:]
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO channels VALUES (?,?,?,?,?)',(identity,name,policy,time.time(),tab))
        return self.known(identity)

    def eligible(self, vid, channel):
        policy, cutoff, _ = self.known(channel)
        with self.connect() as db:
            added = db.execute('SELECT added FROM videos WHERE id=?',(vid,)).fetchone()[0]
        return policy == 'all' or added > cutoff

    def sync_policy(self, channel, policy):
        with self.connect() as db:
            db.execute('UPDATE channels SET policy=? WHERE id=?',(policy,channel))

    def metadata(self, vid):
        with self.connect() as db:
            row = db.execute('SELECT metadata FROM videos WHERE id=?',(vid,)).fetchone()
        return json.loads(row[0]) if row else {}
