"""
TikTok to YouTube Auto Uploader - LIVE MONITOR EDITION v4.1
✅ NEW Videos: Fetch from TikTok (48/72hrs) → Upload → Append → Color mark
✅ OLD Videos: Read from sheet → Download → Upload → Update in-place
✅ LIVE MONITOR: Auto-check every 10 minutes in background
✅ Fixed scheduling bug (skips failed rows)
✅ yt-dlp PRIMARY download method (no watermarks, most reliable!)
✅ Multiple fallback APIs (TikWM, SSSTik) if yt-dlp fails
✅ Smart retry logic with exponential backoff
✅ Configurable fetch window (48 or 72 hours)
"""

import os
import sys
import time
import json
import pickle
import random
import requests
import re
import subprocess
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any, Tuple
from urllib.parse import quote
import threading

# Fix Windows console encoding for unicode characters
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass
    # Enable ANSI color support on Windows
    try:
        import colorama
        colorama.init()
    except ImportError:
        # If colorama not available, enable virtual terminal processing
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except:
            pass

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
import gspread
from google.oauth2.service_account import Credentials as ServiceAccountCredentials


# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

# Get script directory for relative paths
try:
    SCRIPT_DIR = Path(__file__).parent
except NameError:
    SCRIPT_DIR = Path.cwd()


def extract_spreadsheet_id(url: str) -> str:
    """Extract the spreadsheet ID from a Google Sheets URL.

    Handles bare IDs, trailing '/edit', '/edit#gid=...', '?usp=sharing',
    and any other suffix. Returns the input unchanged if it isn't a URL.
    """
    if not url:
        return ''
    url = str(url).strip()
    if '/d/' in url:
        tail = url.split('/d/', 1)[1]
        return tail.split('/')[0].split('?')[0].split('#')[0]
    return url


# API Scopes
YOUTUBE_SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly'
]
SHEETS_SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]


