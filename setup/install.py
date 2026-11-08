"""Install into this checkout without changing existing channel settings."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / '.venv'
PYTHON = ENV / 'Scripts' / 'python.exe'
MARKER = ENV / '.uploader-location'

def run(args):
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT)

def main():
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 or newer is required')
    # Virtual environments contain absolute paths: recreate after copying drives.
    location = str(ROOT.resolve())
    valid = PYTHON.exists() and MARKER.exists() and MARKER.read_text(encoding='utf-8') == location
    if valid:
        valid = subprocess.run([str(PYTHON), '-c', 'import tkinter, pip'], cwd=ROOT).returncode == 0
    if not valid:
        if ENV.exists():
            backup = ROOT / ('.venv.previous.' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            ENV.rename(backup)
            print('Preserved previous environment:', backup)
        # Reuse already-installed compatible packages on this PC.
        run([sys.executable, '-m', 'venv', '--system-site-packages', ENV])
        MARKER.write_text(location, encoding='utf-8')
    # No --upgrade or --force-reinstall: pip skips satisfied requirements.
    run([PYTHON, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', ROOT / 'requirements.txt'])
    run([PYTHON, '-c', 'import tkinter, googleapiclient, gspread, PIL, requests, yt_dlp, openpyxl'])
    (ROOT / 'youtube_credentials').mkdir(exist_ok=True)
    cfg_path = ROOT / 'tiktok_uploader_config.json'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8-sig')) if cfg_path.exists() else {
        'spreadsheet_url': '', 'schedule_gap_min_hours': 2,
        'schedule_gap_max_hours': 3, 'schedule_gap_random_minutes': 40,
        'channel_interval_minutes': 2, 'fetch_hours_limit': 72}
    # Local credentials follow this copy across drives; do not copy secrets from other tools.
    creds = Path(cfg.get('credentials_folder', 'youtube_credentials'))
    if not creds.is_absolute():
        creds = ROOT / creds
    if not creds.is_dir():
        creds = ROOT / 'youtube_credentials'
    cfg['credentials_folder'] = str(creds.resolve())
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    channels = ROOT / 'tiktok_channels_config.json'
    if not channels.exists():
        channels.write_text('{}', encoding='utf-8')
    template = ROOT / 'templates' / 'MultiUploader_Template.xlsx'
    workbook = ROOT / 'MultiUploader_Template.xlsx'
    if not workbook.exists():
        if not template.is_file():
            raise FileNotFoundError('Bundled Excel template is missing; download the complete repository')
        # Exclusive creation avoids overwriting an existing workbook, even
        # if another process creates it between the exists check and copy.
        try:
            with workbook.open('xb') as destination, template.open('rb') as source:
                shutil.copyfileobj(source, destination)
            print('Excel template copied to:', workbook)
        except FileExistsError:
            print('Existing Excel workbook preserved:', workbook)
    else:
        print('Existing Excel workbook preserved:', workbook)
    print('Installed in:', ROOT)
    print('Copy your own OAuth JSON / Sheets service_account.json into youtube_credentials.')
    print('Configure channels, source folders and Sheets URL in the GUI. Run RUN.bat.')

if __name__ == '__main__':
    main()