class TikTokYouTubeUploader:
    """Automated TikTok to YouTube uploader with Live Monitor"""

    def __init__(self):
        # Paths
        self.credentials_folder = SCRIPT_DIR / 'youtube_credentials'
        self.state_file = self.credentials_folder / 'uploader_state.json'

        # Create folders
        self.credentials_folder.mkdir(parents=True, exist_ok=True)

        # Google Sheets configuration (overridden below by tiktok_uploader_config.json)
        self.spreadsheet_url = ""
        self.spreadsheet_id = extract_spreadsheet_id(self.spreadsheet_url)

        # Channels configuration
        self.channels = {}
        self.load_channels_config()

        # Timing configuration
        self.schedule_gap_min_hours = 2
        self.schedule_gap_max_hours = 3
        self.schedule_gap_random_minutes = 40
        self.channel_interval_minutes = 2

        # Fetch configuration - BOTH OPTIONS AVAILABLE
        self.fetch_hours_limit = 72  # Default: 72 hours
        # Options: 48 or 72 (configurable per channel or globally)

        # ═══════════════════════════════════════════════════════════
        # LOAD tiktok_uploader_config.json — single source of truth.
        # The GUI writes its Settings there, so the backend (incl. the
        # CLI main() path) honors the same spreadsheet & timings.
        # ═══════════════════════════════════════════════════════════
        config_file = SCRIPT_DIR / 'tiktok_uploader_config.json'
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.spreadsheet_url = cfg.get('spreadsheet_url', self.spreadsheet_url)
                self.spreadsheet_id = extract_spreadsheet_id(self.spreadsheet_url)
                self.schedule_gap_min_hours = cfg.get('schedule_gap_min_hours', self.schedule_gap_min_hours)
                self.schedule_gap_max_hours = cfg.get('schedule_gap_max_hours', self.schedule_gap_max_hours)
                self.schedule_gap_random_minutes = cfg.get('schedule_gap_random_minutes', self.schedule_gap_random_minutes)
                self.channel_interval_minutes = cfg.get('channel_interval_minutes', self.channel_interval_minutes)
                self.fetch_hours_limit = cfg.get('fetch_hours_limit', self.fetch_hours_limit)
            except Exception as e:
                print(f"⚠️  Could not load uploader config: {e}{Colors.RESET}")

        # Description format
        self.description_format = 'prepend'
        self.description_separator = '\n\n' + '='*50 + '\n\n'

        # Title format
        self.title_format = 'replace'
        self.title_prefix = ''
        self.title_suffix = ''
        self.title_separator = ' '

        # Enhanced download settings
        self.download_timeout = 120
        self.max_retries = 3
        self.retry_delay_base = 5
        self.request_delay = 2

        # User agents for rotation
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
        ]

        # Dual-mode settings
        self.process_old_videos_mode = True  # Enable OLD video processing
        self.new_video_color = {  # Light green for NEW videos
            "red": 0.85,
            "green": 0.92,
            "blue": 0.83
        }

        # State management
        self.state = self.load_state()
        self.current_channel_index = self.state.get('current_channel_index', 0)
        self.processed_videos_this_run = self.state.get('processed_videos_this_run', [])
        self.channels_processed_this_run = self.state.get('channels_processed_this_run', 0)

        # Phase 1 tracking - Only run Phase 1 once per channel per session
        self.phase1_completed_channels = set()  # Track which channels have completed Phase 1 in this session

        # Stop flag for GUI control
        self.stop_requested = False

        # ═══════════════════════════════════════════════════════════
        # QUOTA EXCEEDED TRACKING - 24 HOUR COOLDOWN
        # ═══════════════════════════════════════════════════════════
        self.quota_exceeded_channels = {}  # {channel_id: timestamp}
        self.quota_cooldown_hours = 24

        # Persist cooldowns to disk so a restart doesn't reset them and
        # immediately hammer a still-exhausted daily quota again.
        self.quota_cooldown_file = self.credentials_folder / 'quota_cooldown.json'
        self._load_quota_cooldowns()

        # ═══════════════════════════════════════════════════════════
        # SHEETS API CACHE - Reduce API calls
        # ═══════════════════════════════════════════════════════════
        self.sheets_cache = {}  # {sheet_tab_name: {'ids': [...], 'timestamp': datetime}}
        self.cache_duration_seconds = 300  # Cache for 5 minutes

        # ═══════════════════════════════════════════════════════════
        # LIVE MONITOR - AUTO-CHECK SYSTEM
        # ═══════════════════════════════════════════════════════════
        self.auto_check_enabled = False
        self.auto_check_thread = None
        self.auto_check_interval = 120  # 2 minutes in seconds (as requested)
        self.auto_check_log_callback = None  # Callback for GUI logging
        self.auto_check_stats = {
            'total_checks': 0,
            'videos_found': 0,
            'videos_uploaded': 0,
            'last_check': None,
            'next_check': None,
            'status': 'Stopped'
        }

        # Cache
        self.channel_default_descriptions = {}

        # Initialize Google Sheets
        self.sheets_client = None
        self.init_sheets_client()

        print("="*70)
        print("TikTok to YouTube Uploader - LIVE MONITOR EDITION v4.0")
        print("="*70)
        print(f"✅ NEW Videos: Fetch → Upload → Append → Color")
        print(f"✅ OLD Videos: Sheet → Download → Upload → Update")
        print(f"✅ LIVE MONITOR: Auto-check every 2 minutes")
        print(f"✅ Fixed scheduling (skips failed rows)")
        print(f"✅ Multiple no-watermark APIs")
        print(f"✅ Fetch window: 48 or 72 hours (configurable)")
        print(f"✅ Download timeout: {self.download_timeout}s")
        print(f"✅ Max retries per API: {self.max_retries}")
        print(f"Credentials: {self.credentials_folder}")
        print(f"Google Sheet: {self.spreadsheet_id}")
        print(f"Channels: {len(self.channels)}")
        print("="*70)

    def load_state(self) -> Dict:
        """Load persistent state"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def load_channels_config(self):
        """Load channels from JSON config file"""
        channels_file = SCRIPT_DIR / 'tiktok_channels_config.json'

        if channels_file.exists():
            try:
                with open(channels_file, 'r', encoding='utf-8') as f:
                    self.channels = json.load(f)
                    print(f"✓ Loaded {len(self.channels)} channels from config")
            except Exception as e:
                print(f"⚠️  Could not load channels config: {e}{Colors.RESET}")
        else:
            print(f"⚠️  Channels config not found: {channels_file}{Colors.RESET}")

    def save_state(self):
        """Save persistent state"""
        try:
            state = {
                'current_channel_index': self.current_channel_index,
                'processed_videos_this_run': self.processed_videos_this_run,
                'channels_processed_this_run': self.channels_processed_this_run,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"⚠️  Could not save state: {e}{Colors.RESET}")

    def _mark_uploaded(self, video_id: str):
        """Record a successfully-uploaded video id and persist it.

        Previously `processed_videos_this_run` was reset to [] but never
        appended to, so the 'already uploaded' check was dead code and a
        crash/rerun could double-upload. Call this right after a YouTube
        upload succeeds (and only then, so a mid-upload crash isn't skipped).
        """
        id_key = str(video_id)
        if id_key not in self.processed_videos_this_run:
            self.processed_videos_this_run.append(id_key)
            self.save_state()

    def get_random_user_agent(self) -> str:
        """Get random user agent for requests"""
        return random.choice(self.user_agents)

    def init_sheets_client(self):
        # Local Excel mode never starts Google Sheets OAuth or network setup.
        tracking_file=SCRIPT_DIR/'broadcast_config.json'
        try:
            if tracking_file.exists() and json.loads(tracking_file.read_text(encoding='utf-8-sig')).get('tracking_mode')=='excel':
                self.sheets_client=None
                print('Local Excel mode: Google Sheets connection skipped')
                return
        except (OSError, ValueError):
            pass
        """Initialize Google Sheets client"""
        try:
            service_account_file = self.credentials_folder / 'service_account.json'

            if service_account_file.exists():
                creds = ServiceAccountCredentials.from_service_account_file(
                    str(service_account_file),
                    scopes=SHEETS_SCOPES
                )
                self.sheets_client = gspread.authorize(creds)
                print(f"✓ Connected to Google Sheets (Service Account)")
                return

            sheets_token = self.credentials_folder / 'sheets_token.pickle'
            sheets_creds_file = self.credentials_folder / 'sheets_credentials.json'

            creds = None
            if sheets_token.exists():
                with open(sheets_token, 'rb') as token:
                    creds = pickle.load(token)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        print(f"  🔄 Refreshing Google Sheets token...")
                        creds.refresh(Request())
                        print(f"  ✅ Sheets token refreshed successfully")
                        # Save refreshed token
                        with open(sheets_token, 'wb') as token:
                            pickle.dump(creds, token)
                    except Exception as refresh_error:
                        # Refresh failed - token might be revoked
                        error_msg = str(refresh_error).lower()
                        if 'invalid_grant' in error_msg or 'token has been expired or revoked' in error_msg:
                            print(f"  {Colors.RED}⚠️  Sheets refresh token revoked - need to re-authenticate{Colors.RESET}")
                            # Delete old token and force re-auth
                            if sheets_token.exists():
                                sheets_token.unlink()
                            creds = None
                        else:
                            raise refresh_error

                # If refresh failed or no token, start OAuth flow
                if not creds:
                    if not sheets_creds_file.exists():
                        raise FileNotFoundError(f"Missing: {sheets_creds_file}")

                    print(f"🔐 Starting OAuth flow for Google Sheets...")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(sheets_creds_file), SHEETS_SCOPES)

                    # Use dynamic port (port=0) for better compatibility
                    # This works with http://localhost redirect URI in Google Cloud Console
                    try:
                        creds = flow.run_local_server(
                            port=0,
                            open_browser=True,
                            access_type='offline',  # Get refresh token
                            prompt='consent',  # Force consent screen to ensure refresh token
                            success_message='Authentication successful! You can close this window.'
                        )
                    except Exception as flow_error:
                        print(f"  {Colors.RED}❌ OAuth flow failed: {flow_error}{Colors.RESET}")
                        print(f"  {Colors.YELLOW}💡 TIP: Make sure redirect URI 'http://localhost' is configured in Google Cloud Console{Colors.RESET}")
                        raise

                    # Save new token
                    with open(sheets_token, 'wb') as token:
                        pickle.dump(creds, token)

            self.sheets_client = gspread.authorize(creds)
            print(f"✓ Connected to Google Sheets (OAuth2)")

        except Exception as e:
            print(f"⚠️  Sheets connection failed: {e}{Colors.RESET}")
            self.sheets_client = None

    def get_youtube_service(self, channel_config: Dict):
        """Get YouTube API service for a channel"""
        try:
            # Support custom token_file or default to channel_id_token
            token_name = channel_config.get('token_file', f"{channel_config.get('channel_id', 'default')}_token")
            token_file = self.credentials_folder / f"{token_name}.pickle"
            creds_file = self.credentials_folder / channel_config['credentials_file']

            creds = None
            if token_file.exists():
                with open(token_file, 'rb') as token:
                    creds = pickle.load(token)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        print(f"  🔄 Refreshing expired token...")
                        creds.refresh(Request())
                        print(f"  ✅ Token refreshed successfully")
                        # Save refreshed token
                        with open(token_file, 'wb') as token:
                            pickle.dump(creds, token)
                    except Exception as refresh_error:
                        # Refresh failed - token might be revoked
                        error_msg = str(refresh_error).lower()
                        if 'invalid_grant' in error_msg or 'token has been expired or revoked' in error_msg:
                            print(f"  {Colors.RED}⚠️  Refresh token revoked - need to re-authenticate{Colors.RESET}")
                            # Delete old token and force re-auth
                            if token_file.exists():
                                token_file.unlink()
                            creds = None
                        else:
                            print(f"  {Colors.RED}❌ Token refresh failed: {refresh_error}{Colors.RESET}")
                            return None

                # If refresh failed or no token, start OAuth flow
                if not creds:
                    if not creds_file.exists():
                        print(f"{Colors.RED}❌ Missing credentials: {creds_file}{Colors.RESET}")
                        return None

                    print(f"🔐 Starting OAuth flow for: {Colors.GREEN}{channel_config['channel_name']}{Colors.RESET}")
                    print(f"📝 When browser opens, SELECT THE CORRECT CHANNEL:")
                    print(f"   → Channel: {Colors.GREEN}{channel_config['channel_name']}{Colors.RESET}")
                    print(f"   → TikTok: @{channel_config.get('tiktok_username', 'N/A')}")
                    print(f"{Colors.RED}⚠️  IMPORTANT: If you have multiple channels, pick the RIGHT ONE!{Colors.RESET}")

                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(creds_file), YOUTUBE_SCOPES)

                    # Use dynamic port (port=0) for better compatibility
                    # This works with http://localhost redirect URI in Google Cloud Console
                    try:
                        creds = flow.run_local_server(
                            port=0,
                            open_browser=True,
                            access_type='offline',  # Get refresh token
                            prompt='consent',  # Force consent screen to ensure refresh token
                            success_message='Authentication successful! You can close this window.'
                        )
                    except Exception as flow_error:
                        print(f"  {Colors.RED}❌ OAuth flow failed: {flow_error}{Colors.RESET}")
                        print(f"  {Colors.YELLOW}💡 TIP: Make sure redirect URI 'http://localhost' is configured in Google Cloud Console{Colors.RESET}")
                        return None

                    # Save new token
                    with open(token_file, 'wb') as token:
                        pickle.dump(creds, token)

                    print(f"✅ Token saved: {token_file.name}")

            youtube = build('youtube', 'v3', credentials=creds)
            expected = str(channel_config.get('youtube_channel_id','')).strip()
            if not expected:
                self.last_auth_error = 'YouTube Channel ID is required; upload blocked until the destination is configured.'
                print(self.last_auth_error)
                return None
            owned = youtube.channels().list(part='id,snippet', mine=True).execute(num_retries=3).get('items', [])
            if len(owned) != 1 or owned[0].get('id') != expected:
                actual = ', '.join(f"{item.get('snippet',{}).get('title','')} ({item.get('id','')})" for item in owned) or 'no accessible channel'
                self.last_auth_error = f"Wrong YouTube login: expected {channel_config.get('channel_name','')} ({expected}), authenticated as {actual}. Re-authenticate the correct channel. Upload blocked."
                print(self.last_auth_error)
                return None
            self.last_auth_error = ''
            print(f"Verified destination channel: {owned[0]['snippet']['title']} ({expected})")
            return youtube

        except Exception as e:
            self.last_auth_error = str(e)
            print(f"❌ YouTube service error: {e}{Colors.RESET}")
            return None

    def fetch_tiktok_videos_ytdlp(self, username: str) -> List[Dict]:
        """Fetch TikTok videos using yt-dlp (MOST RELIABLE)"""
        try:
            print(f"  🔍 Fetching from TikTok via yt-dlp...")

            # Remove @ if present
            username = username.lstrip('@')

            # TikTok user profile URL
            profile_url = f"https://www.tiktok.com/@{username}"

            # yt-dlp command to fetch user's videos (last 35)
            cmd = [
                sys.executable,  # Use current Python interpreter
                '-m', 'yt_dlp',
                '--dump-json',  # Output JSON metadata
                '--playlist-end', '35',  # Limit to 35 videos
                '--no-download',  # Don't download videos, just get metadata
                '--skip-download',
                '--quiet',  # Suppress warnings
                profile_url
            ]

            # Run yt-dlp with longer timeout (TikTok profile fetching can be slow)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minutes timeout
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode == 0 and result.stdout:
                # Parse JSON lines (each line is a video metadata)
                videos = []
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        try:
                            video_data = json.loads(line)
                            videos.append({
                                'video_id': video_data.get('id'),
                                'id': video_data.get('id'),
                                'title': video_data.get('title', video_data.get('description', '')),
                                'desc': video_data.get('description', video_data.get('title', '')),
                                'create_time': video_data.get('timestamp', 0),
                                'author': {'unique_id': username, 'nickname': video_data.get('uploader', username)},
                                'play': video_data.get('url', ''),
                                'download_addr': video_data.get('url', ''),
                                'webpage_url': video_data.get('webpage_url', f"https://www.tiktok.com/@{username}/video/{video_data.get('id')}")
                            })
                        except json.JSONDecodeError:
                            continue

                if videos:
                    print(f"  {Colors.GREEN}✓ Found {len(videos)} videos via yt-dlp{Colors.RESET}")
                    return videos
                else:
                    print(f"  {Colors.YELLOW}⚠️  No videos found{Colors.RESET}")
                    return []
            else:
                error_msg = result.stderr[:200] if result.stderr else "Unknown error"
                print(f"  {Colors.RED}❌ yt-dlp failed: {error_msg}{Colors.RESET}")
                return []

        except subprocess.TimeoutExpired:
            print(f"  {Colors.RED}❌ yt-dlp timeout (120s) - TikTok is slow to respond{Colors.RESET}")
            print(f"  {Colors.YELLOW}💡 TIP: Profile fetching is unreliable. Consider using Google Sheets instead.{Colors.RESET}")
            return []
        except Exception as e:
            print(f"  {Colors.RED}❌ yt-dlp error: {e}{Colors.RESET}")
            return []

    def fetch_tiktok_videos_tikwm(self, username: str) -> List[Dict]:
        """Fetch videos using TikWM API with multi-endpoint retry"""
        try:
            print(f"  🔍 Fetching from tikwm.com...")

            # Remove @ if present
            username = username.lstrip('@')

            # Try multiple TikWM endpoints
            endpoints = [
                f"https://www.tikwm.com/api/user/posts",
                f"https://tikwm.com/api/user/posts",
                f"https://api.tikwm.com/api/user/posts"
            ]

            for endpoint in endpoints:
                try:
                    headers = {
                        'User-Agent': self.get_random_user_agent(),
                        'Accept': 'application/json',
                        'Referer': 'https://www.tikwm.com/',
                        'Origin': 'https://www.tikwm.com'
                    }

                    # TikWM requires unique_id parameter
                    params = {
                        'unique_id': username,
                        'count': 35  # Fetch last 35 videos
                    }

                    response = requests.get(
                        endpoint,
                        params=params,
                        headers=headers,
                        timeout=30
                    )

                    if response.status_code == 200:
                        data = response.json()

                        if data.get('code') == 0 and 'data' in data:
                            videos = data['data'].get('videos', [])

                            if videos:
                                print(f"  ✓ Found {len(videos)} videos")
                                # Convert to standard format
                                formatted_videos = []
                                for video in videos:
                                    formatted_videos.append({
                                        'video_id': video.get('video_id') or video.get('id'),
                                        'id': video.get('video_id') or video.get('id'),
                                        'title': video.get('title') or video.get('desc', ''),
                                        'desc': video.get('desc') or video.get('title', ''),
                                        'create_time': video.get('create_time', 0),
                                        'author': video.get('author', {}),
                                        'play': video.get('play', ''),
                                        'download_addr': video.get('download_addr', video.get('play', ''))
                                    })
                                return formatted_videos
                    else:
                        print(f"  {Colors.YELLOW}⚠️  Endpoint {endpoint} returned {response.status_code}, trying next...{Colors.RESET}")
                        continue

                except Exception as e:
                    print(f"  {Colors.YELLOW}⚠️  Endpoint {endpoint} failed: {str(e)[:50]}, trying next...{Colors.RESET}")
                    continue

            print(f"  {Colors.RED}❌ All TikWM endpoints failed{Colors.RESET}")
            return []

        except Exception as e:
            print(f"  {Colors.RED}❌ TikWM error: {e}{Colors.RESET}")
            return []

    def fetch_tiktok_videos_ssstik(self, username: str) -> List[Dict]:
        """Fetch videos using ssstik.io API"""
        try:
            print(f"  🔍 Fetching from ssstik.io...")

            api_url = f"https://ssstik.io/api/profile/{username}"

            headers = {
                'User-Agent': self.get_random_user_agent(),
                'Accept': 'application/json',
                'Referer': 'https://ssstik.io/',
                'Origin': 'https://ssstik.io'
            }

            response = requests.get(
                api_url,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                videos = data.get('data', {}).get('videos', [])

                if videos:
                    print(f"  ✓ Found {len(videos)} videos")
                    return videos
                else:
                    print(f"  {Colors.RED}⚠️  No videos in response{Colors.RESET}")
                    return []
            else:
                print(f"  {Colors.RED}❌ Status {response.status_code}{Colors.RESET}")
                return []

        except Exception as e:
            print(f"  {Colors.RED}❌ ssstik error: {e}{Colors.RESET}")
            return []

    def fetch_tiktok_videos_snaptik(self, username: str) -> List[Dict]:
        """Fetch videos using snaptik.app API"""
        try:
            print(f"  🔍 Fetching from snaptik.app...")

            api_url = f"https://www.snaptik.app/api/ajaxSearch"

            headers = {
                'User-Agent': self.get_random_user_agent(),
                'Accept': 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': 'https://snaptik.app/',
                'Origin': 'https://snaptik.app'
            }

            data = {
                'q': f'https://www.tiktok.com/@{username}',
                'lang': 'en'
            }

            response = requests.post(
                api_url,
                headers=headers,
                data=data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                videos = result.get('data', [])

                if videos:
                    print(f"  ✓ Found {len(videos)} videos")
                    return videos
                else:
                    print(f"  {Colors.RED}⚠️  No videos in response{Colors.RESET}")
                    return []
            else:
                print(f"  {Colors.RED}❌ Status {response.status_code}{Colors.RESET}")
                return []

        except Exception as e:
            print(f"  {Colors.RED}❌ snaptik error: {e}{Colors.RESET}")
            return []

    def fetch_tiktok_videos_playwright(self, username: str) -> List[Dict]:
        """Fetch TikTok videos using Playwright (acts like real browser)"""
        try:
            print(f"  🔍 Fetching from TikTok via Playwright (browser mode)...")

            from playwright.sync_api import sync_playwright
            import re

            username = username.lstrip('@')
            profile_url = f"https://www.tiktok.com/@{username}"

            with sync_playwright() as p:
                # Launch browser with anti-detection settings (visible mode to bypass captcha)
                browser = p.chromium.launch(
                    headless=False,  # Run visible to avoid captcha
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-web-security'
                    ]
                )

                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    locale='en-US',
                    timezone_id='America/New_York',
                    extra_http_headers={
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1'
                    }
                )

                page = context.new_page()

                # Remove webdriver detection
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = {runtime: {}};
                """)

                # Navigate to profile
                print(f"  ⏳ Loading TikTok (browser will open)...")
                page.goto(profile_url, wait_until='domcontentloaded', timeout=90000)  # Increased to 90 seconds

                # Check for captcha and wait for manual solving
                time.sleep(8)  # Increased from 5 to 8 seconds for page to fully load
                captcha_present = page.evaluate("""() => {
                    const captchaText = document.body.innerText;
                    return captchaText.includes('Drag the slider') ||
                           captchaText.includes('verification') ||
                           captchaText.includes('puzzle');
                }""")

                if captcha_present:
                    print(f"  {Colors.YELLOW}⚠️  CAPTCHA detected! Please solve it in the browser window...{Colors.RESET}")
                    print(f"  {Colors.YELLOW}⏳ Waiting 30 seconds for you to solve the captcha...{Colors.RESET}")
                    time.sleep(30)  # Give user time to solve captcha
                    print(f"  {Colors.GREEN}✓ Continuing...{Colors.RESET}")

                # Click on "Videos" tab to ensure we're viewing videos
                try:
                    page.click('div[role="tab"]:has-text("Videos"), a:has-text("Videos")', timeout=10000)  # Increased timeout
                    time.sleep(5)  # Increased from 2 to 5 seconds to let videos load
                except:
                    time.sleep(3)  # Even if tab click fails, wait for content to load

                # Aggressive scrolling to trigger lazy-loading (load more videos)
                print(f"  ⏳ Scrolling to load videos...")

                # Scroll down multiple times to load as many videos as possible
                for i in range(20):  # Increased to 20 scrolls to load more videos
                    page.evaluate(f'window.scrollTo(0, {(i + 1) * 1000})')  # Scroll further each time
                    time.sleep(1.5)  # Wait for lazy loading

                # Scroll to bottom to trigger any remaining lazy loads
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                time.sleep(3)

                # Scroll back to top
                page.evaluate('window.scrollTo(0, 0)')
                time.sleep(5)  # Let content fully render

                # Try multiple selectors to extract video URLs
                video_data = page.evaluate(r"""() => {
                    const videos = [];
                    const videoUrls = new Set();

                    // Try multiple selectors that TikTok uses
                    const selectors = [
                        'a[href*="/video/"]',
                        '[data-e2e="user-post-item"] a',
                        '[data-e2e="user-post-item-list"] a',
                        'div[class*="video"] a[href*="/video/"]',
                        'div[class*="DivItemContainerV2"] a',
                        'div[data-e2e="user-post-item-list"] a',
                        'div[class*="DivContainer"] a[href*="/video/"]'
                    ];

                    // Try each selector
                    for (const selector of selectors) {
                        const links = document.querySelectorAll(selector);
                        links.forEach(link => {
                            const href = link.getAttribute('href');
                            if (href && href.includes('/video/')) {
                                videoUrls.add(href);
                            }
                        });

                        if (videoUrls.size > 0) break; // Found videos, stop trying
                    }

                    // If still no videos, try getting all links and filtering
                    if (videoUrls.size === 0) {
                        const allLinks = document.querySelectorAll('a');
                        allLinks.forEach(link => {
                            const href = link.getAttribute('href');
                            if (href && href.includes('/video/') && /\/video\/\d+/.test(href)) {
                                videoUrls.add(href);
                            }
                        });
                    }

                    // Convert URLs to video objects
                    let count = 0;
                    const username = window.location.pathname.split('/')[1].replace('@', '');

                    for (const url of videoUrls) {
                        // Removed 35 video limit - fetch all videos found

                        const videoId = url.split('/video/')[1]?.split('?')[0];
                        if (videoId && /^\d+$/.test(videoId)) {
                            // Construct proper TikTok URL with username
                            const fullUrl = `https://www.tiktok.com/@${username}/video/${videoId}`;

                            // Try to find the video element to extract title/description and timestamp
                            let title = 'TikTok Video';
                            let desc = '';
                            let createTime = 0;  // Will use yt-dlp as fallback if not found

                            // Try to find the parent element containing this video
                            const allLinks = document.querySelectorAll('a[href*="/video/"]');
                            for (const link of allLinks) {
                                if (link.href && link.href.includes(videoId)) {
                                    // Look for text content near this link
                                    const parent = link.closest('div[data-e2e="user-post-item"]') ||
                                                   link.closest('div[class*="DivItemContainer"]') ||
                                                   link.parentElement;

                                    if (parent) {
                                        // Try to find description/title text
                                        const textElements = parent.querySelectorAll('span, p, h1, h2, h3');
                                        for (const el of textElements) {
                                            const text = el.textContent?.trim();
                                            if (text && text.length > 5 && text.length < 200) {
                                                if (!title || title === 'TikTok Video') {
                                                    title = text;
                                                    desc = text;
                                                }
                                                break;
                                            }
                                        }

                                        // Try to find timestamp - TikTok shows relative time like "2d ago", "3w ago"
                                        const timeElements = parent.querySelectorAll('span[data-e2e="browser-nickname"] + span, span[class*="DivTimeTag"], time');
                                        for (const timeEl of timeElements) {
                                            const timeText = timeEl.textContent?.trim();
                                            if (timeText) {
                                                // Parse relative time strings like "2d ago", "3w ago", "1m ago"
                                                const match = timeText.match(/(\d+)([smhdwMy])/);
                                                if (match) {
                                                    const value = parseInt(match[1]);
                                                    const unit = match[2];
                                                    const now = Math.floor(Date.now() / 1000);

                                                    // Convert to seconds
                                                    let secondsAgo = 0;
                                                    if (unit === 's') secondsAgo = value;
                                                    else if (unit === 'm') secondsAgo = value * 60;
                                                    else if (unit === 'h') secondsAgo = value * 3600;
                                                    else if (unit === 'd') secondsAgo = value * 86400;
                                                    else if (unit === 'w') secondsAgo = value * 604800;
                                                    else if (unit === 'M') secondsAgo = value * 2592000; // ~30 days
                                                    else if (unit === 'y') secondsAgo = value * 31536000;

                                                    createTime = now - secondsAgo;
                                                    break;
                                                }
                                            }
                                        }
                                    }
                                    break;
                                }
                            }

                            videos.push({
                                video_id: videoId,
                                id: videoId,
                                title: title,
                                desc: desc,
                                create_time: createTime,  // Extracted timestamp (0 if not found, will use yt-dlp)
                                author: {unique_id: username},
                                play: '',
                                download_addr: '',
                                webpage_url: fullUrl
                            });
                            count++;
                        }
                    }

                    return videos;
                }""")

                # Take screenshot for debugging if no videos found
                if not video_data:
                    try:
                        screenshot_path = Path(__file__).parent / 'tiktok_debug_screenshot.png'
                        page.screenshot(path=str(screenshot_path))
                        print(f"  {Colors.YELLOW}⚠️  Debug screenshot saved: {screenshot_path}{Colors.RESET}")
                    except:
                        pass

                browser.close()

                if video_data:
                    print(f"  {Colors.GREEN}✓ Found {len(video_data)} videos via Playwright{Colors.RESET}")
                    return video_data
                else:
                    print(f"  {Colors.YELLOW}⚠️  No videos found - TikTok may have changed page structure{Colors.RESET}")
                    return []

        except Exception as e:
            print(f"  {Colors.YELLOW}⚠️  Playwright error: {str(e)[:100]}{Colors.RESET}")
            return []

    def fetch_tiktok_videos(self, username: str) -> List[Dict]:
        """Fetch TikTok videos with multiple API fallbacks"""
        print(f"\n📱 Fetching TikTok videos: @{username}")

        # Try Playwright FIRST (acts like real browser, bypasses anti-bot)
        videos = self.fetch_tiktok_videos_playwright(username)
        if videos:
            return videos

        time.sleep(2)

        # Try yt-dlp as fallback
        videos = self.fetch_tiktok_videos_ytdlp(username)
        if videos:
            return videos

        time.sleep(2)

        # Try TikWM as fallback
        videos = self.fetch_tiktok_videos_tikwm(username)
        if videos:
            return videos

        time.sleep(2)

        # Try ssstik as fallback
        videos = self.fetch_tiktok_videos_ssstik(username)
        if videos:
            return videos

        time.sleep(2)

        # Try snaptik as last fallback
        videos = self.fetch_tiktok_videos_snaptik(username)
        if videos:
            return videos

        print(f"  {Colors.RED}❌ All APIs failed for @{username}{Colors.RESET}")
        return []

    def filter_recent_videos(self, videos: List[Dict], hours: int = 72) -> List[Dict]:
        """Filter videos from last N hours. hours <= 0 means 'all videos'."""
        if not videos:
            return []

        if hours <= 0:
            # Return everything (all known uploads + unknown-time) for 'fetch all'
            return videos

        cutoff = datetime.now() - timedelta(hours=hours)
        recent = []
        unknown_time = []  # Videos with no timestamp (will check with yt-dlp later)

        for video in videos:
            create_time = video.get('create_time', 0)
            if create_time:
                # Has timestamp - check if within time window
                video_date = datetime.fromtimestamp(create_time)
                if video_date >= cutoff:
                    recent.append(video)
            else:
                # No timestamp from Playwright - keep for yt-dlp verification
                unknown_time.append(video)

        # Combine: videos within time window + videos with unknown time (to be checked)
        combined = recent + unknown_time

        if unknown_time:
            print(f"  ✓ Filtered: {len(recent)}/{len(videos)} from last {hours}h ({len(unknown_time)} pending yt-dlp check)")
        else:
            print(f"  ✓ Filtered: {len(recent)}/{len(videos)} from last {hours}h")

        return combined

    def download_video_binary_single_api(self, url: str, video_id: str, api_name: str) -> Optional[bytes]:
        """Download video from single API with retry"""
        for attempt in range(self.max_retries):
            try:
                headers = {
                    'User-Agent': self.get_random_user_agent(),
                    'Accept': '*/*',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive'
                }

                response = requests.get(
                    url,
                    headers=headers,
                    timeout=self.download_timeout,
                    stream=True
                )

                if response.status_code == 200:
                    content = BytesIO()
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            content.write(chunk)

                    video_data = content.getvalue()

                    if len(video_data) > 100000:
                        size_mb = len(video_data) / (1024 * 1024)
                        print(f"  ✓ {api_name}: {size_mb:.2f} MB")
                        return video_data
                    else:
                        print(f"  {Colors.RED}⚠️  {api_name}: File too small ({len(video_data)} bytes){Colors.RESET}")

            except Exception as e:
                print(f"  {Colors.RED}❌ {api_name} attempt {attempt + 1}/{self.max_retries}: {e}{Colors.RESET}")

            if attempt < self.max_retries - 1:
                delay = self.retry_delay_base * (2 ** attempt)
                time.sleep(delay)

        return None

    def download_video_ytdlp(self, video_id: str) -> Optional[bytes]:
        """Download TikTok video using yt-dlp (MOST RELIABLE)"""
        try:
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as temp_dir:
                output_template = str(Path(temp_dir) / f'tiktok_{video_id}.%(ext)s')

                # Build yt-dlp command
                cmd = [
                    sys.executable,
                    '-m', 'yt_dlp',
                    '--no-playlist',
                    '--output', output_template,
                    f'https://www.tiktok.com/video/{video_id}'
                ]

                # Run yt-dlp to download the video
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=90,  # 90 seconds timeout
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )

                if result.returncode == 0:
                    # Find downloaded video file
                    temp_path = Path(temp_dir)
                    video_files = list(temp_path.glob(f'tiktok_{video_id}.*'))

                    if video_files:
                        video_file = video_files[0]
                        video_data = video_file.read_bytes()

                        if len(video_data) > 100000:  # Must be > 100KB
                            size_mb = len(video_data) / (1024 * 1024)
                            print(f"  {Colors.GREEN}✓ yt-dlp: {size_mb:.2f} MB{Colors.RESET}")
                            return video_data
                        else:
                            print(f"  {Colors.YELLOW}⚠️  yt-dlp: File too small ({len(video_data)} bytes){Colors.RESET}")
                    else:
                        print(f"  {Colors.YELLOW}⚠️  yt-dlp: No video file found{Colors.RESET}")
                else:
                    error_msg = result.stderr[:200] if result.stderr else "Unknown error"
                    print(f"  {Colors.YELLOW}⚠️  yt-dlp failed: {error_msg}{Colors.RESET}")

        except subprocess.TimeoutExpired:
            print(f"  {Colors.YELLOW}⚠️  yt-dlp timeout (90s){Colors.RESET}")
        except Exception as e:
            print(f"  {Colors.YELLOW}⚠️  yt-dlp error: {str(e)[:100]}{Colors.RESET}")

        return None

    def download_video_binary(self, mp4_url: str, video_id: str) -> Optional[bytes]:
        """Download video with multiple API fallbacks - yt-dlp FIRST!"""
        print(f"  📥 Downloading video...")

        # 1. Try yt-dlp FIRST (most reliable, no watermarks!)
        video_data = self.download_video_ytdlp(video_id)
        if video_data:
            return video_data

        print(f"  {Colors.YELLOW}🔄 Trying web APIs as fallback...{Colors.RESET}")

        # 2. Try primary URL from metadata
        video_data = self.download_video_binary_single_api(mp4_url, video_id, "Primary")
        if video_data:
            return video_data

        # 3. Try TikWM as final fallback (NEVER use SSSTik - always gives corrupted 1.55 MB files!)
        time.sleep(self.request_delay)
        video_data = self.download_video_binary_single_api(
            f'https://www.tikwm.com/api/download?url=https://www.tiktok.com/video/{video_id}',
            video_id,
            'TikWM'
        )
        if video_data:
            return video_data

        print(f"  {Colors.RED}❌ All download methods failed{Colors.RESET}")
        return None

    def format_title(self, original_title: str, channel_config: Dict, sheet_title: str = None) -> str:
        """Format title with smart truncation

        Args:
            original_title: TikTok video title
            channel_config: Channel configuration
            sheet_title: Title from Google Sheets (for 'sheet' format)
        """
        title_format = channel_config.get('title_format', 'replace')
        prefix = channel_config.get('title_prefix', '')
        suffix = channel_config.get('title_suffix', '')

        # Handle 'sheet' format - use title from Google Sheets
        if title_format == 'sheet':
            if sheet_title:
                # Use sheet title with prefix/suffix
                formatted = f"{prefix} {sheet_title} {suffix}".strip()

                # Ensure under 100 characters
                if len(formatted) > 100:
                    formatted = formatted[:97] + '...'

                return formatted
            else:
                # Fallback to replace if no sheet title provided
                title_format = 'replace'

        # Extract hashtags
        hashtags = re.findall(r'#\w+', original_title)

        # Remove hashtags from title
        clean_title = re.sub(r'#\w+', '', original_title).strip()

        # Split into words
        words = clean_title.split()

        # Take first 8 words
        truncated_words = ' '.join(words[:8])

        # Take first 2 hashtags
        truncated_hashtags = ' '.join(hashtags[:2])

        # Combine
        base_title = f"{truncated_words} {truncated_hashtags}".strip()

        # Apply format
        if title_format == 'prepend':
            formatted = f"{prefix} {base_title}".strip()
        elif title_format == 'append':
            formatted = f"{base_title} {suffix}".strip()
        elif title_format == 'wrap':
            formatted = f"{prefix} {base_title} {suffix}".strip()
        else:
            formatted = base_title

        # Sanitize and ensure under 100 characters
        formatted = self.sanitize_for_youtube(formatted, max_length=100)

        return formatted

    def sanitize_for_youtube(self, text: str, max_length: int = None) -> str:
        """Sanitize text to remove invalid characters for YouTube

        Args:
            text: Text to sanitize
            max_length: Maximum length (optional)
        """
        if not text:
            return ""

        # Remove or replace characters that YouTube doesn't accept
        # Remove angle brackets (often used in HTML, YouTube rejects them)
        text = text.replace('<', '').replace('>', '')

        # Remove null bytes and control characters (except newlines, carriage returns, tabs)
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')

        # Remove any leading/trailing whitespace
        text = text.strip()

        # Apply length limit if specified
        if max_length and len(text) > max_length:
            text = text[:max_length - 3] + "..."

        return text

    def sanitize_description(self, text: str) -> str:
        """Sanitize description to remove invalid characters for YouTube"""
        # Use the general sanitizer with YouTube's description max length (5000 chars)
        return self.sanitize_for_youtube(text, max_length=5000)

    def format_description(self, tiktok_caption: str, channel_config: Dict) -> str:
        """Format description with default if available"""
        # Sanitize the caption first
        tiktok_caption = self.sanitize_description(tiktok_caption)

        default_desc = channel_config.get('default_description', '').strip()
        default_desc = self.sanitize_description(default_desc)

        if not default_desc:
            return tiktok_caption

        format_type = channel_config.get('description_format', 'prepend')

        if format_type == 'prepend':
            result = f"{default_desc}\n\n{tiktok_caption}"
        elif format_type == 'append':
            result = f"{tiktok_caption}\n\n{default_desc}"
        elif format_type == 'replace':
            result = default_desc
        else:
            result = tiktok_caption

        # Final sanitization of combined description
        return self.sanitize_description(result)

    def _load_quota_cooldowns(self):
        """Reload persisted quota cooldowns from disk into memory."""
        try:
            if self.quota_cooldown_file.exists():
                with open(self.quota_cooldown_file, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                for ch, iso_ts in raw.items():
                    try:
                        self.quota_exceeded_channels[ch] = datetime.fromisoformat(iso_ts)
                    except (ValueError, TypeError):
                        continue  # skip corrupt entries
        except Exception as e:
            print(f"⚠️  Could not load quota cooldowns: {e}{Colors.RESET}")

    def _save_quota_cooldowns(self):
        """Persist current quota cooldowns to disk."""
        try:
            with open(self.quota_cooldown_file, 'w', encoding='utf-8') as f:
                json.dump({ch: ts.isoformat() for ch, ts in self.quota_exceeded_channels.items()},
                          f, indent=2)
        except Exception as e:
            print(f"⚠️  Could not save quota cooldowns: {e}{Colors.RESET}")

    def is_channel_in_quota_cooldown(self, channel_id: str) -> bool:
        """Check if channel is in quota exceeded cooldown period"""
        if channel_id not in self.quota_exceeded_channels:
            return False

        exceeded_time = self.quota_exceeded_channels[channel_id]
        time_diff = datetime.now() - exceeded_time
        hours_passed = time_diff.total_seconds() / 3600

        if hours_passed >= self.quota_cooldown_hours:
            # Cooldown period over, remove from tracking
            del self.quota_exceeded_channels[channel_id]
            self._save_quota_cooldowns()
            return False

        return True

    def get_quota_cooldown_remaining(self, channel_id: str) -> float:
        """Get remaining cooldown hours for a channel"""
        if channel_id not in self.quota_exceeded_channels:
            return 0

        exceeded_time = self.quota_exceeded_channels[channel_id]
        time_diff = datetime.now() - exceeded_time
        hours_passed = time_diff.total_seconds() / 3600
        remaining = self.quota_cooldown_hours - hours_passed

        return max(0, remaining)

    def mark_channel_quota_exceeded(self, channel_id: str, channel_name: str):
        """Mark channel as quota exceeded with 24-hour cooldown (persisted)"""
        self.quota_exceeded_channels[channel_id] = datetime.now()
        self._save_quota_cooldowns()
        remaining_time = datetime.now() + timedelta(hours=self.quota_cooldown_hours)
        print(f"\n⚠️  QUOTA EXCEEDED for '{channel_name}'{Colors.RESET}")
        print(f"🕐 Channel will be skipped until: {remaining_time.strftime('%d-%b-%Y %I:%M %p')}")
        print(f"⏳ Cooldown period: {self.quota_cooldown_hours} hours (persisted across restarts)")

    def check_quota_notice_in_sheet(self, sheet_tab_name: str) -> bool:
        """Check if there's already a quota notice in the sheet (column K)"""
        try:
            if not self.sheets_client:
                return False

            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
            worksheet = sheet.worksheet(sheet_tab_name)

            # Check column K for quota notice
            column_k = worksheet.col_values(11)  # Column K is index 11

            for idx, cell_value in enumerate(column_k, start=1):
                if cell_value and 'QUOTA EXCEEDED' in cell_value:
                    # Extract cooldown time from notice
                    import re
                    match = re.search(r'Cooldown until (.+)', cell_value)
                    if match:
                        cooldown_str = match.group(1)
                        try:
                            cooldown_time = datetime.strptime(cooldown_str, '%d-%b-%Y %I:%M %p')
                            # Check if cooldown is still active
                            if datetime.now() < cooldown_time:
                                remaining_hours = (cooldown_time - datetime.now()).total_seconds() / 3600
                                print(f"  {Colors.YELLOW}⏸️  Found active quota notice in sheet - {remaining_hours:.1f} hours remaining{Colors.RESET}")
                                return True
                            else:
                                print(f"  ✅ Found expired quota notice in sheet - deleting it now")
                                # Delete the expired notice
                                worksheet.update(f'K{idx}', [['']], value_input_option='USER_ENTERED')
                                # Remove red background
                                worksheet.format(f'K{idx}', {'backgroundColor': {'red': 1.0, 'green': 1.0, 'blue': 1.0}})
                                print(f"  🗑️  Deleted expired quota notice from row {idx}")
                                return False
                        except:
                            pass
            return False

        except Exception as e:
            print(f"  {Colors.RED}⚠️  Could not check quota notice: {e}{Colors.RESET}")
            return False

    def add_quota_notice_to_sheet(self, sheet_tab_name: str, row_index: int, cooldown_until: str):
        """Add a visible quota cooldown notice to the error column (K) at the specific row"""
        try:
            if not self.sheets_client:
                return

            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
            worksheet = sheet.worksheet(sheet_tab_name)

            # Add notice to column K (error column) at the row where quota happened
            notice = f"⚠️ QUOTA EXCEEDED - Cooldown until {cooldown_until}"
            worksheet.update(f'K{row_index}', [[notice]], value_input_option='USER_ENTERED')

            # Format cell with red background
            worksheet.format(f'K{row_index}', {
                'backgroundColor': {'red': 1.0, 'green': 0.8, 'blue': 0.8},
                'textFormat': {'bold': True, 'fontSize': 10},
                'horizontalAlignment': 'LEFT'
            })

            print(f"  📝 Added quota notice to sheet row {row_index}, column K")

        except Exception as e:
            print(f"  {Colors.RED}⚠️  Could not add quota notice to sheet: {e}{Colors.RESET}")

    def upload_to_youtube(
        self,
        channel_config: Dict,
        video_data: bytes,
        video_info: Dict,
        scheduled_time: str
    ) -> Optional[Dict]:
        """Upload video to YouTube"""
        self.last_upload_error = ''
        try:
            print(f"  📤 Uploading to YouTube...")

            youtube = self.get_youtube_service(channel_config)
            if not youtube:
                self.last_upload_error = (
                    getattr(self, 'last_auth_error', '') or
                    f"Could not open YouTube service for {channel_config.get('channel_name', channel_config.get('channel_id', 'channel'))}; check credentials."
                )
                return None

            # Format title and description
            # Pass video_info['title'] as sheet_title parameter for 'sheet' format option
            formatted_title = self.format_title(
                video_info['title'],
                channel_config,
                sheet_title=video_info.get('title', '')
            )
            formatted_description = self.format_description(video_info['caption'], channel_config)

            # Parse schedule time (local time)
            schedule_dt = datetime.strptime(scheduled_time, '%d-%b-%Y %I:%M %p')

            # Convert local time to UTC for the YouTube API (DST-aware).
            # time.mktime interprets the naive local datetime using the DST
            # rule for that exact date, so the result stays correct even when
            # the scheduled time crosses a daylight-saving boundary.
            import time as time_module
            try:
                epoch = time_module.mktime(schedule_dt.timetuple())
                schedule_dt_utc = datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)
                utc_offset_hours = (schedule_dt - schedule_dt_utc).total_seconds() / 3600
            except Exception:
                # Best-effort fallback using the current offset.
                utc_offset_seconds = time_module.altzone if time_module.daylight else time_module.timezone
                utc_offset_hours = -utc_offset_seconds / 3600
                schedule_dt_utc = schedule_dt - timedelta(hours=utc_offset_hours)

            print(f"  🌍 Local time: {schedule_dt.strftime('%d-%b-%Y %I:%M %p')}")
            print(f"  🌐 UTC time: {schedule_dt_utc.strftime('%d-%b-%Y %I:%M %p')} (offset: {utc_offset_hours:+.1f}h)")

            from video_tags import upload_tags
            tags = upload_tags(video_info, channel_config)
            print(f'  Keyword tags: {len(tags)} (video metadata first, channel defaults if blank)')

            # Prepare request
            body = {
                'snippet': {
                    'title': formatted_title,
                    'description': formatted_description,
                    'tags': tags,
                    'categoryId': '24'
                },
                'status': {
                    'privacyStatus': 'private',
                    'publishAt': schedule_dt_utc.isoformat() + 'Z',
                    'selfDeclaredMadeForKids': False
                }
            }

            # Upload with progress tracking
            media = MediaIoBaseUpload(
                BytesIO(video_data),
                mimetype='video/mp4',
                resumable=True,
                chunksize=1024*1024
            )

            request = youtube.videos().insert(
                part='snippet,status',
                body=body,
                media_body=media
            )

            # Execute with progress
            response = None
            last_progress = 0

            print("  Upload started (automatic network retries enabled)")
            while response is None:
                # Keep the same resumable request/session when SSL or socket
                # connections fail. The installed Google client retries these
                # transport failures with backoff and tracks upload progress.
                status, response = request.next_chunk(num_retries=3)
                if status:
                    progress = int(status.progress() * 100)
                    # Show progress every 20%
                    if progress >= last_progress + 15:
                        print(f"  📊 Upload progress: {progress}%")
                        last_progress = progress

            youtube_url = f"https://www.youtube.com/watch?v={response['id']}"
            video_id = response['id']

            youtube_data = {
                'youtube_id': video_id,
                'youtube_url': youtube_url,
                'formatted_title': formatted_title,
                'formatted_description': formatted_description,
                'tags': tags
            }

            print(f"  ✅ Uploaded successfully!")
            print(f"  🔗 {Colors.GREEN}{youtube_url}{Colors.RESET}")

            # Add to playlist if configured
            playlist_id = channel_config.get('default_playlist_id', '').strip()
            if playlist_id:
                self.add_video_to_playlist(youtube, video_id, playlist_id)

            return youtube_data

        except HttpError as e:
            # YouTube API specific errors
            error_msg = str(e).lower()
            raw_content = getattr(e, 'content', b'') or b''
            error_content = raw_content.decode('utf-8', errors='replace') if isinstance(raw_content, bytes) else str(raw_content)
            self.last_upload_error = f"HTTP {getattr(getattr(e, 'resp', None), 'status', '?')}: {error_content[:700] or str(e)}"

            # Log detailed error info for debugging
            print(f"\n  🔍 DEBUG: YouTube API Error Details")
            print(f"  📝 Error message: {str(e)}")
            if hasattr(e, 'resp'):
                print(f"  🔢 HTTP Status: {e.resp.status}")
            if error_content:
                print(f"  📄 Error content: {error_content[:500]}")  # First 500 chars

            # Check for quota exceeded errors (HTTP 403 with quotaExceeded reason)
            is_quota_error = False

            # Check error message
            if 'quota' in error_msg or 'quotaexceeded' in error_msg:
                is_quota_error = True
                print(f"  {Colors.RED}⚠️  Quota keyword found in error message{Colors.RESET}")

            # Check HTTP status code 403 (Forbidden - typical for quota errors)
            if hasattr(e, 'resp') and e.resp.status == 403:
                if 'quota' in error_content.lower() or 'quotaexceeded' in error_content.lower():
                    is_quota_error = True
                    print(f"  {Colors.RED}⚠️  HTTP 403 with quota keyword detected{Colors.RESET}")

            # Check for specific error reasons in response
            try:
                error_details = json.loads(error_content)
                if 'error' in error_details:
                    errors = error_details['error'].get('errors', [])
                    for err in errors:
                        reason = err.get('reason', '').lower()
                        print(f"  🔍 Error reason: {reason}")
                        if reason in ['quotaexceeded', 'dailylimitexceeded', 'ratelimitexceeded', 'userratelimitexceeded', 'uploadlimitexceeded']:
                            is_quota_error = True
                            print(f"  {Colors.RED}⚠️  Quota error reason detected: {reason}{Colors.RESET}")
                            break
            except:
                pass

            if is_quota_error:
                channel_id = channel_config.get('channel_id', 'unknown')
                channel_name = channel_config.get('channel_name', 'Unknown Channel')
                self.mark_channel_quota_exceeded(channel_id, channel_name)
            else:
                print(f"  ℹ️  Not identified as quota error")

            print(f"  {Colors.RED}❌ Upload failed: {e}{Colors.RESET}")
            return None

        except Exception as e:
            self.last_upload_error = f"{type(e).__name__}: {e}"
            # Other exceptions
            error_msg = str(e).lower()

            # Check for quota in general exception messages
            if 'quota' in error_msg or 'quotaexceeded' in error_msg or 'limit exceeded' in error_msg or 'uploadlimitexceeded' in error_msg:
                channel_id = channel_config.get('channel_id', 'unknown')
                channel_name = channel_config.get('channel_name', 'Unknown Channel')
                self.mark_channel_quota_exceeded(channel_id, channel_name)

            print(f"  {Colors.RED}❌ Upload failed: {e}{Colors.RESET}")
            return None

    @staticmethod
    def prepare_thumbnail(image_path):
        """Create an in-memory upload copy under the client's 2 MB limit."""
        from PIL import Image, ImageOps
        from io import BytesIO
        image_path = Path(image_path)
        limit = 2 * 1024 * 1024
        raw = image_path.read_bytes()
        mime = 'image/png' if image_path.suffix.lower() == '.png' else 'image/jpeg'
        if len(raw) < limit:
            return raw, mime
        with Image.open(BytesIO(raw)) as original:
            oriented = ImageOps.exif_transpose(original)
            rgba = oriented.convert('RGBA')
            rgb = Image.new('RGB', rgba.size, 'white')
            rgb.paste(rgba, mask=rgba.getchannel('A'))
            rgb.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
            while True:
                for quality in (92, 85, 75, 65, 50):
                    buffer = BytesIO()
                    rgb.save(buffer, format='JPEG', quality=quality, optimize=True)
                    compressed = buffer.getvalue()
                    if len(compressed) < limit:
                        print(f'  Thumbnail compressed: {len(raw)//1024} KB -> {len(compressed)//1024} KB (original unchanged)')
                        return compressed, 'image/jpeg'
                width, height = rgb.size
                if max(width, height) <= 320:
                    raise ValueError('Cannot compress thumbnail below 2 MB')
                rgb = rgb.resize((max(1, int(width*.75)), max(1, int(height*.75))), Image.Resampling.LANCZOS)

    def set_video_thumbnail(self, channel_config, video_id, image_path, stop=None):
        """Retry thumbnail separately from video upload; never re-upload video."""
        try:
            from googleapiclient.http import MediaIoBaseUpload
            import time
            image = Path(image_path)
            thumbnail_bytes, mime = self.prepare_thumbnail(image)
            youtube = self.get_youtube_service(channel_config)
            if not youtube:
                raise RuntimeError('YouTube authentication unavailable for thumbnail')
            # A Short must finish processing before thumbnails.set is called.
            deadline = time.monotonic() + 600
            print(f'  Waiting for YouTube processing before thumbnail: {video_id}')
            polls = 0
            while True:
                if stop and stop.is_set():
                    return False
                result = youtube.videos().list(part='processingDetails', id=video_id).execute(num_retries=3)
                items = result.get('items', [])
                status = items[0].get('processingDetails', {}).get('processingStatus') if items else None
                polls += 1
                if polls == 1 or polls % 6 == 0:
                    print(f'  Video {video_id} processing status: {status or "not available yet"}')
                if status == 'succeeded':
                    break
                if status in ('failed', 'terminated'):
                    raise RuntimeError(f'Video processing {status}')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Video still processing; restart queue later to retry thumbnail')
                if stop:
                    if stop.wait(5):
                        return False
                else:
                    time.sleep(5)
            media = MediaIoBaseUpload(BytesIO(thumbnail_bytes), mimetype=mime, resumable=False)
            youtube.thumbnails().set(videoId=video_id, media_body=media).execute(num_retries=3)
            print(f"  Thumbnail set: {channel_config.get('channel_name', '')}")
            return True
        except Exception as error:
            print(f'  Thumbnail failed: {error}. Video is already uploaded; retry will only set thumbnail.')
            return False

    def add_video_to_playlist(self, youtube, video_id: str, playlist_id: str) -> bool:
        """Add uploaded video to a YouTube playlist"""
        try:
            print(f"  📋 Adding to playlist...")

            request = youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id
                        }
                    }
                }
            )

            response = request.execute()
            print(f"  ✅ Added to playlist: {playlist_id}")
            return True

        except HttpError as e:
            error_content = e.content.decode('utf-8') if hasattr(e, 'content') else ''
            print(f"  ⚠️  Failed to add to playlist: {str(e)[:100]}")

            # Don't fail the entire upload if playlist addition fails
            return False

        except Exception as e:
            print(f"  ⚠️  Failed to add to playlist: {str(e)[:100]}")
            return False

    def calculate_schedule_time(self, sheet_tab_name: str) -> str:
        """Calculate next schedule time"""
        try:
            if not self.sheets_client:
                return datetime.now().strftime('%d-%b-%Y %I:%M %p')

            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
            worksheet = sheet.worksheet(sheet_tab_name)

            # Column I (col_values(9)) contains schedual_time
            schedule_col = worksheet.col_values(9)

            valid_dates = []
            for date_str in schedule_col[1:]:  # Skip header
                if date_str and date_str.strip():
                    try:
                        dt = datetime.strptime(date_str.strip(), '%d-%b-%Y %I:%M %p')
                        valid_dates.append(dt)
                    except:
                        continue

            if valid_dates:
                last_schedule = max(valid_dates)
            else:
                last_schedule = datetime.now()

            # Calculate gap
            gap_hours = random.uniform(
                float(self.schedule_gap_min_hours),
                float(self.schedule_gap_max_hours)
            )
            gap_minutes = random.randint(
                -int(self.schedule_gap_random_minutes),
                int(self.schedule_gap_random_minutes)
            )

            next_time = last_schedule + timedelta(
                hours=gap_hours,
                minutes=gap_minutes
            )

            if next_time < datetime.now():
                next_time = datetime.now() + timedelta(hours=gap_hours, minutes=gap_minutes)

            return next_time.strftime('%d-%b-%Y %I:%M %p')

        except Exception as e:
            print(f"  {Colors.RED}⚠️  Schedule calculation error: {e}{Colors.RESET}")
            return datetime.now().strftime('%d-%b-%Y %I:%M %p')

    def check_duplicate_in_sheet(self, sheet_tab_name: str, video_id: str) -> bool:
        """Check if video already exists in sheet (with caching to reduce API calls)"""
        try:
            if not self.sheets_client:
                return False

            # Check if we have a valid cache
            now = datetime.now()
            cache_entry = self.sheets_cache.get(sheet_tab_name)

            if cache_entry:
                cache_age = (now - cache_entry['timestamp']).total_seconds()
                if cache_age < self.cache_duration_seconds:
                    # Use cached data
                    return video_id in cache_entry['ids']

            # Cache miss or expired - fetch from API
            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
            worksheet = sheet.worksheet(sheet_tab_name)

            # Column A (col_values(1)) contains tiktok_video_id
            existing_ids = worksheet.col_values(1)[1:]  # Skip header

            # Update cache
            self.sheets_cache[sheet_tab_name] = {
                'ids': existing_ids,
                'timestamp': now
            }

            return video_id in existing_ids

        except Exception as e:
            error_str = str(e)
            # Check if it's a quota error
            if '429' in error_str or 'quota exceeded' in error_str.lower():
                print(f"  {Colors.RED}⚠️  Google Sheets API quota exceeded - waiting 60 seconds...{Colors.RESET}")
                time.sleep(60)
                # Try to use cache if available
                cache_entry = self.sheets_cache.get(sheet_tab_name)
                if cache_entry:
                    print(f"  📦 Using cached data from {(now - cache_entry['timestamp']).total_seconds():.0f}s ago")
                    return video_id in cache_entry['ids']

            print(f"  {Colors.RED}⚠️  Duplicate check failed: {e}{Colors.RESET}")
            return False

    def log_to_sheet(
        self,
        sheet_tab_name: str,
        video_info: Dict,
        youtube_data: Dict,
        scheduled_time: str,
        status: str
    ):
        """Log video to Google Sheet and color green"""
        try:
            if not self.sheets_client:
                print("  ⚠️  Sheets client not available{Colors.RESET}")
                return

            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
            worksheet = sheet.worksheet(sheet_tab_name)

            # Prepare row with correct column order
            # A: tiktok_video_id
            # B: tiktok_video_url
            # C: tiktok_video_title
            # D: tiktok_caption
            # E: tiktok_upload_time
            # F: yt_video_url
            # G: youtube_id
            # H: upload_time
            # I: schedual_time
            # J: status

            current_time = datetime.now().strftime('%d-%b-%Y %I:%M %p')

            row = [
                video_info.get('video_id', ''),              # A
                video_info.get('tiktok_url', ''),            # B
                youtube_data.get('formatted_title', ''),     # C
                youtube_data.get('formatted_description', ''),  # D (caption)
                video_info.get('tiktok_upload_time', ''),    # E
                youtube_data.get('youtube_url', ''),         # F
                youtube_data.get('youtube_id', ''),          # G
                current_time,                                # H
                scheduled_time,                              # I
                status                                       # J
            ]

            # Append row
            worksheet.append_row(row, value_input_option='USER_ENTERED')

            # Invalidate cache since we added a new row
            if sheet_tab_name in self.sheets_cache:
                del self.sheets_cache[sheet_tab_name]

            # Get row index
            all_rows = worksheet.get_all_values()
            row_index = len(all_rows)

            # Color the row light green
            worksheet.format(
                f'A{row_index}:J{row_index}',
                {
                    'backgroundColor': self.new_video_color
                }
            )

            print(f"  ✅ Logged to sheet (row {row_index})")

        except Exception as e:
            print(f"  {Colors.RED}❌ Sheet logging failed: {e}{Colors.RESET}")

    def verify_sheet_update(self, sheet_tab_name: str, video_id: str, youtube_url: str, youtube_id: str, scheduled_time: str, status: str) -> bool:
        """Verify that sheet was updated correctly with all required data

        Returns:
            bool: True if all columns are properly updated, False otherwise
        """
        try:
            if not self.sheets_client:
                print("  ⚠️  Cannot verify: Sheets client not available{Colors.RESET}")
                return False

            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
            worksheet = sheet.worksheet(sheet_tab_name)

            # Get all rows
            all_rows = worksheet.get_all_values()

            # Search for the video_id in column A (most recently added should be at bottom)
            for idx in range(len(all_rows) - 1, 0, -1):  # Search from bottom to top
                row = all_rows[idx]
                if len(row) > 0 and row[0] == video_id:
                    # Found the row, now verify all required columns
                    # F(5): yt_video_url, G(6): youtube_id, I(8): schedual_time, J(9): status

                    row_number = idx + 1
                    verification_issues = []

                    # Check yt_video_url (column F, index 5)
                    if len(row) <= 5 or not row[5] or row[5].strip() == '':
                        verification_issues.append("yt_video_url (column F) is empty")
                    elif youtube_url and row[5] != youtube_url:
                        verification_issues.append(f"yt_video_url mismatch: expected '{youtube_url}', got '{row[5]}'")

                    # Check youtube_id (column G, index 6)
                    if len(row) <= 6 or not row[6] or row[6].strip() == '':
                        verification_issues.append("youtube_id (column G) is empty")
                    elif youtube_id and row[6] != youtube_id:
                        verification_issues.append(f"youtube_id mismatch: expected '{youtube_id}', got '{row[6]}'")

                    # Check schedual_time (column I, index 8) - with flexible time format matching
                    if len(row) <= 8 or not row[8] or row[8].strip() == '':
                        verification_issues.append("schedual_time (column I) is empty")
                    elif scheduled_time:
                        # Normalize both times to handle format variations (09:59 vs 9:59)
                        normalized_expected = self.normalize_time_format(scheduled_time)
                        normalized_actual = self.normalize_time_format(row[8])
                        if normalized_expected != normalized_actual:
                            verification_issues.append(f"schedual_time mismatch: expected '{scheduled_time}', got '{row[8]}'")

                    # Check status (column J, index 9)
                    if len(row) <= 9 or not row[9] or row[9].strip() == '':
                        verification_issues.append("status (column J) is empty")
                    elif status and row[9].lower() != status.lower():
                        verification_issues.append(f"status mismatch: expected '{status}', got '{row[9]}'")

                    if verification_issues:
                        print(f"  {Colors.RED}⚠️  Sheet verification FAILED for row {row_number}:{Colors.RESET}")
                        for issue in verification_issues:
                            print(f"     - {issue}")
                        return False
                    else:
                        print(f"  ✅ Sheet verification PASSED (row {row_number}): All required columns populated")
                        return True

            print(f"  {Colors.RED}⚠️  Sheet verification FAILED: Video ID '{video_id}' not found in sheet{Colors.RESET}")
            return False

        except Exception as e:
            print(f"  {Colors.RED}❌ Sheet verification error: {e}{Colors.RESET}")
            return False

    def normalize_time_format(self, time_str: str) -> str:
        """Normalize a schedule-time string to a canonical datetime.

        Google Sheets may expand 'Aug' → 'August' and drop the leading zero on
        the hour ('01:35' → '1:35'), so a verbatim string comparison fails even
        though the times are identical. Both the expected and stored values are
        run through this helper and compared as normalized datetime strings.

        Args:
            time_str: Time string like '10-Aug-2026 01:35 AM'

        Returns:
            Canonical 'YYYY-MM-DD HH:MM' string, or the original string if
            nothing parses (so the caller still sees the mismatch).
        """
        s = time_str.strip()

        # Map full month names to 3-letter abbreviations ('August' → 'Aug')
        month_map = [
            ('january', 'Jan'), ('february', 'Feb'), ('march', 'Mar'),
            ('april', 'Apr'), ('may', 'May'), ('june', 'Jun'),
            ('july', 'Jul'), ('august', 'Aug'), ('september', 'Sep'),
            ('october', 'Oct'), ('november', 'Nov'), ('december', 'Dec'),
        ]
        for full, abbr in month_map:
            if full in s.lower():
                s = re.sub(rf'\b{full}\b', abbr, s, flags=re.IGNORECASE)
                break

        # Try the plausible layouts (abbreviated month, full month already
        # collapsed above); leading-zero on hour is ignored by %I.
        formats = [
            '%d-%b-%Y %I:%M %p',
            '%d-%b-%Y %H:%M',
            '%Y-%m-%d %H:%M:%S',
            '%m/%d/%Y %I:%M %p',
            '%m/%d/%Y %H:%M:%S',
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime('%Y-%m-%d %H:%M')
            except ValueError:
                continue

        # Fallback: if it already parses with a leading-zero hour variant.
        try:
            dt = datetime.strptime(s, '%d-%b-%Y %#I:%M %p')
            return dt.strftime('%Y-%m-%d %H:%M')
        except ValueError:
            pass

        return time_str

    def verify_sheet_row_update(self, sheet_tab_name: str, row_index: int, youtube_url: str, youtube_id: str, scheduled_time: str, status: str) -> bool:
        """Verify that a specific sheet row was updated correctly with all required data

        Args:
            sheet_tab_name: Name of the sheet tab
            row_index: Row number (1-indexed) to verify
            youtube_url: Expected YouTube URL
            youtube_id: Expected YouTube ID
            scheduled_time: Expected schedule time
            status: Expected status

        Returns:
            bool: True if all columns are properly updated, False otherwise
        """
        try:
            if not self.sheets_client:
                print("  ⚠️  Cannot verify: Sheets client not available{Colors.RESET}")
                return False

            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
            worksheet = sheet.worksheet(sheet_tab_name)

            # Get the specific row (row_index is 1-based, list is 0-based)
            all_rows = worksheet.get_all_values()
            if row_index < 1 or row_index > len(all_rows):
                print(f"  {Colors.RED}⚠️  Sheet verification FAILED: Row {row_index} out of range{Colors.RESET}")
                return False

            row = all_rows[row_index - 1]
            verification_issues = []

            # Check yt_video_url (column F, index 5)
            if len(row) <= 5 or not row[5] or row[5].strip() == '':
                verification_issues.append("yt_video_url (column F) is empty")
            elif youtube_url and row[5] != youtube_url:
                verification_issues.append(f"yt_video_url mismatch: expected '{youtube_url}', got '{row[5]}'")

            # Check youtube_id (column G, index 6)
            if len(row) <= 6 or not row[6] or row[6].strip() == '':
                verification_issues.append("youtube_id (column G) is empty")
            elif youtube_id and row[6] != youtube_id:
                verification_issues.append(f"youtube_id mismatch: expected '{youtube_id}', got '{row[6]}'")

            # Check schedual_time (column I, index 8) - with flexible time format matching
            if len(row) <= 8 or not row[8] or row[8].strip() == '':
                verification_issues.append("schedual_time (column I) is empty")
            elif scheduled_time:
                # Normalize both times to handle format variations (09:59 vs 9:59)
                normalized_expected = self.normalize_time_format(scheduled_time)
                normalized_actual = self.normalize_time_format(row[8])
                if normalized_expected != normalized_actual:
                    verification_issues.append(f"schedual_time mismatch: expected '{scheduled_time}', got '{row[8]}'")

            # Check status (column J, index 9)
            if len(row) <= 9 or not row[9] or row[9].strip() == '':
                verification_issues.append("status (column J) is empty")
            elif status and row[9].lower() != status.lower():
                verification_issues.append(f"status mismatch: expected '{status}', got '{row[9]}'")

            if verification_issues:
                print(f"  {Colors.RED}⚠️  Sheet verification FAILED for row {row_index}:{Colors.RESET}")
                for issue in verification_issues:
                    print(f"     - {issue}")
                return False
            else:
                print(f"  ✅ Sheet verification PASSED (row {row_index}): All required columns populated")
                return True

        except Exception as e:
            print(f"  {Colors.RED}❌ Sheet verification error: {e}{Colors.RESET}")
            return False

    def find_old_videos_in_sheet(self, sheet_tab_name: str) -> List[Tuple[int, Dict]]:
        """Find OLD videos in sheet (status column empty)"""
        try:
            if not self.sheets_client:
                return []

            # IMPORTANT: Always fetch fresh spreadsheet to avoid gspread caching issues
            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)

            # Verify we're getting the correct worksheet
            try:
                worksheet = sheet.worksheet(sheet_tab_name)
                actual_title = worksheet.title
                if actual_title != sheet_tab_name:
                    print(f"  {Colors.RED}⚠️  WARNING: Worksheet mismatch! Expected '{sheet_tab_name}', got '{actual_title}'{Colors.RESET}")
                    # Try again with explicit title match
                    worksheet = sheet.worksheet(sheet_tab_name)
            except Exception as ws_error:
                print(f"  {Colors.RED}❌ Failed to get worksheet '{sheet_tab_name}': {ws_error}{Colors.RESET}")
                return []

            all_rows = worksheet.get_all_values()

            if not all_rows:
                print(f"  {Colors.YELLOW}⚠️  Sheet is empty{Colors.RESET}")
                return []

            if len(all_rows) < 2:
                print(f"  {Colors.YELLOW}⚠️  No data rows (only headers){Colors.RESET}")
                return []

            print(f"  {Colors.GREEN}✓ Found {len(all_rows) - 1} rows in sheet{Colors.RESET}")

            old_videos = []

            for idx, row in enumerate(all_rows[1:], start=2):
                if len(row) < 10:
                    print(f"  {Colors.YELLOW}⚠️  Row {idx}: Skipped (only {len(row)} columns, need at least 10){Colors.RESET}")
                    continue

                # Column mapping (0-indexed):
                # A(0): tiktok_video_id
                # B(1): tiktok_video_url
                # C(2): tiktok_video_title
                # D(3): tiktok_caption
                # E(4): tiktok_upload_time
                # F(5): yt_video_url
                # G(6): youtube_id
                # H(7): upload_time
                # I(8): schedual_time
                # J(9): status
                # K(10): error

                status = row[9].strip() if len(row) > 9 else ''

                if not status:
                    video_info = {
                        'video_id': row[0] if len(row) > 0 else '',
                        'tiktok_url': row[1] if len(row) > 1 else '',
                        'title': row[2] if len(row) > 2 else '',
                        'caption': row[3] if len(row) > 3 else '',
                        'tiktok_upload_time': row[4] if len(row) > 4 else '',
                        'youtube_url': row[5] if len(row) > 5 else '',
                        'youtube_id': row[6] if len(row) > 6 else '',
                        'upload_time': row[7] if len(row) > 7 else '',
                        'scheduled_time': row[8] if len(row) > 8 else ''
                    }

                    # Only require tiktok_url (column B) to be present
                    if video_info['tiktok_url'].strip():
                        old_videos.append((idx, video_info))
                        # Don't print each row - will show summary count instead

            if old_videos:
                print(f"  {Colors.GREEN}✓ Found {len(old_videos)} OLD videos to process{Colors.RESET}")
            else:
                print(f"  {Colors.YELLOW}⚠️  No OLD videos found (all rows either have status or missing tiktok_url){Colors.RESET}")

            return old_videos

        except Exception as e:
            import traceback
            print(f"  {Colors.RED}❌ Error finding OLD videos: {e}{Colors.RESET}")
            print(f"  {Colors.RED}Traceback: {traceback.format_exc()}{Colors.RESET}")
            return []

    def find_local_videos_in_sheet(self, sheet_tab_name: str, source_folder: str) -> List[Tuple[int, Dict, str]]:
        """Find local folder videos in sheet (status column empty) and verify video files exist"""
        try:
            if not self.sheets_client:
                return []

            from pathlib import Path

            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
            worksheet = sheet.worksheet(sheet_tab_name)

            all_rows = worksheet.get_all_values()

            local_videos = []
            source_path = Path(source_folder)

            if not source_path.exists():
                print(f"  {Colors.RED}⚠️  Source folder not found: {source_folder}{Colors.RESET}")
                return []

            for idx, row in enumerate(all_rows[1:], start=2):
                if len(row) < 10:
                    continue

                # Column mapping (0-indexed):
                # A(0): video_id (numeric like 1, 2, 3)
                # B(1): (empty or unused for local)
                # C(2): title
                # D(3): caption/description
                # E(4): (optional)
                # F(5): yt_video_url
                # G(6): youtube_id
                # H(7): upload_time
                # I(8): schedual_time
                # J(9): status

                status = row[9].strip() if len(row) > 9 else ''

                if not status:
                    video_id = row[0].strip() if len(row) > 0 else ''

                    if not video_id:
                        continue

                    # Look for video file with this ID
                    video_file = None
                    for ext in ['.mp4', '.MP4', '.mov', '.MOV', '.avi', '.AVI']:
                        potential_file = source_path / f"{video_id}{ext}"
                        if potential_file.exists():
                            video_file = str(potential_file)
                            break

                    if not video_file:
                        continue

                    video_info = {
                        'video_id': video_id,
                        'title': row[2] if len(row) > 2 else f'Video {video_id}',
                        'caption': row[3] if len(row) > 3 else '',
                        'tiktok_upload_time': '',
                        'youtube_url': row[5] if len(row) > 5 else '',
                        'youtube_id': row[6] if len(row) > 6 else '',
                        'upload_time': row[7] if len(row) > 7 else '',
                        'scheduled_time': row[8] if len(row) > 8 else '',
                        'tiktok_url': ''  # Not applicable for local videos
                    }

                    local_videos.append((idx, video_info, video_file))

            return local_videos

        except Exception as e:
            print(f"  {Colors.RED}❌ Error finding local videos: {e}{Colors.RESET}")
            return []

    def find_local_videos_sheet_free(self, source_folder: str, uploaded_folder: str) -> List[str]:
        """Find video files directly from folder (no Google Sheet needed)

        Returns list of video file paths that haven't been uploaded yet
        """
        try:
            from pathlib import Path
            import random

            source_path = Path(source_folder)
            uploaded_path = Path(uploaded_folder)

            if not source_path.exists():
                print(f"  {Colors.RED}⚠️  Source folder not found: {source_folder}{Colors.RESET}")
                return []

            # Create uploaded folder if it doesn't exist
            if not uploaded_path.exists():
                uploaded_path.mkdir(parents=True, exist_ok=True)
                print(f"  ✅ Created uploaded folder: {uploaded_folder}")

            # Find all video files in source folder
            video_extensions = ['.mp4', '.MP4', '.mov', '.MOV', '.avi', '.AVI', '.mkv', '.MKV', '.flv', '.FLV']
            video_files = []

            for ext in video_extensions:
                video_files.extend(list(source_path.glob(f'*{ext}')))

            if not video_files:
                print(f"  ℹ️  No video files found in source folder")
                return []

            # Shuffle for random order
            random.shuffle(video_files)

            # Convert to string paths
            video_paths = [str(vf) for vf in video_files]

            print(f"  ✅ Found {len(video_paths)} video files in source folder")

            return video_paths

        except Exception as e:
            print(f"  {Colors.RED}❌ Error finding local videos: {e}{Colors.RESET}")
            return []

    def process_local_video_sheet_free(
        self,
        channel_config: Dict,
        video_file_path: str,
        uploaded_folder: str
    ) -> bool:
        """Process a local folder video WITHOUT Google Sheet

        - Uploads video to YouTube
        - Moves video to uploaded folder on success
        - Uses filename as title
        """
        try:
            from pathlib import Path
            import shutil

            video_path = Path(video_file_path)

            if not video_path.exists():
                print(f"  {Colors.RED}❌ Video file not found: {video_file_path}{Colors.RESET}")
                return False

            # Extract filename without extension for title
            video_filename = video_path.stem

            print(f"\n  📁 LOCAL Video (Sheet-Free): {video_filename}")
            print(f"  📂 File: {video_file_path}")

            # Read video file
            with open(video_path, 'rb') as f:
                video_data = f.read()

            size_mb = len(video_data) / (1024 * 1024)
            print(f"  📊 Size: {size_mb:.2f} MB")

            # Create video_info from filename
            video_info = {
                'video_id': video_filename,
                'title': video_filename.replace('_', ' ').replace('-', ' '),  # Clean up filename
                'caption': '',  # Can be customized via config later
                'tiktok_upload_time': '',
                'youtube_url': '',
                'youtube_id': '',
                'upload_time': '',
                'scheduled_time': '',
                'tiktok_url': ''
            }

            # Schedule a short time in the future — YouTube rejects a
            # publishAt in the past, and the upload itself takes time.
            scheduled_time = (datetime.now() + timedelta(minutes=15)).strftime('%d-%b-%Y %I:%M %p')

            # Upload
            youtube_data = self.upload_to_youtube(channel_config, video_data, video_info, scheduled_time)
            if not youtube_data:
                # Check if failure was due to quota exceeded
                channel_id = channel_config.get('channel_id', channel_config.get('channel_name'))
                if self.is_channel_in_quota_cooldown(channel_id):
                    print(f"  ⏸️  Upload blocked - quota exceeded")
                    return False
                else:
                    print(f"  {Colors.RED}❌ Upload failed{Colors.RESET}")
                    return False

            # Show completion info
            upload_completed = datetime.now().strftime('%d-%b-%Y %I:%M %p')
            print(f"  🕐 Upload completed: {upload_completed}")
            print(f"  📅 Published: {Colors.GREEN}{scheduled_time}{Colors.RESET}")
            print(f"  🔗 YouTube URL: {Colors.GREEN}{youtube_data['youtube_url']}{Colors.RESET}")

            # Move video to uploaded folder
            uploaded_path = Path(uploaded_folder)
            if not uploaded_path.exists():
                uploaded_path.mkdir(parents=True, exist_ok=True)

            destination = uploaded_path / video_path.name

            # If file already exists in uploaded folder, add timestamp
            if destination.exists():
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                destination = uploaded_path / f"{video_path.stem}_{timestamp}{video_path.suffix}"

            shutil.move(str(video_path), str(destination))
            print(f"  📦 Moved to uploaded folder: {destination.name}")

            self._mark_uploaded(video_filename)
            print(f"  ✅ LOCAL video upload complete (sheet-free)!")
            return True

        except Exception as e:
            print(f"  {Colors.RED}❌ Error processing sheet-free local video: {e}{Colors.RESET}")
            import traceback
            print(traceback.format_exc())
            return False

    def process_old_video(
        self,
        channel_config: Dict,
        sheet_tab_name: str,
        row_index: int,
        video_info: Dict
    ) -> bool:
        """Process an OLD video from sheet"""
        try:
            print(f"\n  📦 OLD Video (row {row_index}): {video_info['title'][:50] if video_info['title'] else video_info['video_id']}")

            # Extract video info
            source_url = video_info['tiktok_url']  # Can be TikTok or Facebook
            video_id = video_info['video_id']

            # Detect platform
            platform = self.detect_platform_from_url(source_url)

            if platform == 'tiktok':
                print(f"  🔗 TikTok: {source_url}")
                print(f"  🆔 ID: {video_id}")
                result = self.download_from_tiktok_url(source_url, video_id)
            elif platform == 'facebook':
                print(f"  🔗 Facebook: {source_url}")
                print(f"  🆔 ID: {video_id}")
                result = self.download_from_facebook_url(source_url, video_id)
            elif platform == 'instagram':
                print(f"  🔗 Instagram: {source_url}")
                print(f"  🆔 ID: {video_id}")
                result = self.download_from_instagram_url(source_url, video_id)
            else:
                print(f"  {Colors.RED}❌ Unsupported URL platform: {source_url}{Colors.RESET}")
                self.update_sheet_status(sheet_tab_name, row_index, 'failed')
                return False

            # Download video
            if not result:
                print(f"  {Colors.RED}❌ Download failed - marking as 'failed'{Colors.RESET}")
                self.update_sheet_status(sheet_tab_name, row_index, 'failed')
                return False

            video_data, metadata = result

            # Update tiktok_upload_time if we got it from API
            if 'tiktok_upload_time' in metadata and metadata['tiktok_upload_time']:
                video_info['tiktok_upload_time'] = metadata['tiktok_upload_time']
                platform_names = {'tiktok': 'TikTok', 'facebook': 'Facebook', 'instagram': 'Instagram'}
                platform_name = platform_names.get(platform, platform.title())
                print(f"  📅 {platform_name} uploaded: {metadata['tiktok_upload_time']}")

            # Get or calculate schedule time
            if video_info['scheduled_time']:
                scheduled_time = video_info['scheduled_time']
            else:
                scheduled_time = self.calculate_schedule_time(sheet_tab_name)

            # Upload
            youtube_data = self.upload_to_youtube(channel_config, video_data, video_info, scheduled_time)
            if not youtube_data:
                # Check if failure was due to quota exceeded
                channel_id = channel_config.get('channel_id', channel_config.get('channel_name'))
                if self.is_channel_in_quota_cooldown(channel_id):
                    print(f"  ⏸️  Upload blocked - quota exceeded (leaving status empty for retry)")

                    # Add quota notice to error column K at this row (only if not already present)
                    if not self.check_quota_notice_in_sheet(sheet_tab_name):
                        remaining_hours = self.get_quota_cooldown_remaining(channel_id)
                        cooldown_time = datetime.now() + timedelta(hours=remaining_hours)
                        cooldown_until = cooldown_time.strftime('%d-%b-%Y %I:%M %p')
                        self.add_quota_notice_to_sheet(sheet_tab_name, row_index, cooldown_until)
                    else:
                        print(f"  📝 Quota notice already exists in sheet - not updating")

                    # Don't mark as failed - leave status empty so it can be retried after cooldown
                    return False
                else:
                    print(f"  {Colors.RED}❌ Upload failed - marking as 'failed'{Colors.RESET}")
                    self.update_sheet_status(sheet_tab_name, row_index, 'failed')
                    return False

            # Show completion and schedule info
            upload_completed = datetime.now().strftime('%d-%b-%Y %I:%M %p')
            print(f"  🕐 Upload completed: {upload_completed}")
            print(f"  📅 Scheduled to publish: {Colors.GREEN}{scheduled_time}{Colors.RESET}")

            # Mark as uploaded immediately: the YouTube upload already happened
            # and cannot be undone, so a later sheet-verify failure must NOT
            # cause a duplicate re-upload on the next run.
            self._mark_uploaded(video_id)

            # Update sheet (including tiktok_upload_time)
            self.update_old_video_in_sheet(
                sheet_tab_name,
                row_index,
                youtube_data,
                scheduled_time,
                'done',
                video_info.get('tiktok_upload_time', '')
            )

            # STRICT VERIFICATION: Ensure sheet row is properly updated before proceeding
            print(f"  🔍 Verifying sheet update (row {row_index})...")
            verification_passed = self.verify_sheet_row_update(
                sheet_tab_name,
                row_index,
                youtube_data.get('youtube_url', ''),
                youtube_data.get('youtube_id', ''),
                scheduled_time,
                'done'
            )

            if not verification_passed:
                print(f"  {Colors.RED}❌ CRITICAL: Sheet verification failed for row {row_index}!{Colors.RESET}")
                print(f"  {Colors.RED}⚠️  Please check the Google Sheet manually and fix the issue.{Colors.RESET}")
                return False

            print(f"  ✅ OLD video upload & verification complete!")
            return True

        except Exception as e:
            print(f"  {Colors.RED}❌ Error processing OLD video: {e}{Colors.RESET}")
            self.update_sheet_status(sheet_tab_name, row_index, 'failed')
            return False

    def process_local_video(
        self,
        channel_config: Dict,
        sheet_tab_name: str,
        row_index: int,
        video_info: Dict,
        video_file_path: str
    ) -> bool:
        """Process a local folder video"""
        try:
            print(f"\n  📁 LOCAL Video (row {row_index}): {video_info['title'][:50]}")
            print(f"  🆔 ID: {video_info['video_id']}")
            print(f"  📂 File: {video_file_path}")

            # Read video file
            from pathlib import Path
            video_path = Path(video_file_path)

            if not video_path.exists():
                print(f"  {Colors.RED}❌ Video file not found: {video_file_path}{Colors.RESET}")
                self.update_sheet_status(sheet_tab_name, row_index, 'failed')
                return False

            with open(video_path, 'rb') as f:
                video_data = f.read()

            size_mb = len(video_data) / (1024 * 1024)
            print(f"  📊 Size: {size_mb:.2f} MB")

            # Get or calculate schedule time
            if video_info['scheduled_time']:
                scheduled_time = video_info['scheduled_time']
            else:
                scheduled_time = self.calculate_schedule_time(sheet_tab_name)

            # Upload
            youtube_data = self.upload_to_youtube(channel_config, video_data, video_info, scheduled_time)
            if not youtube_data:
                # Check if failure was due to quota exceeded
                channel_id = channel_config.get('channel_id', channel_config.get('channel_name'))
                if self.is_channel_in_quota_cooldown(channel_id):
                    print(f"  ⏸️  Upload blocked - quota exceeded (leaving status empty for retry)")

                    # Add quota notice to error column K at this row (only if not already present)
                    if not self.check_quota_notice_in_sheet(sheet_tab_name):
                        remaining_hours = self.get_quota_cooldown_remaining(channel_id)
                        cooldown_time = datetime.now() + timedelta(hours=remaining_hours)
                        cooldown_until = cooldown_time.strftime('%d-%b-%Y %I:%M %p')
                        self.add_quota_notice_to_sheet(sheet_tab_name, row_index, cooldown_until)
                    else:
                        print(f"  📝 Quota notice already exists in sheet - not updating")

                    # Don't mark as failed - leave status empty so it can be retried after cooldown
                    return False
                else:
                    print(f"  {Colors.RED}❌ Upload failed - marking as 'failed'{Colors.RESET}")
                    self.update_sheet_status(sheet_tab_name, row_index, 'failed')
                    return False

            # Show completion and schedule info
            upload_completed = datetime.now().strftime('%d-%b-%Y %I:%M %p')
            print(f"  🕐 Upload completed: {upload_completed}")
            print(f"  📅 Scheduled to publish: {Colors.GREEN}{scheduled_time}{Colors.RESET}")

            self._mark_uploaded(video_info['video_id'])

            # Update sheet
            self.update_old_video_in_sheet(
                sheet_tab_name,
                row_index,
                youtube_data,
                scheduled_time,
                'done'
            )

            # STRICT VERIFICATION: Ensure sheet row is properly updated before proceeding
            print(f"  🔍 Verifying sheet update (row {row_index})...")
            verification_passed = self.verify_sheet_row_update(
                sheet_tab_name,
                row_index,
                youtube_data.get('youtube_url', ''),
                youtube_data.get('youtube_id', ''),
                scheduled_time,
                'done'
            )

            if not verification_passed:
                print(f"  {Colors.RED}❌ CRITICAL: Sheet verification failed for row {row_index}!{Colors.RESET}")
                print(f"  {Colors.RED}⚠️  Please check the Google Sheet manually and fix the issue.{Colors.RESET}")
                return False

            # Move video to uploaded folder (only after verification passes)
            uploaded_folder = channel_config.get('video_uploaded_folder', '')
            if uploaded_folder:
                import shutil
                uploaded_path = Path(uploaded_folder)
                uploaded_path.mkdir(parents=True, exist_ok=True)

                dest_file = uploaded_path / video_path.name
                shutil.move(str(video_path), str(dest_file))
                print(f"  ✅ Moved to: {dest_file}")

            print(f"  ✅ LOCAL video upload & verification complete!")
            return True

        except Exception as e:
            print(f"  {Colors.RED}❌ Error processing LOCAL video: {e}{Colors.RESET}")
            self.update_sheet_status(sheet_tab_name, row_index, 'failed')
            return False

    def detect_platform_from_url(self, url: str) -> str:
        """Detect which platform the URL is from

        Returns:
            'tiktok', 'facebook', 'instagram', or 'unknown'
        """
        url_lower = url.lower()
        # shorts.com is TikTok's own short-link domain (www.shorts.com/@user/video/{id})
        if 'tiktok.com' in url_lower or 'vm.tiktok.com' in url_lower or 'shorts.com' in url_lower:
            return 'tiktok'
        elif 'facebook.com' in url_lower or 'fb.watch' in url_lower or 'fb.com' in url_lower:
            return 'facebook'
        elif 'instagram.com' in url_lower or 'instagr.am' in url_lower:
            return 'instagram'
        return 'unknown'

    def download_from_facebook_url(self, facebook_url: str, video_id: str) -> Optional[tuple]:
        """Download video from Facebook Reels URL

        Returns:
            tuple: (video_data: bytes, metadata: dict) or None if failed
        """
        print(f"  📥 Downloading video from Facebook Reels...")

        # Skip Playwright due to DNS issues - use direct methods instead
        # Commenting out for now as it has network configuration conflicts

        # FALLBACK METHOD: yt-dlp
        print(f"  🔄 Trying yt-dlp (fallback method)...")
        try:
            import subprocess
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as temp_dir:
                output_template = str(Path(temp_dir) / f'facebook_{video_id}.%(ext)s')

                # Build command with cookie support if available
                cmd = [
                    'yt-dlp',
                    '--no-playlist',
                    '--output', output_template,
                    '--user-agent', self.get_random_user_agent(),
                ]

                # Check if cookies.txt exists for Facebook authentication
                cookies_file = Path('facebook_cookies.txt')
                if cookies_file.exists():
                    cmd.extend(['--cookies', str(cookies_file)])

                cmd.append(facebook_url)

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode == 0:
                    # Find the downloaded file
                    temp_path = Path(temp_dir)
                    video_files = list(temp_path.glob(f'facebook_{video_id}.*'))

                    if video_files:
                        video_file = video_files[0]
                        with open(video_file, 'rb') as f:
                            video_data = f.read()

                        if len(video_data) > 100000:
                            size_mb = len(video_data) / (1024 * 1024)
                            print(f"  {Colors.GREEN}✅ yt-dlp: {size_mb:.2f} MB{Colors.RESET}")
                            return (video_data, {})
                        else:
                            print(f"  {Colors.YELLOW}⚠️  yt-dlp: File too small, trying fallback APIs...{Colors.RESET}")
                    else:
                        print(f"  {Colors.YELLOW}⚠️  yt-dlp: No video file found, trying fallback APIs...{Colors.RESET}")
                else:
                    # Show actual error from yt-dlp (check both stderr and stdout)
                    error_msg = result.stderr.strip() if result.stderr else ""
                    if not error_msg:
                        error_msg = result.stdout.strip() if result.stdout else ""
                    if not error_msg:
                        error_msg = f"Exit code {result.returncode}"

                    # Show cookies tip if not using cookies
                    if not cookies_file.exists():
                        print(f"  {Colors.YELLOW}⚠️  yt-dlp failed: Facebook requires authentication{Colors.RESET}")
                        print(f"  {Colors.YELLOW}   See FACEBOOK_SETUP_GUIDE.md to setup cookies{Colors.RESET}")
                    else:
                        print(f"  {Colors.YELLOW}⚠️  yt-dlp failed: {error_msg[:150]}{Colors.RESET}")
                    print(f"  {Colors.YELLOW}   Trying fallback APIs...{Colors.RESET}")
        except Exception as e:
            print(f"  {Colors.YELLOW}⚠️  yt-dlp exception: {str(e)[:100]}{Colors.RESET}")
            print(f"  {Colors.YELLOW}   Trying fallback APIs...{Colors.RESET}")

        # FALLBACK METHODS: Web-based download APIs
        print(f"  🔄 Trying web-based download APIs as fallback...")

        # Try direct Facebook extraction with multiple approaches
        try:
            print(f"  🔄 Trying direct Facebook video extraction...")
            import re
            import json

            # Try both desktop and mobile URLs
            urls_to_try = [
                facebook_url,
                facebook_url.replace('www.facebook.com', 'm.facebook.com'),  # Mobile version
                f"https://m.facebook.com/reel/{video_id}"  # Direct mobile reel
            ]

            for attempt_url in urls_to_try:
                try:
                    # Use mobile user agent for better success
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate',
                        'Referer': 'https://www.facebook.com/',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1'
                    }

                    response = requests.get(attempt_url, headers=headers, timeout=30, allow_redirects=True)

                    if response.status_code == 200:
                        html = response.text

                        # Try to extract video URL from HTML using different patterns
                        video_patterns = [
                            r'"playable_url":"([^"]+)"',
                            r'"browser_native_hd_url":"([^"]+)"',
                            r'"browser_native_sd_url":"([^"]+)"',
                            r'"playable_url_quality_hd":"([^"]+)"',
                            r'sd_src":"([^"]+)"',
                            r'hd_src":"([^"]+)"',
                            r'playable_url_quality_hd":"([^"]+)"',
                            r'"src":"(https://[^"]*video[^"]*\.mp4[^"]*)"',
                            r'src="(https://[^"]*video[^"]*\.mp4[^"]*)"',
                        ]

                        for pattern in video_patterns:
                            matches = re.findall(pattern, html)
                            if matches:
                                video_url = matches[0].replace('\\/', '/').replace('\\u0025', '%').replace('&amp;', '&')

                                print(f"  📥 Downloading video file from direct source...")
                                video_response = requests.get(
                                    video_url,
                                    headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15'},
                                    timeout=self.download_timeout,
                                    stream=True
                                )

                                if video_response.status_code == 200:
                                    from io import BytesIO
                                    content = BytesIO()
                                    for chunk in video_response.iter_content(chunk_size=8192):
                                        if chunk:
                                            content.write(chunk)

                                    video_data = content.getvalue()
                                    if len(video_data) > 100000:
                                        size_mb = len(video_data) / (1024 * 1024)
                                        print(f"  {Colors.GREEN}✅ Direct extraction: {size_mb:.2f} MB{Colors.RESET}")
                                        return (video_data, {})
                except:
                    continue  # Try next URL

        except Exception as e:
            print(f"  {Colors.YELLOW}⚠️  Direct extraction failed: {str(e)[:100]}{Colors.RESET}")

        # Try third-party APIs (these likely won't work without cookies, but try anyway)
        # Skip most APIs to save time since they're failing with DNS errors
        print(f"  {Colors.YELLOW}⚠️  Third-party APIs are unreliable for Facebook{Colors.RESET}")
        print(f"  {Colors.YELLOW}   Skipping to avoid timeouts...{Colors.RESET}")

        # Only keep this as a reference - not actually trying them anymore
        # to save time since they all fail with DNS/timeout errors
        apis = []

        for api in apis:
            try:
                print(f"  🔄 Trying {api['name']}...")

                headers = {
                    'User-Agent': self.get_random_user_agent(),
                    'Accept': 'application/json, */*',
                    'Referer': facebook_url
                }

                # Support both GET and POST methods
                if api.get('method', 'get') == 'post':
                    response = requests.post(
                        api['url'],
                        headers=headers,
                        data=api.get('data', {}),
                        timeout=30
                    )
                else:
                    response = requests.get(
                        api['url'],
                        headers=headers,
                        timeout=30
                    )

                if response.status_code == 200:
                    video_url = None
                    metadata = {}

                    # Try JSON response first
                    try:
                        data = response.json()

                        # Try different response structures (most common formats)
                        if 'sd' in data:
                            video_url = data['sd']
                        elif 'hd' in data:
                            video_url = data['hd']
                        elif 'url' in data:
                            video_url = data['url']
                        elif 'download_url' in data:
                            video_url = data['download_url']
                        elif 'video_url' in data:
                            video_url = data['video_url']
                        elif 'download' in data:
                            video_url = data['download']
                        elif 'link' in data:
                            video_url = data['link']
                        elif 'data' in data and isinstance(data['data'], dict):
                            if 'url' in data['data']:
                                video_url = data['data']['url']
                            elif 'download' in data['data']:
                                video_url = data['data']['download']
                            elif 'sd' in data['data']:
                                video_url = data['data']['sd']
                            elif 'hd' in data['data']:
                                video_url = data['data']['hd']
                        elif 'links' in data and isinstance(data['links'], list) and len(data['links']) > 0:
                            # Some APIs return array of quality options
                            video_url = data['links'][0].get('url') or data['links'][0].get('link')
                        elif 'video' in data and isinstance(data['video'], list) and len(data['video']) > 0:
                            video_url = data['video'][0].get('url') or data['video'][0].get('link')
                    except:
                        # If JSON fails, try regex on HTML
                        try:
                            html = response.text
                            # Look for video URLs in HTML
                            import re
                            patterns = [
                                r'"(https?://[^"]+\.mp4[^"]*)"',
                                r"'(https?://[^']+\.mp4[^']*)'",
                                r'href="(https?://[^"]+/download[^"]*)"',
                                r'data-url="([^"]+)"'
                            ]
                            for pattern in patterns:
                                matches = re.findall(pattern, html)
                                if matches:
                                    video_url = matches[0]
                                    break
                        except:
                            pass

                    if video_url:
                        try:
                            print(f"  📥 Downloading video file...")
                            video_response = requests.get(
                                video_url,
                                headers={'User-Agent': self.get_random_user_agent()},
                                timeout=self.download_timeout,
                                stream=True
                            )

                            if video_response.status_code == 200:
                                from io import BytesIO
                                content = BytesIO()
                                for chunk in video_response.iter_content(chunk_size=8192):
                                    if chunk:
                                        content.write(chunk)

                                video_data = content.getvalue()

                                if len(video_data) > 100000:  # At least 100KB
                                    size_mb = len(video_data) / (1024 * 1024)
                                    print(f"  {Colors.GREEN}✅ {api['name']}: {size_mb:.2f} MB{Colors.RESET}")
                                    return (video_data, metadata)
                                else:
                                    print(f"  {Colors.RED}⚠️  {api['name']}: File too small ({len(video_data)} bytes){Colors.RESET}")
                        except Exception as download_error:
                            print(f"  {Colors.RED}⚠️  {api['name']}: Download failed - {download_error}{Colors.RESET}")

            except Exception as e:
                print(f"  {Colors.RED}❌ {api['name']} error: {e}{Colors.RESET}")

            time.sleep(1)

        # All methods failed
        print(f"  {Colors.RED}❌ All Facebook download methods failed{Colors.RESET}")
        print(f"")
        print(f"  {Colors.YELLOW}{'='*60}{Colors.RESET}")
        print(f"  {Colors.YELLOW}💡 SOLUTION: Facebook Reels Require Authentication{Colors.RESET}")
        print(f"  {Colors.YELLOW}{'='*60}{Colors.RESET}")
        print(f"  {Colors.YELLOW}Facebook has restricted video downloads. To fix this:{Colors.RESET}")
        print(f"")

        # Check if facebook_cookies.txt exists and is valid
        cookies_file = Path('facebook_cookies.txt')
        if not cookies_file.exists():
            print(f"  {Colors.YELLOW}1. Install browser extension 'Get cookies.txt LOCALLY'{Colors.RESET}")
            print(f"  {Colors.YELLOW}2. Login to Facebook in your browser{Colors.RESET}")
            print(f"  {Colors.YELLOW}3. Export cookies and save as 'facebook_cookies.txt'{Colors.RESET}")
            print(f"  {Colors.YELLOW}4. Put file in: {Path.cwd()}{Colors.RESET}")
            print(f"")
            print(f"  {Colors.YELLOW}📖 Full guide: FACEBOOK_SETUP_GUIDE.md{Colors.RESET}")
        else:
            # Check if cookies file actually contains Facebook cookies
            try:
                with open(cookies_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if 'facebook.com' not in content and '.facebook.com' not in content:
                        print(f"  {Colors.RED}❌ ERROR: Cookies file contains NO Facebook cookies!{Colors.RESET}")
                        print(f"  {Colors.YELLOW}   Your file has cookies from other sites but NOT Facebook.{Colors.RESET}")
                        print(f"")
                        print(f"  {Colors.YELLOW}⚠️  IMPORTANT: You must be ON facebook.com when exporting!{Colors.RESET}")
                        print(f"  {Colors.YELLOW}   1. Go to https://www.facebook.com in your browser{Colors.RESET}")
                        print(f"  {Colors.YELLOW}   2. Login if needed{Colors.RESET}")
                        print(f"  {Colors.YELLOW}   3. THEN click the extension and export cookies{Colors.RESET}")
                        print(f"  {Colors.YELLOW}   4. Make sure the extension shows 'facebook.com' cookies{Colors.RESET}")
                    else:
                        print(f"  {Colors.YELLOW}❗ Cookies file exists but yt-dlp failed{Colors.RESET}")
                        print(f"  {Colors.YELLOW}   Cookies may be expired - try re-exporting from Facebook{Colors.RESET}")
            except Exception as e:
                print(f"  {Colors.YELLOW}❗ Could not read cookies file: {e}{Colors.RESET}")

        print(f"  {Colors.YELLOW}{'='*60}{Colors.RESET}")
        print(f"")

        return None

    def download_from_instagram_url(self, instagram_url: str, video_id: str) -> Optional[tuple]:
        """Download video from Instagram Reels URL

        Returns:
            tuple: (video_data: bytes, metadata: dict) or None if failed
        """
        print(f"  📥 Downloading video from Instagram Reels...")

        # Instagram download APIs
        apis = [
            {
                'name': 'InstaDownloader',
                'url': f'https://v3.saveig.app/api/ajaxSearch',
                'method': 'post',
                'data': {'q': instagram_url, 'lang': 'en'}
            },
            {
                'name': 'SnapInsta',
                'url': f'https://snapinsta.app/api/ajaxSearch',
                'method': 'post',
                'data': {'q': instagram_url, 'lang': 'en'}
            }
        ]

        for api in apis:
            try:
                print(f"  🔄 Trying {api['name']}...")

                headers = {
                    'User-Agent': self.get_random_user_agent(),
                    'Accept': 'application/json, */*',
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Referer': instagram_url,
                    'Origin': 'https://' + api['url'].split('/')[2]
                }

                if api.get('method') == 'post':
                    response = requests.post(
                        api['url'],
                        data=api.get('data', {}),
                        headers=headers,
                        timeout=30
                    )
                else:
                    response = requests.get(
                        api['url'],
                        headers=headers,
                        timeout=30
                    )

                if response.status_code == 200:
                    try:
                        # Instagram APIs often return HTML with video URLs embedded
                        content = response.text
                        metadata = {}

                        # Try to parse JSON response
                        try:
                            data = response.json()

                            # Look for video URL in different structures
                            video_url = None
                            if 'url' in data:
                                video_url = data['url']
                            elif 'video_url' in data:
                                video_url = data['video_url']
                            elif 'download_url' in data:
                                video_url = data['download_url']
                            elif 'data' in data:
                                if isinstance(data['data'], list) and len(data['data']) > 0:
                                    video_url = data['data'][0].get('url') or data['data'][0].get('video_url')
                                elif isinstance(data['data'], dict):
                                    video_url = data['data'].get('url') or data['data'].get('video_url')

                            if video_url:
                                print(f"  📥 Downloading video file...")
                                video_response = requests.get(
                                    video_url,
                                    headers={'User-Agent': self.get_random_user_agent()},
                                    timeout=self.download_timeout,
                                    stream=True
                                )

                                if video_response.status_code == 200:
                                    from io import BytesIO
                                    content_bytes = BytesIO()
                                    for chunk in video_response.iter_content(chunk_size=8192):
                                        if chunk:
                                            content_bytes.write(chunk)

                                    video_data = content_bytes.getvalue()

                                    if len(video_data) > 100000:  # At least 100KB
                                        size_mb = len(video_data) / (1024 * 1024)
                                        print(f"  ✅ {api['name']}: {size_mb:.2f} MB")
                                        return (video_data, metadata)
                                    else:
                                        print(f"  {Colors.RED}⚠️  {api['name']}: File too small ({len(video_data)} bytes){Colors.RESET}")
                        except:
                            # If JSON parsing fails, try regex to extract video URL from HTML
                            import re
                            video_patterns = [
                                r'"video_url":"([^"]+)"',
                                r'"url":"(https://[^"]*\.mp4[^"]*)"',
                                r'href="(https://[^"]*\.mp4[^"]*)"'
                            ]

                            for pattern in video_patterns:
                                matches = re.findall(pattern, content)
                                if matches:
                                    video_url = matches[0].replace('\\/', '/')

                                    print(f"  📥 Downloading video file...")
                                    video_response = requests.get(
                                        video_url,
                                        headers={'User-Agent': self.get_random_user_agent()},
                                        timeout=self.download_timeout,
                                        stream=True
                                    )

                                    if video_response.status_code == 200:
                                        from io import BytesIO
                                        content_bytes = BytesIO()
                                        for chunk in video_response.iter_content(chunk_size=8192):
                                            if chunk:
                                                content_bytes.write(chunk)

                                        video_data = content_bytes.getvalue()

                                        if len(video_data) > 100000:
                                            size_mb = len(video_data) / (1024 * 1024)
                                            print(f"  ✅ {api['name']}: {size_mb:.2f} MB")
                                            return (video_data, {})
                                        else:
                                            print(f"  {Colors.RED}⚠️  {api['name']}: File too small{Colors.RESET}")
                                    break
                    except Exception as parse_error:
                        print(f"  {Colors.RED}⚠️  {api['name']}: Parse error - {parse_error}{Colors.RESET}")

            except Exception as e:
                print(f"  {Colors.RED}❌ {api['name']} error: {e}{Colors.RESET}")

            time.sleep(2)

        print(f"  {Colors.RED}❌ All Instagram download APIs failed{Colors.RESET}")
        return None

    def download_from_tiktok_url(self, tiktok_url: str, video_id: str) -> Optional[tuple]:
        """Download video from TikTok URL using no-watermark APIs

        Returns:
            tuple: (video_data: bytes, metadata: dict) or None if failed
            metadata may contain: {'tiktok_upload_time': str}
        """
        print(f"  📥 Downloading video from TikTok...")

        # TikTok now shares via www.shorts.com — normalize back to the
        # canonical tiktok.com form the download APIs are tested against.
        if 'shorts.com' in tiktok_url.lower():
            tiktok_url = tiktok_url.replace('shorts.com', 'tiktok.com', 1)
            print(f"  🔗 Normalized shorts.com URL → {tiktok_url}")

        # List of no-watermark download APIs
        apis = [
            {
                'name': 'TikWM',
                'url': f'https://www.tikwm.com/api/?url={tiktok_url}&hd=1'
            },
            {
                'name': 'SnapTik',
                'url': f'https://snaptik.app/abc2.php?url={tiktok_url}'
            },
            {
                'name': 'SSSTik',
                'url': f'https://ssstik.io/abc?url={tiktok_url}'
            }
        ]

        for api in apis:
            try:
                print(f"  🔄 Trying {api['name']}...")

                headers = {
                    'User-Agent': self.get_random_user_agent(),
                    'Accept': 'application/json, */*',
                    'Referer': tiktok_url
                }

                # First, try to get video info/download link
                response = requests.get(
                    api['url'],
                    headers=headers,
                    timeout=30
                )

                if response.status_code == 200:
                    # Try to parse JSON response for download URL
                    try:
                        data = response.json()

                        # Different APIs have different response structures
                        video_url = None
                        metadata = {}

                        # TikWM structure
                        if 'data' in data and 'play' in data['data']:
                            video_url = data['data']['play']
                            # Extract upload time if available from TikWM API
                            if 'create_time' in data['data']:
                                try:
                                    create_timestamp = int(data['data']['create_time'])
                                    upload_time = datetime.fromtimestamp(create_timestamp).strftime('%d-%b-%Y %I:%M %p')
                                    metadata['tiktok_upload_time'] = upload_time
                                except:
                                    pass
                        # Alternative structure
                        elif 'url' in data:
                            video_url = data['url']
                        elif 'video_url' in data:
                            video_url = data['video_url']

                        if video_url:
                            # Download the actual video
                            print(f"  📥 Downloading video file...")
                            video_response = requests.get(
                                video_url,
                                headers={'User-Agent': self.get_random_user_agent()},
                                timeout=self.download_timeout,
                                stream=True
                            )

                            if video_response.status_code == 200:
                                from io import BytesIO
                                content = BytesIO()
                                for chunk in video_response.iter_content(chunk_size=8192):
                                    if chunk:
                                        content.write(chunk)

                                video_data = content.getvalue()

                                if len(video_data) > 100000:  # At least 100KB
                                    size_mb = len(video_data) / (1024 * 1024)
                                    print(f"  ✅ {api['name']}: {size_mb:.2f} MB")
                                    return (video_data, metadata)
                                else:
                                    print(f"  {Colors.RED}⚠️  {api['name']}: File too small ({len(video_data)} bytes){Colors.RESET}")
                    except:
                        pass

            except Exception as e:
                print(f"  {Colors.RED}❌ {api['name']} error: {e}{Colors.RESET}")

            time.sleep(2)  # Wait between API attempts

        print(f"  {Colors.RED}❌ All download APIs failed{Colors.RESET}")
        return None

    def update_sheet_status(self, sheet_tab_name: str, row_index: int, status: str):
        """Update status column in sheet"""
        try:
            if not self.sheets_client:
                return

            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
            worksheet = sheet.worksheet(sheet_tab_name)

            # Column J (index 10) = status
            worksheet.update_cell(row_index, 10, status)

        except Exception as e:
            print(f"  {Colors.RED}⚠️  Status update failed: {e}{Colors.RESET}")

    def update_old_video_in_sheet(
        self,
        sheet_tab_name: str,
        row_index: int,
        youtube_data: Dict,
        scheduled_time: str,
        status: str,
        tiktok_upload_time: str = ''
    ):
        """Update OLD video row with YouTube data"""
        try:
            if not self.sheets_client:
                return

            sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
            worksheet = sheet.worksheet(sheet_tab_name)

            # Column mapping:
            # E(5) = tiktok_upload_time
            # F(6) = yt_video_url
            # G(7) = youtube_id
            # H(8) = upload_time
            # I(9) = schedual_time
            # J(10) = status

            current_time = datetime.now().strftime('%d-%b-%Y %I:%M %p')

            # Update columns E, F, G, H, I, J
            updates = [
                {
                    'range': f'F{row_index}',
                    'values': [[youtube_data.get('youtube_url', '')]]
                },
                {
                    'range': f'G{row_index}',
                    'values': [[youtube_data.get('youtube_id', '')]]
                },
                {
                    'range': f'H{row_index}',
                    'values': [[current_time]]
                },
                {
                    'range': f'I{row_index}',
                    'values': [[scheduled_time]]
                },
                {
                    'range': f'J{row_index}',
                    'values': [[status]]
                }
            ]

            # Add tiktok_upload_time update if provided
            if tiktok_upload_time:
                updates.insert(0, {
                    'range': f'E{row_index}',
                    'values': [[tiktok_upload_time]]
                })

            worksheet.batch_update(updates, value_input_option='USER_ENTERED')

            print(f"  ✅ Updated sheet (row {row_index})")

        except Exception as e:
            print(f"  {Colors.RED}❌ Sheet update failed: {e}{Colors.RESET}")

    def process_channel(self, channel_config: Dict, mode: str = 'all', phase_mode: str = 'phase2') -> bool:
        """Process a single channel (NEW + OLD videos)

        Args:
            channel_config: Channel configuration
            mode: 'all' = process all videos, 'single' = process only 1 video
            phase_mode: 'both' = run both phases, 'phase1' = only fetch to sheet, 'phase2' = only upload from sheet (default)
        """
        print(f"\n{'='*70}")
        print(f"📺 Channel: {Colors.GREEN}{channel_config['channel_name']}{Colors.RESET}")
        print(f"{'='*70}")

        # Check if channel is in quota cooldown (from memory)
        channel_id = channel_config.get('channel_id', channel_config.get('channel_name'))
        if self.is_channel_in_quota_cooldown(channel_id):
            remaining_hours = self.get_quota_cooldown_remaining(channel_id)
            print(f"\n{Colors.YELLOW}⏸️  SKIPPING: Channel is in quota cooldown (from memory){Colors.RESET}")
            print(f"{Colors.YELLOW}⏳ Remaining cooldown time: {remaining_hours:.1f} hours{Colors.RESET}")
            print(f"{'='*70}")
            return False

        # Check if there's a quota notice in the sheet
        sheet_tab_name = channel_config.get('sheet_tab_name')
        if self.check_quota_notice_in_sheet(sheet_tab_name):
            print(f"\n{Colors.YELLOW}⏸️  SKIPPING: Found active quota notice in Google Sheet{Colors.RESET}")
            print(f"{Colors.YELLOW}➡️  Continuing to next channel...{Colors.RESET}")
            print(f"{'='*70}")
            return False

        total_uploaded = 0  # Track total uploads for SINGLE mode

        fetch_hours = channel_config.get('fetch_hours_limit', self.fetch_hours_limit)
        source_type = channel_config.get('source_type', 'tiktok')

        # ═══════════════════════════════════════════════════════════
        # PHASE 1: NEW VIDEOS (only for TikTok source)
        # ═══════════════════════════════════════════════════════════

        # Check if Phase 1 has already run for this channel in this session
        channel_identifier = channel_config.get('channel_name') or channel_config.get('sheet_tab_name')
        skip_phase1 = channel_identifier in self.phase1_completed_channels

        if source_type == 'tiktok' and phase_mode in ('both', 'phase1'):
            if skip_phase1:
                print(f"\n🆕 PHASE 1: SKIPPED (already checked for new videos in this session)")
                print(f"{'─'*70}")
            else:
                print(f"\n🆕 PHASE 1: NEW VIDEOS (TikTok → Sheet)")
                print(f"{'─'*70}")

                videos = self.fetch_tiktok_videos(channel_config['tiktok_username'])

                if not videos:
                    print("  ⚠️  No videos fetched{Colors.RESET}")
                else:
                    # Filter recent
                    recent_videos = self.filter_recent_videos(videos, hours=fetch_hours)

                    if recent_videos:
                        new_added = 0
                        newly_added_video_ids = []  # Track which videos we just added

                        # Add each NEW video to sheet (don't upload yet!)
                        for video in recent_videos:
                            # Check if stop was requested
                            if self.stop_requested:
                                print(f"\n  ⏸️  Stop requested - ending NEW video processing")
                                break

                            video_id = video.get('video_id') or video.get('id')

                            if video_id in self.processed_videos_this_run:
                                continue

                            if self.check_duplicate_in_sheet(channel_config['sheet_tab_name'], video_id):
                                print(f"  ⏭️  Skipping duplicate: {video_id}")
                                continue

                            username = video.get('author', {}).get('unique_id') or channel_config['tiktok_username']

                            # Construct proper TikTok URL
                            tiktok_url = video.get('webpage_url') or f"https://www.tiktok.com/@{username}/video/{video_id}"

                            # Try to fetch REAL metadata using yt-dlp (quick info only, no download)
                            video_title = ''
                            video_caption = ''
                            upload_time = ''

                            try:
                                print(f"  📋 Fetching metadata for {video_id[:12]}...")
                                cmd = [
                                    sys.executable,
                                    '-m', 'yt_dlp',
                                    '--no-download',
                                    '--dump-json',
                                    '--no-playlist',
                                    tiktok_url
                                ]

                                result = subprocess.run(
                                    cmd,
                                    capture_output=True,
                                    text=True,
                                    timeout=15,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                                )

                                if result.returncode == 0 and result.stdout:
                                    import json
                                    metadata = json.loads(result.stdout)

                                    video_title = metadata.get('title') or metadata.get('description', 'TikTok Video')
                                    video_caption = metadata.get('description') or metadata.get('title', '')

                                    # Get upload timestamp
                                    timestamp = metadata.get('timestamp') or metadata.get('upload_date')
                                    if timestamp:
                                        try:
                                            if isinstance(timestamp, int):
                                                upload_time = datetime.fromtimestamp(timestamp).strftime('%d-%b-%Y %I:%M %p')
                                            elif isinstance(timestamp, str) and len(timestamp) == 8:  # YYYYMMDD format
                                                upload_time = datetime.strptime(timestamp, '%Y%m%d').strftime('%d-%b-%Y %I:%M %p')
                                        except:
                                            pass

                                    print(f"  ✓ Metadata: {video_title[:40]}...")
                                else:
                                    # yt-dlp failed - show error for debugging
                                    print(f"  ⚠️  yt-dlp failed (code {result.returncode})")
                                    if result.stderr:
                                        error_msg = result.stderr[:200].replace('\n', ' ')
                                        print(f"  ⚠️  Error: {error_msg}")

                                    # Use Playwright data as fallback
                                    video_title = video.get('title', 'TikTok Video')
                                    video_caption = video.get('description', '')
                                    # Use create_time from Playwright if available
                                    create_time = video.get('create_time') or video.get('createTime')
                                    if create_time:
                                        try:
                                            upload_time = datetime.fromtimestamp(int(create_time)).strftime('%d-%b-%Y %I:%M %p')
                                        except:
                                            pass

                            except Exception as e:
                                # If metadata fetch fails, use Playwright data
                                video_title = video.get('title', 'TikTok Video')
                                video_caption = video.get('description', '')
                                # Use create_time from Playwright if available
                                create_time = video.get('create_time') or video.get('createTime')
                                if create_time:
                                    try:
                                        upload_time = datetime.fromtimestamp(int(create_time)).strftime('%d-%b-%Y %I:%M %p')
                                    except:
                                        pass
                                print(f"  ⚠️  Could not fetch metadata: {str(e)[:50]}")

                            # Fallback to generic if still empty
                            if not video_title:
                                video_title = 'TikTok Video'

                            # If upload_time is still empty, use current time as estimate
                            if not upload_time:
                                upload_time = datetime.now().strftime('%d-%b-%Y %I:%M %p')
                                print(f"  ⚠️  Using current time as upload time estimate")

                            # FINAL TIME FILTER CHECK (for videos that had no timestamp from Playwright)
                            # If video had create_time=0, we check it now with yt-dlp's timestamp
                            if video.get('create_time', 0) == 0:
                                # This video had no timestamp from Playwright, check yt-dlp timestamp
                                try:
                                    # Parse upload_time back to datetime for comparison
                                    video_datetime = datetime.strptime(upload_time, '%d-%b-%Y %I:%M %p')
                                    cutoff = datetime.now() - timedelta(hours=hours)

                                    if video_datetime < cutoff:
                                        # Video is too old, skip it
                                        print(f"  ⏭️  Skipping {video_id[:12]} (uploaded {upload_time}, outside {hours}h window)")
                                        continue
                                except Exception as e:
                                    # If we can't parse the time, keep the video (benefit of doubt)
                                    pass

                            # Add video to sheet with full metadata
                            try:
                                if not self.sheets_client:
                                    print(f"  ⚠️  Sheets client not available")
                                    continue

                                sheet = self.sheets_client.open_by_key(self.spreadsheet_id)
                                worksheet = sheet.worksheet(channel_config['sheet_tab_name'])

                                # Row with TikTok metadata (Phase 2 will add YouTube data when uploading)
                                row = [
                                    video_id,      # A: tiktok_video_id
                                    tiktok_url,    # B: tiktok_video_url
                                    video_title[:100],   # C: tiktok_video_title (truncate to 100 chars)
                                    video_caption[:200], # D: tiktok_caption (truncate to 200 chars)
                                    upload_time,   # E: tiktok_upload_time
                                    '',            # F: yt_video_url (Phase 2 will fill)
                                    '',            # G: youtube_id (Phase 2 will fill)
                                    '',            # H: upload_time (Phase 2 will fill)
                                    '',            # I: schedule_time (Phase 2 will fill)
                                    ''             # J: status (Phase 2 will fill)
                                ]

                                worksheet.append_row(row, value_input_option='USER_ENTERED')

                                # Invalidate cache
                                if channel_config['sheet_tab_name'] in self.sheets_cache:
                                    del self.sheets_cache[channel_config['sheet_tab_name']]

                                all_rows = worksheet.get_all_values()
                                row_index = len(all_rows)

                                print(f"  ✅ Added to sheet (row {row_index}): {video_id}")
                                new_added += 1
                                newly_added_video_ids.append(video_id)  # Track this video ID

                            except Exception as e:
                                print(f"  ❌ Failed to add to sheet: {e}")
                                continue

                        if new_added > 0:
                            print(f"\n✅ Phase 1 complete: {new_added} NEW videos added to sheet")
                            print(f"   📤 Phase 2 will now upload these NEW videos first...")
                        else:
                            print(f"\n  ℹ️  No new videos added (all were duplicates)")

                        # Invalidate cache to ensure Phase 2 sees the new videos
                        if channel_config['sheet_tab_name'] in self.sheets_cache:
                            del self.sheets_cache[channel_config['sheet_tab_name']]
                    else:
                        print(f"  ℹ️  No new videos in last {fetch_hours} hours")

                # Mark Phase 1 as completed for this channel
                self.phase1_completed_channels.add(channel_identifier)

        # ═══════════════════════════════════════════════════════════
        # PHASE 2: OLD VIDEOS / LOCAL FOLDER VIDEOS
        # ═══════════════════════════════════════════════════════════

        # Skip Phase 2 if phase_mode is 'phase1'
        if phase_mode == 'phase1':
            print(f"\n📦 PHASE 2: Skipped (Phase 1 only mode)")
        # Skip Phase 2 if SINGLE mode and already uploaded in Phase 1
        elif mode == 'single' and total_uploaded >= 1:
            print(f"\n📦 PHASE 2: Skipped (SINGLE mode - already uploaded 1 video)")
        elif phase_mode in ('both', 'phase2') and (self.process_old_videos_mode or source_type == 'local_folder'):
            if source_type == 'local_folder':
                print(f"\n📁 PHASE 2: LOCAL FOLDER VIDEOS (from sheet)")
            else:
                print(f"\n📦 PHASE 2: OLD VIDEOS (from sheet)")
            print(f"{'─'*70}")

            # Find videos in sheet based on source type
            if source_type == 'local_folder':
                source_folder = channel_config.get('video_source_folder', '')
                uploaded_folder = channel_config.get('video_uploaded_folder', '')
                sheet_free_mode = channel_config.get('sheet_free_mode', False)

                if not source_folder:
                    print(f"  {Colors.RED}⚠️  No source folder configured{Colors.RESET}")
                elif sheet_free_mode:
                    # SHEET-FREE MODE: Upload directly from folder without Google Sheet
                    print(f"  📁 SHEET-FREE MODE: Processing local folder videos directly")

                    if not uploaded_folder:
                        print(f"  {Colors.RED}⚠️  No uploaded folder configured{Colors.RESET}")
                    else:
                        video_files = self.find_local_videos_sheet_free(source_folder, uploaded_folder)

                        if video_files:
                            print(f"  ℹ️  Found {len(video_files)} video files to upload")

                            local_uploaded = 0

                            for video_file_path in video_files:
                                # Check if stop was requested
                                if self.stop_requested:
                                    print(f"\n  ⏸️  Stop requested - ending LOCAL video processing")
                                    break

                                # Check if channel is in quota cooldown
                                channel_id = channel_config.get('channel_id', channel_config.get('channel_name'))
                                if self.is_channel_in_quota_cooldown(channel_id):
                                    remaining_hours = self.get_quota_cooldown_remaining(channel_id)
                                    print(f"\n⏸️  STOPPING: Channel entered quota cooldown")
                                    print(f"⏳ Remaining cooldown time: {remaining_hours:.1f} hours")
                                    break

                                success = self.process_local_video_sheet_free(channel_config, video_file_path, uploaded_folder)

                                if success:
                                    local_uploaded += 1
                                    total_uploaded += 1
                                else:
                                    # If upload failed, check if it was due to quota
                                    if self.is_channel_in_quota_cooldown(channel_id):
                                        remaining_hours = self.get_quota_cooldown_remaining(channel_id)
                                        print(f"\n⏸️  STOPPING: Quota exceeded, skipping remaining videos")
                                        print(f"⏳ Cooldown time: {remaining_hours:.1f} hours")
                                        break

                                # Check if SINGLE mode - stop after 1 video
                                if mode == 'single' and total_uploaded >= 1:
                                    print(f"\n  🎯 SINGLE mode: Uploaded 1 video, stopping")
                                    break

                                # Check if stop was requested before waiting
                                if self.stop_requested:
                                    print(f"\n  ⏸️  Stop requested - ending LOCAL video processing")
                                    break

                                # Wait before next video (only in ALL mode)
                                if mode == 'all':
                                    print(f"⏳ Waiting {self.channel_interval_minutes} min...")
                                    time.sleep(self.channel_interval_minutes * 60)

                            print(f"\n✅ Phase 2 complete: {local_uploaded}/{len(video_files)} LOCAL videos uploaded (sheet-free)")
                        else:
                            print(f"  ℹ️  No video files found in source folder")
                else:
                    # SHEET MODE: Upload using Google Sheet tracking
                    local_videos = self.find_local_videos_in_sheet(channel_config['sheet_tab_name'], source_folder)

                    if local_videos:
                        print(f"  ℹ️  Found {len(local_videos)} LOCAL videos to process")

                        local_uploaded = 0

                        for row_index, video_info, video_file_path in local_videos:
                            # Check if stop was requested
                            if self.stop_requested:
                                print(f"\n  ⏸️  Stop requested - ending LOCAL video processing")
                                break

                            # Check if channel is in quota cooldown (might have been added during processing)
                            channel_id = channel_config.get('channel_id', channel_config.get('channel_name'))
                            if self.is_channel_in_quota_cooldown(channel_id):
                                remaining_hours = self.get_quota_cooldown_remaining(channel_id)
                                print(f"\n⏸️  STOPPING: Channel entered quota cooldown")
                                print(f"⏳ Remaining cooldown time: {remaining_hours:.1f} hours")
                                break

                            success = self.process_local_video(channel_config, channel_config['sheet_tab_name'], row_index, video_info, video_file_path)

                            if success:
                                local_uploaded += 1
                                total_uploaded += 1
                            else:
                                # If upload failed, check if it was due to quota
                                if self.is_channel_in_quota_cooldown(channel_id):
                                    remaining_hours = self.get_quota_cooldown_remaining(channel_id)
                                    print(f"\n⏸️  STOPPING: Quota exceeded, skipping remaining videos")
                                    print(f"⏳ Cooldown time: {remaining_hours:.1f} hours")
                                    break

                            # Check if SINGLE mode - stop after 1 video
                            if mode == 'single' and total_uploaded >= 1:
                                print(f"\n  🎯 SINGLE mode: Uploaded 1 video, stopping")
                                break

                            # Check if stop was requested before waiting
                            if self.stop_requested:
                                print(f"\n  ⏸️  Stop requested - ending LOCAL video processing")
                                break

                            # Wait before next video (only in ALL mode)
                            if mode == 'all':
                                print(f"⏳ Waiting {self.channel_interval_minutes} min...")
                                time.sleep(self.channel_interval_minutes * 60)

                        print(f"\n✅ Phase 2 complete: {local_uploaded}/{len(local_videos)} LOCAL videos uploaded")
                    else:
                        print(f"  ℹ️  No LOCAL videos to process")
            else:
                # TikTok videos from sheet
                sheet_tab = channel_config['sheet_tab_name']
                print(f"  📊 Reading from sheet tab: {Colors.GREEN}'{sheet_tab}'{Colors.RESET}")
                all_videos = self.find_old_videos_in_sheet(sheet_tab)

                if all_videos:
                    # Separate NEW videos from OLD videos
                    # Strategy: Sort by TikTok upload date (newest first)
                    new_videos = []
                    old_videos = []

                    # First, separate videos just added in Phase 1
                    phase1_video_ids = set()
                    for row_index, video_info in all_videos:
                        video_id = video_info.get('video_id', '')
                        if 'newly_added_video_ids' in locals() and video_id in newly_added_video_ids:
                            new_videos.append((row_index, video_info))
                            phase1_video_ids.add(video_id)

                    # For remaining videos, separate by TikTok upload date
                    remaining_videos = []
                    for row_index, video_info in all_videos:
                        video_id = video_info.get('video_id', '')
                        if video_id not in phase1_video_ids:
                            remaining_videos.append((row_index, video_info))

                    # Sort remaining videos by TikTok upload time (newest first)
                    def parse_tiktok_date(video_tuple):
                        """Parse TikTok upload time for sorting"""
                        row_index, video_info = video_tuple
                        tiktok_time = video_info.get('tiktok_upload_time', '')

                        if not tiktok_time:
                            return datetime.min  # Put videos without date at the end

                        try:
                            # Try parsing common date formats
                            # Format: "19-Dec-2025 1:42 PM" or "28-Dec-2025 1:38 PM"
                            for fmt in ['%d-%b-%Y %I:%M %p', '%d-%b-%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S']:
                                try:
                                    return datetime.strptime(tiktok_time, fmt)
                                except ValueError:
                                    continue
                            return datetime.min
                        except Exception:
                            return datetime.min

                    # Sort by TikTok upload date (newest first)
                    remaining_videos.sort(key=parse_tiktok_date, reverse=True)

                    # Split into NEW (recent uploads on TikTok) and OLD (older uploads)
                    # Use last 50 videos by upload date as "recent"
                    if len(remaining_videos) > 50:
                        new_videos.extend(remaining_videos[:50])  # 50 most recent TikTok videos
                        old_videos.extend(remaining_videos[50:])  # Older TikTok videos
                    else:
                        # All remaining videos are considered "recent"
                        new_videos.extend(remaining_videos)

                    # Report counts
                    if new_videos:
                        print(f"  ✨ Found {len(new_videos)} NEW videos to upload (sorted by TikTok upload date)")
                    if old_videos:
                        print(f"  📦 Found {len(old_videos)} OLD videos to process")

                    total_to_process = new_videos + old_videos  # NEW first, then OLD
                    videos_uploaded = 0

                    # Process NEW videos first, then OLD videos
                    for idx, (row_index, video_info) in enumerate(total_to_process):
                        is_new_video = idx < len(new_videos)

                        if is_new_video:
                            # Check if this is actually from Phase 1 or just "recent by date"
                            video_id = video_info.get('video_id', '')
                            is_from_phase1 = video_id in phase1_video_ids if phase1_video_ids else False

                            print(f"\n  ╔══════════════════════════════════════════════════════════════")
                            if is_from_phase1:
                                print(f"  ║ ✨ NEW Video #{idx + 1}/{len(new_videos)} (from Phase 1)")
                            else:
                                print(f"  ║ 📅 RECENT Video #{idx + 1}/{len(new_videos)} (by upload date)")
                            print(f"  ╚══════════════════════════════════════════════════════════════")
                        else:
                            old_idx = idx - len(new_videos) + 1
                            print(f"\n  ╔══════════════════════════════════════════════════════════════")
                            print(f"  ║ 📦 OLD Video #{old_idx}/{len(old_videos)}")
                            print(f"  ╚══════════════════════════════════════════════════════════════")
                        # Check if stop was requested
                        if self.stop_requested:
                            print(f"\n  ⏸️  Stop requested - ending OLD video processing")
                            break

                        # Check if channel is in quota cooldown (might have been added during processing)
                        channel_id = channel_config.get('channel_id', channel_config.get('channel_name'))
                        if self.is_channel_in_quota_cooldown(channel_id):
                            remaining_hours = self.get_quota_cooldown_remaining(channel_id)
                            print(f"\n⏸️  STOPPING: Channel entered quota cooldown")
                            print(f"⏳ Remaining cooldown time: {remaining_hours:.1f} hours")
                            break

                        success = self.process_old_video(channel_config, channel_config['sheet_tab_name'], row_index, video_info)

                        if success:
                            videos_uploaded += 1
                            total_uploaded += 1
                        else:
                            # If upload failed, check if it was due to quota (channel may have been added to cooldown)
                            if self.is_channel_in_quota_cooldown(channel_id):
                                remaining_hours = self.get_quota_cooldown_remaining(channel_id)
                                print(f"\n⏸️  STOPPING: Quota exceeded, skipping remaining videos")
                                print(f"⏳ Cooldown time: {remaining_hours:.1f} hours")
                                break

                        # Check if SINGLE mode - stop after 1 video
                        if mode == 'single' and total_uploaded >= 1:
                            print(f"\n  🎯 SINGLE mode: Uploaded 1 video, stopping")
                            break

                        # Check if stop was requested before waiting
                        if self.stop_requested:
                            print(f"\n  ⏸️  Stop requested - ending video processing")
                            break

                        # Wait before next video (only in ALL mode, and not after last video)
                        if mode == 'all' and idx < len(total_to_process) - 1:
                            print(f"⏳ Waiting {self.channel_interval_minutes} min...")
                            time.sleep(self.channel_interval_minutes * 60)

                    # Summary
                    if new_videos and old_videos:
                        new_uploaded = min(videos_uploaded, len(new_videos))
                        old_uploaded = max(0, videos_uploaded - len(new_videos))
                        # Check if any videos were actually from Phase 1
                        has_phase1_videos = bool(phase1_video_ids)
                        label = "NEW" if has_phase1_videos else "RECENT"
                        print(f"\n✅ Phase 2 complete:")
                        print(f"   📅 {label} videos: {new_uploaded}/{len(new_videos)} uploaded")
                        print(f"   📦 OLD videos: {old_uploaded}/{len(old_videos)} uploaded")
                    elif new_videos:
                        has_phase1_videos = bool(phase1_video_ids)
                        label = "NEW" if has_phase1_videos else "RECENT"
                        print(f"\n✅ Phase 2 complete: {videos_uploaded}/{len(new_videos)} {label} videos uploaded")
                    else:
                        print(f"\n✅ Phase 2 complete: {videos_uploaded}/{len(old_videos)} OLD videos uploaded")
                else:
                    print(f"  ℹ️  No OLD videos to process")

        print(f"\n{'='*70}")
        print(f"✅ Channel complete!")
        print(f"{'='*70}")

        return True

    def get_enabled_channels(self) -> List[Dict]:
        """Get list of enabled channels"""
        return [ch for ch in self.channels.values() if ch.get('enabled', True)]

    def get_next_channel(self) -> Optional[Dict]:
        """Get next channel in rotation"""
        enabled = self.get_enabled_channels()

        if not enabled:
            return None

        if self.channels_processed_this_run >= len(enabled):
            self.current_channel_index = 0
            self.channels_processed_this_run = 0
            self.processed_videos_this_run = []
            self.save_state()
            return None

        channel = enabled[self.current_channel_index]
        return channel

    def move_to_next_channel(self):
        """Move to next channel in rotation"""
        enabled = self.get_enabled_channels()

        self.channels_processed_this_run += 1
        self.processed_videos_this_run = []
        self.current_channel_index = (self.current_channel_index + 1) % len(enabled)
        self.save_state()

    # ═══════════════════════════════════════════════════════════
    # LIVE MONITOR - AUTO-CHECK METHODS
    # ═══════════════════════════════════════════════════════════

    def set_auto_check_interval(self, minutes: int):
        """Set the auto-check interval in minutes"""
        if minutes < 1:
            print("⚠️  Interval must be at least 1 minute{Colors.RESET}")
            return False

        self.auto_check_interval = minutes * 60  # Convert to seconds
        print(f"✅ Auto-check interval set to {minutes} minute(s)")
        return True

    def set_auto_check_log_callback(self, callback):
        """Set callback for auto-check logging (for GUI integration)"""
        self.auto_check_log_callback = callback

    def _auto_log(self, message: str):
        """Log message via callback or print"""
        if self.auto_check_log_callback:
            self.auto_check_log_callback(message)
        else:
            print(message)

    def start_auto_check(self):
        """Start the Live Monitor background thread"""
        if self.auto_check_enabled:
            self._auto_log("⚠️  Live Monitor already running{Colors.RESET}")
            return False

        self.auto_check_enabled = True
        self.auto_check_stats['status'] = 'Active'
        self.auto_check_thread = threading.Thread(target=self._auto_check_loop, daemon=True)
        self.auto_check_thread.start()

        interval_min = self.auto_check_interval // 60
        self._auto_log(f"🟢 Live Monitor started - checking every {interval_min} minute(s)")
        return True

    def stop_auto_check(self):
        """Stop the Live Monitor"""
        if not self.auto_check_enabled:
            self._auto_log("⚠️  Live Monitor not running{Colors.RESET}")
            return False

        self.auto_check_enabled = False
        self.auto_check_stats['status'] = 'Stopped'

        self._auto_log("🔴 Live Monitor stopped")
        return True

    def _auto_check_loop(self):
        """Background loop for Live Monitor"""
        import sys

        # Stdout redirector for Live Monitor
        class StdoutRedirector:
            def __init__(self, callback):
                self.callback = callback

            def write(self, text):
                if self.callback and text.strip():
                    self.callback(text.rstrip())

            def flush(self):
                pass

        # Redirect all print() to GUI callback
        old_stdout = sys.stdout
        if self.auto_check_log_callback:
            sys.stdout = StdoutRedirector(self.auto_check_log_callback)

        try:
            while self.auto_check_enabled:
                try:
                    self.auto_check_stats['last_check'] = datetime.now().strftime('%d-%b %I:%M %p')
                    self.auto_check_stats['next_check'] = (
                        datetime.now() + timedelta(seconds=self.auto_check_interval)
                    ).strftime('%d-%b %I:%M %p')

                    self._auto_log(f"\n{'='*70}")
                    self._auto_log(f"🔍 Live Monitor Check #{self.auto_check_stats['total_checks'] + 1}")
                    self._auto_log(f"{'='*70}")

                    videos_found_this_check = 0
                    videos_uploaded_this_check = 0

                    # Check each enabled channel
                    for channel in self.get_enabled_channels():
                        if not self.auto_check_enabled:
                            break

                        self._auto_log(f"\n📺 Checking: {channel['channel_name']}")

                        # Check if channel is in quota cooldown
                        channel_id = channel.get('channel_id', channel.get('channel_name'))
                        if self.is_channel_in_quota_cooldown(channel_id):
                            remaining_hours = self.get_quota_cooldown_remaining(channel_id)
                            self._auto_log(f"  ⏸️  SKIPPED: Quota cooldown ({remaining_hours:.1f}h remaining)")
                            continue

                        # Fetch videos
                        videos = self.fetch_tiktok_videos(channel['tiktok_username'])
                        if not videos:
                            continue

                        # Filter recent videos using fetch_hours_limit from config
                        recent_videos = self.filter_recent_videos(videos, hours=self.fetch_hours_limit)
                        videos_found_this_check += len(recent_videos)

                        # Process new videos
                        for video in recent_videos:
                            if not self.auto_check_enabled:
                                break

                            video_id = video.get('video_id') or video.get('id')

                            # Skip if already processed
                            if self.check_duplicate_in_sheet(channel['sheet_tab_name'], video_id):
                                continue

                            # Process video
                            username = video.get('author', {}).get('unique_id') or channel['tiktok_username']

                            video_info = {
                                'video_id': video_id,
                                'title': video.get('title') or video.get('desc', 'Untitled'),
                                'caption': video.get('desc') or video.get('title', ''),
                                'mp4_url': video.get('play') or video.get('download_addr', ''),
                                'tiktok_url': f"https://www.tiktok.com/@{username}/video/{video_id}",
                                'tiktok_upload_time': datetime.fromtimestamp(video.get('create_time', 0)).strftime('%d-%b-%Y %I:%M %p')
                            }

                            self._auto_log(f"\n  🆕 NEW: {video_info['title'][:50]}")

                            # Download
                            video_data = self.download_video_binary(video_info['mp4_url'], video_id)
                            if not video_data:
                                continue

                            # Schedule
                            scheduled_time = self.calculate_schedule_time(channel['sheet_tab_name'])

                            # Upload
                            youtube_data = self.upload_to_youtube(channel, video_data, video_info, scheduled_time)
                            if not youtube_data:
                                continue

                            # Show completion and schedule info
                            upload_completed = datetime.now().strftime('%d-%b-%Y %I:%M %p')
                            self._auto_log(f"  🕐 Upload completed: {upload_completed}")
                            self._auto_log(f"  📅 Scheduled to publish: {Colors.GREEN}{scheduled_time}{Colors.RESET}")

                            # Log
                            self.log_to_sheet(channel['sheet_tab_name'], video_info, youtube_data, scheduled_time, 'done')
                            self._mark_uploaded(video_id)

                            videos_uploaded_this_check += 1
                            self._auto_log(f"  ✅ Uploaded!")

                            # Use auto_check_interval for Live Monitor, not channel_interval_minutes
                            wait_minutes = self.auto_check_interval // 60  # Convert seconds to minutes
                            if wait_minutes > 0:
                                self._auto_log(f"  ⏳ Waiting {wait_minutes} min before next video...")
                                # Interruptible sleep - check every second if we should stop
                                for _ in range(self.auto_check_interval):
                                    if not self.auto_check_enabled:
                                        break
                                    time.sleep(1)

                    # Update stats
                    self.auto_check_stats['total_checks'] += 1
                    self.auto_check_stats['videos_found'] += videos_found_this_check
                    self.auto_check_stats['videos_uploaded'] += videos_uploaded_this_check

                    self._auto_log(f"\n{'='*70}")
                    self._auto_log(f"✅ Check complete: Found {videos_found_this_check}, Uploaded {videos_uploaded_this_check}")
                    self._auto_log(f"{'='*70}")

                    # Wait for next check
                    if self.auto_check_enabled:
                        interval_min = self.auto_check_interval // 60
                        self._auto_log(f"\n⏳ Next check in {interval_min} minute(s)...")
                        for _ in range(self.auto_check_interval):
                            if not self.auto_check_enabled:
                                break
                            time.sleep(1)

                except Exception as e:
                    self._auto_log(f"❌ Live Monitor error: {e}{Colors.RESET}")
                    import traceback
                    self._auto_log(traceback.format_exc())
                    time.sleep(60)

            self._auto_log("🔴 Live Monitor thread ended")
        finally:
            # Restore stdout
            sys.stdout = old_stdout

    def get_auto_check_stats(self) -> Dict:
        """Get Live Monitor statistics"""
        return self.auto_check_stats.copy()

    # ═══════════════════════════════════════════════════════════
    # END LIVE MONITOR
    # ═══════════════════════════════════════════════════════════

    def run_continuous(self):
        """Run continuous automation"""
        print("\n🚀 Starting TikTok → YouTube automation (DUAL-MODE)")
        print("Press Ctrl+C to stop\n")

        try:
            while True:
                channel = self.get_next_channel()

                if not channel:
                    print("\n✅ All channels processed!")
                    print("⏳ Waiting 10 minutes before next cycle...")
                    time.sleep(600)
                    continue

                success = self.process_channel(channel)
                self.move_to_next_channel()

                if success:
                    print(f"\n⏳ Waiting {self.channel_interval_minutes} minutes...")
                    time.sleep(self.channel_interval_minutes * 60)
                else:
                    print(f"\n⏳ Waiting 1 minute before next channel...")
                    time.sleep(60)

        except KeyboardInterrupt:
            print("\n\n⏸️  Automation stopped")
            self.save_state()


def main():
    """Main function"""
    uploader = TikTokYouTubeUploader()

    while True:
        print("\n" + "="*70)
        print("TikTok → YouTube Auto Uploader - LIVE MONITOR EDITION")
        print("="*70)
        print("1. Start continuous automation")
        print("2. Process one channel")
        print("3. Start Live Monitor (auto-check every 2 min)")
        print("4. Stop Live Monitor")
        print("5. Show Live Monitor stats")
        print("6. Show status")
        print("7. Reset state")
        print("8. Exit")

        choice = input("\nChoice (1-8): ").strip()

        if choice == '1':
            uploader.run_continuous()
        elif choice == '2':
            channel = uploader.get_next_channel()
            if channel:
                uploader.process_channel(channel)
                uploader.move_to_next_channel()
            else:
                print("No channels available")
        elif choice == '3':
            uploader.start_auto_check()
        elif choice == '4':
            uploader.stop_auto_check()
        elif choice == '5':
            stats = uploader.get_auto_check_stats()
            print("\n" + "="*70)
            print("📊 LIVE MONITOR STATS")
            print("="*70)
            print(f"Status: {stats['status']}")
            print(f"Total Checks: {stats['total_checks']}")
            print(f"Videos Found: {stats['videos_found']}")
            print(f"Videos Uploaded: {stats['videos_uploaded']}")
            print(f"Last Check: {stats['last_check'] or 'Never'}")
            print(f"Next Check: {stats['next_check'] or 'N/A'}")
            print("="*70)
        elif choice == '6':
            print(f"\nCurrent channel index: {uploader.current_channel_index}")
            print(f"Channels processed this run: {uploader.channels_processed_this_run}")
            print(f"Videos processed: {len(uploader.processed_videos_this_run)}")
        elif choice == '7':
            uploader.current_channel_index = 0
            uploader.channels_processed_this_run = 0
            uploader.processed_videos_this_run = []
            uploader.save_state()
            print("✓ State reset")
        elif choice == '8':
            if uploader.auto_check_enabled:
                uploader.stop_auto_check()
            break


if __name__ == "__main__":
    main()
