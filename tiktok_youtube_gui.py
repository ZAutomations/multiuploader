"""
TikTok to YouTube Auto Uploader GUI - Professional Edition
Full-featured dashboard matching YouTube uploader design
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import queue
import json
import sys
import time
from pathlib import Path
from datetime import datetime
import importlib.util
import hashlib
import hmac

# Import backend
TikTokUploader = None
try:
    from tiktok_youtube_uploader import TikTokYouTubeUploader
    TikTokUploader = TikTokYouTubeUploader
    print("Backend loaded")
except ImportError:
    script_dir = Path(__file__).parent if '__file__' in globals() else Path.cwd()
    backend_path = script_dir / 'tiktok_youtube_uploader.py'

    if backend_path.exists():
        spec = importlib.util.spec_from_file_location("tiktok_backend", str(backend_path))
        tiktok_module = importlib.util.module_from_spec(spec)
        sys.modules['tiktok_backend'] = tiktok_module
        spec.loader.exec_module(tiktok_module)
        TikTokUploader = tiktok_module.TikTokYouTubeUploader
        print("Backend loaded (dynamic)")


class PasswordDialog:
    """Password dialog for authentication and locking"""

    def __init__(self, parent, title="Enter Password", is_setup=False):
        self.result = None
        self.is_setup = is_setup

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("400x250")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self.on_cancel)

        # Make it always on top and centered
        self.dialog.attributes('-topmost', True)

        # Colors
        bg = '#2c3e50'
        text_color = '#ecf0f1'
        accent = '#3498db'

        self.dialog.configure(bg=bg)

        # Main container
        main = tk.Frame(self.dialog, bg=bg, padx=30, pady=30)
        main.pack(fill=tk.BOTH, expand=True)

        # Icon and title
        tk.Label(
            main, text="🔒",
            font=('Arial', 40),
            bg=bg, fg=text_color
        ).pack(pady=(0, 10))

        if is_setup:
            tk.Label(
                main, text="Setup Password",
                font=('Arial', 14, 'bold'),
                bg=bg, fg=text_color
            ).pack(pady=(0, 5))

            tk.Label(
                main, text="Create a password to secure your application",
                font=('Arial', 9),
                bg=bg, fg='#95a5a6'
            ).pack(pady=(0, 20))
        else:
            tk.Label(
                main, text="Application Locked",
                font=('Arial', 14, 'bold'),
                bg=bg, fg=text_color
            ).pack(pady=(0, 5))

            tk.Label(
                main, text="Enter password to unlock",
                font=('Arial', 9),
                bg=bg, fg='#95a5a6'
            ).pack(pady=(0, 20))

        # Password entry
        self.password_var = tk.StringVar()
        password_frame = tk.Frame(main, bg=bg)
        password_frame.pack(fill=tk.X, pady=(0, 20))

        self.password_entry = tk.Entry(
            password_frame,
            textvariable=self.password_var,
            show='●',
            font=('Arial', 12),
            bg='#34495e',
            fg=text_color,
            insertbackground=text_color,
            relief=tk.FLAT,
            bd=0
        )
        self.password_entry.pack(fill=tk.X, ipady=10, ipadx=10)
        self.password_entry.focus()
        self.password_entry.bind('<Return>', lambda e: self.on_submit())

        # Buttons
        btn_frame = tk.Frame(main, bg=bg)
        btn_frame.pack(fill=tk.X)

        tk.Button(
            btn_frame,
            text="✓ Submit" if not is_setup else "✓ Set Password",
            command=self.on_submit,
            font=('Arial', 10, 'bold'),
            bg=accent,
            fg='white',
            relief=tk.FLAT,
            cursor='hand2',
            padx=20,
            pady=8
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))

        if not is_setup:
            tk.Button(
                btn_frame,
                text="✕ Cancel",
                command=self.on_cancel,
                font=('Arial', 10, 'bold'),
                bg='#e74c3c',
                fg='white',
                relief=tk.FLAT,
                cursor='hand2',
                padx=20,
                pady=8
            ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

        # Center dialog
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (self.dialog.winfo_width() // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (self.dialog.winfo_height() // 2)
        self.dialog.geometry(f"+{x}+{y}")

    def on_submit(self):
        password = self.password_var.get()
        if not password:
            messagebox.showerror("Error", "Password cannot be empty!")
            return

        self.result = password
        self.dialog.destroy()

    def on_cancel(self):
        if self.is_setup:
            messagebox.showerror("Error", "Password is required to use this application!")
            return
        self.result = None
        self.dialog.destroy()

    def show(self):
        self.dialog.wait_window()
        return self.result


class ChannelSelectionDialog:
    """Dialog for selecting channels and upload mode"""

    def __init__(self, parent, channels_config):
        self.result = None
        self.channels_config = channels_config

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Select Channels to Process")
        self.dialog.geometry("650x650")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Colors
        bg = '#f5f5f5'
        card_bg = '#ffffff'
        accent = '#3498db'
        success = '#27ae60'
        error = '#e74c3c'

        self.dialog.configure(bg=bg)

        # Main container
        main = tk.Frame(self.dialog, bg=bg, padx=20, pady=20)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(
            main, text="📺 Select Channels to Process",
            font=('Arial', 14, 'bold'), bg=bg
        ).pack(pady=(0, 15))

        # Channels frame with scrollbar
        channels_frame = tk.Frame(main, bg=card_bg, relief=tk.SOLID, borderwidth=1)
        channels_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # Canvas for scrolling
        canvas = tk.Canvas(channels_frame, bg=card_bg, highlightthickness=0)
        scrollbar = tk.Scrollbar(channels_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=card_bg)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Channel checkboxes
        self.channel_vars = {}
        enabled_channels = [(ch_id, ch) for ch_id, ch in channels_config.items() if ch.get('enabled', True)]

        if not enabled_channels:
            tk.Label(
                scrollable_frame, text="No enabled channels found",
                font=('Arial', 10), bg=card_bg, fg='#7f8c8d'
            ).pack(pady=20)
        else:
            for ch_id, ch_data in enabled_channels:
                var = tk.BooleanVar(value=True)
                self.channel_vars[ch_id] = var

                frame = tk.Frame(scrollable_frame, bg=card_bg)
                frame.pack(fill=tk.X, padx=10, pady=5)

                cb = tk.Checkbutton(
                    frame,
                    text=f"{ch_data.get('channel_name', 'Unknown')} (@{ch_data.get('tiktok_username', '')})",
                    variable=var,
                    font=('Arial', 10),
                    bg=card_bg,
                    activebackground=card_bg
                )
                cb.pack(anchor=tk.W)

        # Selection buttons
        btn_frame = tk.Frame(main, bg=bg)
        btn_frame.pack(fill=tk.X, pady=(0, 15))

        tk.Button(
            btn_frame, text="Select All",
            command=self.select_all,
            bg='#3498db', fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=15, pady=5
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(
            btn_frame, text="Deselect All",
            command=self.deselect_all,
            bg='#95a5a6', fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=15, pady=5
        ).pack(side=tk.LEFT)

        # Mode selection
        mode_frame = tk.LabelFrame(main, text="Upload Mode", bg=card_bg, font=('Arial', 10, 'bold'), padx=10, pady=10)
        mode_frame.pack(fill=tk.X, pady=(0, 15))

        self.mode_var = tk.StringVar(value="all")

        tk.Radiobutton(
            mode_frame,
            text="📤 Single Mode - Upload ONE video from each channel, then stop",
            variable=self.mode_var,
            value="single",
            font=('Arial', 10),
            bg=card_bg,
            activebackground=card_bg
        ).pack(anchor=tk.W, pady=2)

        tk.Radiobutton(
            mode_frame,
            text="📚 All Videos Mode - Upload ALL videos from each channel (one channel at a time)",
            variable=self.mode_var,
            value="all",
            font=('Arial', 10),
            bg=card_bg,
            activebackground=card_bg
        ).pack(anchor=tk.W, pady=2)

        tk.Radiobutton(
            mode_frame,
            text="🔄 Continuous Mode - Keep rotating between channels uploading 1 video each",
            variable=self.mode_var,
            value="continuous",
            font=('Arial', 10),
            bg=card_bg,
            activebackground=card_bg
        ).pack(anchor=tk.W, pady=2)

        # Action buttons
        action_frame = tk.Frame(main, bg=bg)
        action_frame.pack(fill=tk.X, pady=(10, 0))

        tk.Button(
            action_frame, text="✅ Start Processing",
            command=self.on_start,
            bg=success, fg='white',
            font=('Arial', 12, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20, pady=12,
            width=18
        ).pack(side=tk.LEFT, expand=True, padx=(0, 5))

        tk.Button(
            action_frame, text="❌ Cancel",
            command=self.on_cancel,
            bg=error, fg='white',
            font=('Arial', 12, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20, pady=12,
            width=18
        ).pack(side=tk.LEFT, expand=True, padx=(5, 0))

        # Center dialog
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (self.dialog.winfo_width() // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (self.dialog.winfo_height() // 2)
        self.dialog.geometry(f"+{x}+{y}")

    def select_all(self):
        for var in self.channel_vars.values():
            var.set(True)

    def deselect_all(self):
        for var in self.channel_vars.values():
            var.set(False)

    def on_start(self):
        selected = [ch_id for ch_id, var in self.channel_vars.items() if var.get()]

        if not selected:
            messagebox.showwarning("No Selection", "Please select at least one channel")
            return

        self.result = {
            'channels': selected,
            'mode': self.mode_var.get()
        }
        self.dialog.destroy()

    def on_cancel(self):
        self.result = None
        self.dialog.destroy()

    def show(self):
        self.dialog.wait_window()
        return self.result


class TikTokYouTubeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TikTok → YouTube Auto Uploader - Professional Edition")
        self.root.geometry("1600x1000")

        # Colors matching original design
        self.bg = '#f5f5f5'
        self.card_bg = '#ffffff'
        self.header_bg = '#2c3e50'
        self.accent = '#3498db'
        self.success = '#27ae60'
        self.warning = '#f39c12'
        self.error = '#e74c3c'
        self.text = '#2c3e50'
        self.text_light = '#7f8c8d'

        self.root.configure(bg=self.bg)

        # State
        self.is_running = False
        self.automation_thread = None  # Track the running automation thread
        self.log_queue = queue.Queue()
        self.is_loading = False  # Prevent concurrent heavy operations
        self.selective_mode = False  # Flag for channel selection mode
        self.selected_channels = []
        self.upload_mode = 'single'
        self.is_locked = False  # Lock state
        self.lock_overlay = None  # Lock screen overlay
        self.start_lock = threading.Lock()  # Prevent race condition on start_automation()

        # Config files
        script_dir = Path(__file__).parent if '__file__' in globals() else Path.cwd()
        self.config_file = script_dir / "tiktok_uploader_config.json"
        self.password_file = script_dir / ".app_password"  # Hidden file for password
        self.channels_file = script_dir / "tiktok_channels_config.json"

        self.config = self.load_config()
        self.channels_config = self.load_channels_config()

        # Backend
        self.uploader = None

        # Build GUI
        self.build_gui()
        self.process_logs()

        # Check password AFTER GUI is built
        self.root.after(100, self.check_password_setup)

        # Initialize backend
        self.root.after(500, self.initialize_backend)

    def load_config(self):
        """Load configuration"""
        script_dir = Path(__file__).parent if '__file__' in globals() else Path.cwd()

        default = {
            'credentials_folder': str(script_dir / 'youtube_credentials'),
            'spreadsheet_url': '',
            'schedule_gap_min_hours': 2,
            'schedule_gap_max_hours': 3,
            'schedule_gap_random_minutes': 40,
            'channel_interval_minutes': 2,
            'fetch_hours_limit': 72  # Time range to fetch from TikTok
        }

        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    default.update(loaded)
            except:
                pass

        Path(default['credentials_folder']).mkdir(parents=True, exist_ok=True)
        return default

    def load_channels_config(self):
        """Load channels configuration with robust error handling"""
        if self.channels_file.exists():
            try:
                with open(self.channels_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.log(f"✅ Loaded {len(data)} channels from config", 'success')
                        return data
                    else:
                        self.log("⚠️  Invalid channels config format", 'warning')
                        return {}
            except json.JSONDecodeError as e:
                self.log(f"⚠️  Channels config JSON error: {e}", 'warning')
                return {}
            except Exception as e:
                self.log(f"⚠️  Could not load channels: {e}", 'warning')
                return {}
        return {}

    def hash_password(self, password):
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()

    def save_password(self, password):
        """Save hashed password"""
        try:
            hashed = self.hash_password(password)
            with open(self.password_file, 'w') as f:
                f.write(hashed)
            return True
        except Exception as e:
            messagebox.showerror("Error", f"Could not save password: {e}")
            return False

    def verify_password(self, password):
        """Verify password against saved hash (constant-time compare)
        so timing doesn't leak how many leading hash bytes match."""
        try:
            if not self.password_file.exists():
                return False
            with open(self.password_file, 'r') as f:
                saved_hash = f.read().strip()
            return hmac.compare_digest(self.hash_password(password), saved_hash)
        except:
            return False

    def check_password_setup(self):
        """Check if password is set up, if not prompt for setup"""
        if not self.password_file.exists():
            # First time setup
            dialog = PasswordDialog(self.root, title="Setup Password", is_setup=True)
            password = dialog.show()

            if not password:
                messagebox.showerror("Error", "Password is required to use this application!")
                self.root.destroy()
                sys.exit(0)

            self.save_password(password)
            messagebox.showinfo("Success", "Password saved successfully!\n\nRemember your password - you'll need it to access the application.")
        else:
            # Ask for password
            max_attempts = 3
            for attempt in range(max_attempts):
                dialog = PasswordDialog(self.root, title="Enter Password")
                password = dialog.show()

                if password is None:
                    # User cancelled
                    self.root.destroy()
                    sys.exit(0)

                if self.verify_password(password):
                    return True
                else:
                    remaining = max_attempts - attempt - 1
                    if remaining > 0:
                        messagebox.showerror("Error", f"Incorrect password!\n\n{remaining} attempts remaining")
                    else:
                        messagebox.showerror("Error", "Maximum attempts exceeded!\n\nApplication will close.")
                        self.root.destroy()
                        sys.exit(0)

    def lock_application(self):
        """Lock the application with overlay"""
        if self.is_locked:
            return

        self.is_locked = True

        # Create full-screen overlay
        self.lock_overlay = tk.Toplevel(self.root)
        self.lock_overlay.title("Locked")
        self.lock_overlay.attributes('-fullscreen', True)
        self.lock_overlay.attributes('-topmost', True)
        self.lock_overlay.protocol("WM_DELETE_WINDOW", lambda: None)  # Disable close

        # Dark overlay
        bg = '#2c3e50'
        self.lock_overlay.configure(bg=bg)

        # Lock screen content
        lock_frame = tk.Frame(self.lock_overlay, bg=bg)
        lock_frame.place(relx=0.5, rely=0.5, anchor='center')

        tk.Label(
            lock_frame,
            text="🔒",
            font=('Arial', 80),
            bg=bg,
            fg='#ecf0f1'
        ).pack(pady=(0, 20))

        tk.Label(
            lock_frame,
            text="Application Locked",
            font=('Arial', 24, 'bold'),
            bg=bg,
            fg='#ecf0f1'
        ).pack(pady=(0, 10))

        tk.Label(
            lock_frame,
            text="Click below to unlock",
            font=('Arial', 12),
            bg=bg,
            fg='#95a5a6'
        ).pack(pady=(0, 30))

        tk.Button(
            lock_frame,
            text="🔓 Unlock",
            command=self.unlock_application,
            font=('Arial', 14, 'bold'),
            bg='#3498db',
            fg='white',
            relief=tk.FLAT,
            cursor='hand2',
            padx=40,
            pady=15
        ).pack()

    def unlock_application(self):
        """Unlock the application"""
        dialog = PasswordDialog(self.root, title="Unlock Application")
        password = dialog.show()

        if password and self.verify_password(password):
            self.is_locked = False
            if self.lock_overlay:
                self.lock_overlay.destroy()
                self.lock_overlay = None
            messagebox.showinfo("Success", "Application unlocked!")
        else:
            if password is not None:  # User didn't cancel
                messagebox.showerror("Error", "Incorrect password!")

    def save_config(self):
        """Save ONLY main configuration (not channels)"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
            self.log("💾 Settings saved", 'success')
        except Exception as e:
            self.log(f"❌ Save config failed: {e}", 'error')

    def save_channels(self):
        """Save ONLY channels configuration"""
        try:
            with open(self.channels_file, 'w', encoding='utf-8') as f:
                json.dump(self.channels_config, f, indent=2)
            self.log(f"💾 Channels saved ({len(self.channels_config)} channels)", 'success')
        except Exception as e:
            self.log(f"❌ Save channels failed: {e}", 'error')

    def initialize_backend(self):
        """Initialize backend uploader in background thread"""
        if self.is_loading:
            self.log("⚠️  Backend already initializing...", 'warning')
            return

        self.is_loading = True
        self.status_label.config(text="● Loading...", fg='#f39c12')

        def init_thread():
            try:
                self.log("🔧 Initializing backend...", 'info')

                if not TikTokUploader:
                    self.log("❌ Backend not loaded!", 'error')
                    self.root.after(0, lambda: messagebox.showerror("Error", "Backend class not loaded!\n\nMake sure tiktok_youtube_uploader.py is in the same folder."))
                    self.is_loading = False
                    self.root.after(0, lambda: self.status_label.config(text="● Error", fg='#e74c3c'))
                    return

                self.uploader = TikTokUploader()
                self.uploader.credentials_folder = Path(self.config['credentials_folder'])
                # Robust spreadsheet-ID extraction (handles '/d/', trailing '/edit', '?usp=...', bare IDs)
                spreadsheet_url = str(self.config.get('spreadsheet_url', '')).strip()
                self.uploader.spreadsheet_url = spreadsheet_url
                if '/d/' in spreadsheet_url:
                    spreadsheet_id = spreadsheet_url.split('/d/', 1)[1].split('/')[0].split('?')[0].split('#')[0]
                else:
                    spreadsheet_id = spreadsheet_url
                self.uploader.spreadsheet_id = spreadsheet_id
                self.uploader.channels = self.channels_config
                self.uploader.schedule_gap_min_hours = self.config['schedule_gap_min_hours']
                self.uploader.schedule_gap_max_hours = self.config['schedule_gap_max_hours']
                self.uploader.schedule_gap_random_minutes = self.config['schedule_gap_random_minutes']
                self.uploader.channel_interval_minutes = self.config['channel_interval_minutes']
                self.uploader.fetch_hours_limit = self.config.get('fetch_hours_limit', 72)

                # Reinitialize sheets client with new config (this is slow!)
                self.uploader.init_sheets_client()

                self.log(f"✅ Backend initialized", 'success')
                self.log(f"📺 {len(self.uploader.channels)} channels loaded", 'info')

                # Update UI on main thread
                self.root.after(0, lambda: self.status_label.config(text="● Ready", fg='#2ecc71'))

                # Refresh data in background
                self.root.after(100, self.refresh_all_data)

            except Exception as e:
                self.log(f"❌ Backend init failed: {e}", 'error')
                import traceback
                self.log(traceback.format_exc(), 'error')
                self.root.after(0, lambda: self.status_label.config(text="● Error", fg='#e74c3c'))
            finally:
                self.is_loading = False

        # Run in background thread
        threading.Thread(target=init_thread, daemon=True).start()

    def build_gui(self):
        """Build main interface"""
        # Set minimum window size for proper responsiveness
        self.root.minsize(1200, 700)

        # Header
        header = tk.Frame(self.root, bg=self.header_bg, height=70)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header, text="🎬 TikTok → YouTube Auto Uploader",
            font=('Arial', 20, 'bold'), bg=self.header_bg, fg='white'
        ).pack(side=tk.LEFT, padx=30, pady=20)

        # Lock button
        tk.Button(
            header,
            text="🔒 Lock",
            command=self.lock_application,
            font=('Arial', 11, 'bold'),
            bg='#e74c3c',
            fg='white',
            relief=tk.FLAT,
            cursor='hand2',
            padx=15,
            pady=8
        ).pack(side=tk.RIGHT, padx=(0, 10))

        self.status_label = tk.Label(
            header, text="● Stopped", font=('Arial', 12),
            bg=self.header_bg, fg='#f39c12'
        )
        self.status_label.pack(side=tk.RIGHT, padx=20)

        # Main content with PanedWindow for resizable split
        main = tk.Frame(self.root, bg=self.bg)
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Create PanedWindow for resizable left/right split
        self.paned = tk.PanedWindow(main, orient=tk.HORIZONTAL, bg=self.bg,
                               sashwidth=8, sashrelief=tk.RAISED,
                               bd=0, showhandle=True, handlesize=10,
                               sashpad=2, relief=tk.FLAT)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Left pane
        left = tk.Frame(self.paned, bg=self.bg)
        self.paned.add(left, minsize=400, stretch="always")

        # Right pane - WITH SCROLLBAR
        right_wrapper = tk.Frame(self.paned, bg=self.bg)
        self.paned.add(right_wrapper, minsize=600, stretch="always")

        # Create canvas and scrollbar for right side
        right_canvas = tk.Canvas(right_wrapper, bg=self.bg, highlightthickness=0)
        right_scrollbar = ttk.Scrollbar(right_wrapper, orient=tk.VERTICAL, command=right_canvas.yview)
        right = tk.Frame(right_canvas, bg=self.bg)

        # Store reference for width updates
        self.right_canvas = right_canvas
        self.right_content = right

        def _update_right_width(e):
            # Update scroll region
            right_canvas.configure(scrollregion=right_canvas.bbox("all"))
            # Update canvas window width to match canvas width
            canvas_width = right_canvas.winfo_width()
            if canvas_width > 1:
                right_canvas.itemconfig(right_canvas.find_withtag("all")[0], width=canvas_width)

        right.bind("<Configure>", _update_right_width)
        right_canvas.bind("<Configure>", _update_right_width)

        right_canvas.create_window((0, 0), window=right, anchor="nw")
        right_canvas.configure(yscrollcommand=right_scrollbar.set)

        right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Enable mouse wheel scrolling for right pane
        def _on_mousewheel_right(event):
            right_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        right_canvas.bind("<Enter>", lambda e: right_canvas.bind_all("<MouseWheel>", _on_mousewheel_right))
        right_canvas.bind("<Leave>", lambda e: right_canvas.unbind_all("<MouseWheel>"))

        # Build sections
        # Top row: Stats and Live Monitor side by side
        top_row = tk.Frame(left, bg=self.bg)
        top_row.pack(fill=tk.X, pady=(0, 8), padx=5)

        stats_col = tk.Frame(top_row, bg=self.bg)
        stats_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        monitor_col = tk.Frame(top_row, bg=self.bg)
        monitor_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        self.build_stats(stats_col)
        self.build_live_monitor(monitor_col)

        # Add padding frame for left content WITH SCROLLBAR
        left_wrapper = tk.Frame(left, bg=self.bg)
        left_wrapper.pack(fill=tk.BOTH, expand=True, padx=5)

        # Create canvas and scrollbar for left side
        left_canvas = tk.Canvas(left_wrapper, bg=self.bg, highlightthickness=0)
        left_scrollbar = ttk.Scrollbar(left_wrapper, orient=tk.VERTICAL, command=left_canvas.yview)
        left_content = tk.Frame(left_canvas, bg=self.bg)

        # Store reference for width updates
        self.left_canvas = left_canvas
        self.left_content = left_content

        def _update_left_width(e):
            # Update scroll region
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
            # Update canvas window width to match canvas width
            canvas_width = left_canvas.winfo_width()
            if canvas_width > 1:
                left_canvas.itemconfig(left_canvas.find_withtag("all")[0], width=canvas_width)

        left_content.bind("<Configure>", _update_left_width)
        left_canvas.bind("<Configure>", _update_left_width)

        left_canvas.create_window((0, 0), window=left_content, anchor="nw")
        left_canvas.configure(yscrollcommand=left_scrollbar.set)

        left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Enable mouse wheel scrolling for left pane
        def _on_mousewheel_left(event):
            left_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        left_canvas.bind("<Enter>", lambda e: left_canvas.bind_all("<MouseWheel>", _on_mousewheel_left))
        left_canvas.bind("<Leave>", lambda e: left_canvas.unbind_all("<MouseWheel>"))

        self.build_controls(left_content)
        self.build_settings(left_content)
        self.build_channels(right)
        self.build_log(right)

        # Bind window resize to adjust paned window sash position proportionally
        self.root.bind("<Configure>", self._on_window_resize)
        self._last_width = self.root.winfo_width()

    def build_stats(self, parent):
        """System status section"""
        card = tk.Frame(parent, bg=self.card_bg, relief=tk.RAISED, bd=1)
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            card, text="📊 System Status", font=('Arial', 10, 'bold'),
            bg=self.card_bg, fg=self.text
        ).pack(anchor=tk.W, padx=10, pady=(8, 6))

        stats_frame = tk.Frame(card, bg=self.card_bg)
        stats_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        stats = [
            ('📺', 'Channels', '0', self.accent),
            ('🎥', 'Videos', '0', self.success),
            ('✅', 'Uploaded', '0', self.warning),
            ('🔐', 'Tokens', 'Healthy', self.success)
        ]

        self.stat_labels = {}

        # Create 2x2 grid
        for idx, (icon, label, value, color) in enumerate(stats):
            row = idx // 2
            col = idx % 2

            frame = tk.Frame(stats_frame, bg='#f8f9fa', relief=tk.SOLID, bd=1)
            frame.grid(row=row, column=col, sticky='nsew', padx=2, pady=2)

            inner = tk.Frame(frame, bg='#f8f9fa')
            inner.pack(fill=tk.X, padx=6, pady=4)

            tk.Label(inner, text=icon, font=('Arial', 14), bg='#f8f9fa').pack(side=tk.LEFT, padx=(0, 6))

            text_frame = tk.Frame(inner, bg='#f8f9fa')
            text_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

            val_lbl = tk.Label(text_frame, text=value, font=('Arial', 11, 'bold'), bg='#f8f9fa', fg=color, anchor=tk.W)
            val_lbl.pack(fill=tk.X)
            tk.Label(text_frame, text=label, font=('Arial', 8), bg='#f8f9fa', fg=self.text_light, anchor=tk.W).pack(fill=tk.X)

            self.stat_labels[label] = val_lbl

        # Configure grid weights
        stats_frame.grid_rowconfigure(0, weight=1)
        stats_frame.grid_rowconfigure(1, weight=1)
        stats_frame.grid_columnconfigure(0, weight=1)
        stats_frame.grid_columnconfigure(1, weight=1)

    def build_live_monitor(self, parent):
        """Live Monitor - Auto-Check section"""
        card = tk.Frame(parent, bg=self.card_bg, relief=tk.RAISED, bd=1)
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            card, text="🔍 Live Monitor",
            font=('Arial', 10, 'bold'), bg=self.card_bg, fg=self.text
        ).pack(anchor=tk.W, padx=10, pady=(8, 6))

        # Status and stats in compact layout
        stats_frame = tk.Frame(card, bg='#f0f0f0', relief=tk.GROOVE, bd=1)
        stats_frame.pack(fill=tk.X, padx=10, pady=(0, 6))

        stats_inner = tk.Frame(stats_frame, bg='#f0f0f0')
        stats_inner.pack(fill=tk.X, padx=6, pady=4)

        # Status
        self.monitor_status_label = tk.Label(
            stats_inner, text="● Stopped", font=('Arial', 9, 'bold'),
            bg='#f0f0f0', fg=self.warning
        )
        self.monitor_status_label.pack(side=tk.LEFT, padx=(0, 15))

        # Checks
        tk.Label(stats_inner, text="Checks: ", font=('Arial', 8), bg='#f0f0f0', fg='#666').pack(side=tk.LEFT)
        self.monitor_checks_label = tk.Label(
            stats_inner, text="0", font=('Arial', 9, 'bold'), bg='#f0f0f0', fg=self.text
        )
        self.monitor_checks_label.pack(side=tk.LEFT, padx=(0, 12))

        # Found
        tk.Label(stats_inner, text="Found: ", font=('Arial', 8), bg='#f0f0f0', fg='#666').pack(side=tk.LEFT)
        self.monitor_found_label = tk.Label(
            stats_inner, text="0", font=('Arial', 9, 'bold'), bg='#f0f0f0', fg=self.text
        )
        self.monitor_found_label.pack(side=tk.LEFT, padx=(0, 12))

        # Uploaded
        tk.Label(stats_inner, text="Uploaded: ", font=('Arial', 8), bg='#f0f0f0', fg='#666').pack(side=tk.LEFT)
        self.monitor_uploaded_label = tk.Label(
            stats_inner, text="0", font=('Arial', 9, 'bold'), bg='#f0f0f0', fg=self.success
        )
        self.monitor_uploaded_label.pack(side=tk.LEFT)

        # Interval setting - compact
        interval_frame = tk.Frame(card, bg=self.card_bg)
        interval_frame.pack(fill=tk.X, padx=10, pady=(0, 6))

        tk.Label(
            interval_frame, text="Interval:",
            font=('Arial', 9), bg=self.card_bg, fg=self.text
        ).pack(side=tk.LEFT, padx=(0, 5))

        self.monitor_interval_var = tk.StringVar(value="2")
        tk.Entry(
            interval_frame, textvariable=self.monitor_interval_var,
            font=('Arial', 9), width=4, relief=tk.SOLID, bd=1
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Label(
            interval_frame, text="min",
            font=('Arial', 9), bg=self.card_bg, fg=self.text_light
        ).pack(side=tk.LEFT)

        # Control buttons - compact
        monitor_btn_frame = tk.Frame(card, bg=self.card_bg)
        monitor_btn_frame.pack(fill=tk.X, padx=10, pady=(0, 8))

        self.btn_monitor_start = tk.Button(
            monitor_btn_frame, text="● Start Auto-Check",
            command=self.toggle_live_monitor, font=('Arial', 9, 'bold'),
            bg=self.success, fg='white', relief=tk.FLAT, cursor='hand2', pady=6
        )
        self.btn_monitor_start.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))

        self.btn_monitor_stop = tk.Button(
            monitor_btn_frame, text="● Stop Auto-Check",
            command=self.toggle_live_monitor, font=('Arial', 9, 'bold'),
            bg=self.error, fg='white', relief=tk.FLAT, cursor='hand2',
            pady=6, state=tk.DISABLED
        )
        self.btn_monitor_stop.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        # Manual check button
        manual_btn_frame = tk.Frame(card, bg=self.card_bg)
        manual_btn_frame.pack(fill=tk.X, padx=10, pady=(0, 8))

        tk.Button(
            manual_btn_frame, text="🔎 Check Selected Channels",
            command=self.manual_check_selected, font=('Arial', 9, 'bold'),
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2', pady=5
        ).pack(fill=tk.X)

        # Initialize update thread
        self.monitor_update_thread = None
        self.start_monitor_stats_update()

    def build_controls(self, parent):
        """Upload controls section"""
        card = tk.Frame(parent, bg=self.card_bg, relief=tk.RAISED, bd=1)
        card.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            card, text="🚀 Upload Controls", font=('Arial', 11, 'bold'),
            bg=self.card_bg, fg=self.text
        ).pack(anchor=tk.W, padx=15, pady=(8, 5))

        # Upload Interval Setting
        interval_setting = tk.Frame(card, bg='#e8f4f8', relief=tk.SOLID, bd=1)
        interval_setting.pack(fill=tk.X, padx=15, pady=(0, 5))

        tk.Label(
            interval_setting, text="⏱️ Upload Interval:", font=('Arial', 9, 'bold'),
            bg='#e8f4f8', fg=self.text
        ).pack(side=tk.LEFT, padx=(8, 5), pady=5)

        self.interval_var = tk.StringVar(value=str(self.config.get('channel_interval_minutes', 2)))
        interval_spinbox = tk.Spinbox(
            interval_setting, from_=0, to=60, textvariable=self.interval_var,
            font=('Arial', 9), width=5, relief=tk.SOLID, bd=1
        )
        interval_spinbox.pack(side=tk.LEFT, padx=5)

        tk.Label(
            interval_setting, text="minutes between uploads", font=('Arial', 9),
            bg='#e8f4f8', fg=self.text
        ).pack(side=tk.LEFT, padx=(0, 10))

        tk.Button(
            interval_setting, text="💾", command=self.save_interval,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 8, 'bold'), width=3
        ).pack(side=tk.LEFT, padx=(5, 10))

        # TikTok Time Filter Setting
        time_filter_setting = tk.Frame(card, bg='#e8f8f8', relief=tk.SOLID, bd=1)
        time_filter_setting.pack(fill=tk.X, padx=15, pady=(0, 5))

        filter_controls = tk.Frame(time_filter_setting, bg='#e8f8f8')
        filter_controls.pack(fill=tk.X, padx=8, pady=5)

        tk.Label(
            filter_controls, text="🕐 Fetch last:", font=('Arial', 9, 'bold'),
            bg='#e8f8f8', fg=self.text
        ).pack(side=tk.LEFT, padx=(0, 5))

        self.fetch_hours_var = tk.StringVar(value=str(self.config.get('fetch_hours_limit', 72)))
        fetch_spinbox = tk.Spinbox(
            filter_controls, from_=0, to=8760, textvariable=self.fetch_hours_var,
            font=('Arial', 9), width=6, relief=tk.SOLID, bd=1
        )
        fetch_spinbox.pack(side=tk.LEFT, padx=5)

        tk.Label(
            filter_controls, text="hrs (0=All)", font=('Arial', 9),
            bg='#e8f8f8', fg=self.text
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(
            filter_controls, text="💾", command=self.save_time_filter,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 8, 'bold'), width=3
        ).pack(side=tk.LEFT, padx=(5, 5))

        # Quick preset buttons - inline
        tk.Label(
            filter_controls, text="Presets:", font=('Arial', 8),
            bg='#e8f8f8', fg=self.text_light
        ).pack(side=tk.LEFT, padx=(10, 3))

        presets = [
            ("24h", 24, "Last day"),
            ("72h", 72, "Last 3 days"),
            ("1w", 168, "Last week"),
            ("2w", 336, "Last 2 weeks"),
            ("1m", 720, "Last month (30 days)"),
            ("3m", 2160, "Last 3 months (90 days)"),
            ("6m", 4320, "Last 6 months (180 days)"),
            ("1y", 8760, "Last year (365 days)"),
            ("All", 999999, "All time (entire channel history)")
        ]

        for label, hours, tooltip in presets:
            btn = tk.Button(
                filter_controls, text=label,
                command=lambda h=hours: self.set_time_filter_preset(h),
                bg='#d0e8f0', fg=self.text, relief=tk.FLAT, cursor='hand2',
                font=('Arial', 7), padx=4, pady=1
            )
            btn.pack(side=tk.LEFT, padx=1)

        # Schedule Gap Setting
        schedule_setting = tk.Frame(card, bg='#fff4e6', relief=tk.SOLID, bd=1)
        schedule_setting.pack(fill=tk.X, padx=15, pady=(0, 5))

        gap_controls = tk.Frame(schedule_setting, bg='#fff4e6')
        gap_controls.pack(fill=tk.X, padx=8, pady=5)

        # Min hours
        tk.Label(gap_controls, text="📅 Gap:", font=('Arial', 9, 'bold'), bg='#fff4e6', fg=self.text).pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(gap_controls, text="Min:", font=('Arial', 9), bg='#fff4e6', fg=self.text).pack(side=tk.LEFT, padx=(0, 3))
        self.min_hours_var = tk.StringVar(value=str(self.config.get('schedule_gap_min_hours', 2)))
        tk.Spinbox(
            gap_controls, from_=1, to=10, textvariable=self.min_hours_var,
            font=('Arial', 9), width=3, relief=tk.SOLID, bd=1
        ).pack(side=tk.LEFT, padx=2)
        tk.Label(gap_controls, text="h", font=('Arial', 9), bg='#fff4e6', fg=self.text).pack(side=tk.LEFT, padx=(2, 8))

        # Max hours
        tk.Label(gap_controls, text="Max:", font=('Arial', 9), bg='#fff4e6', fg=self.text).pack(side=tk.LEFT, padx=(0, 3))
        self.max_hours_var = tk.StringVar(value=str(self.config.get('schedule_gap_max_hours', 3)))
        tk.Spinbox(
            gap_controls, from_=1, to=10, textvariable=self.max_hours_var,
            font=('Arial', 9), width=3, relief=tk.SOLID, bd=1
        ).pack(side=tk.LEFT, padx=2)
        tk.Label(gap_controls, text="h", font=('Arial', 9), bg='#fff4e6', fg=self.text).pack(side=tk.LEFT, padx=(2, 8))

        # Randomization
        tk.Label(gap_controls, text="±", font=('Arial', 9), bg='#fff4e6', fg=self.text).pack(side=tk.LEFT, padx=(0, 3))
        self.random_minutes_var = tk.StringVar(value=str(self.config.get('schedule_gap_random_minutes', 40)))
        tk.Spinbox(
            gap_controls, from_=0, to=120, textvariable=self.random_minutes_var,
            font=('Arial', 9), width=3, relief=tk.SOLID, bd=1
        ).pack(side=tk.LEFT, padx=2)
        tk.Label(gap_controls, text="m", font=('Arial', 9), bg='#fff4e6', fg=self.text).pack(side=tk.LEFT, padx=(2, 5))

        tk.Button(
            gap_controls, text="💾", command=self.save_schedule_gap,
            bg=self.warning, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 8, 'bold'), width=3
        ).pack(side=tk.LEFT, padx=(5, 0))

        # Phase Selection
        phase_setting = tk.Frame(card, bg='#f0f8ff', relief=tk.SOLID, bd=1)
        phase_setting.pack(fill=tk.X, padx=15, pady=(5, 5))

        phase_label_frame = tk.Frame(phase_setting, bg='#f0f8ff')
        phase_label_frame.pack(fill=tk.X, padx=8, pady=(5, 3))

        tk.Label(
            phase_label_frame, text="📋 Phase Selection:", font=('Arial', 9, 'bold'),
            bg='#f0f8ff', fg=self.text
        ).pack(side=tk.LEFT)

        phase_buttons_frame = tk.Frame(phase_setting, bg='#f0f8ff')
        phase_buttons_frame.pack(fill=tk.X, padx=8, pady=(0, 5))

        self.phase_mode = tk.StringVar(value="phase2")  # both, phase1, phase2 — default to upload phase

        phases = [
            ("Both (Phase 1 + Phase 2)", "both", "Run both phases"),
            ("Phase 1 Only (Fetch → Sheet)", "phase1", "Only fetch new videos to sheet"),
            ("Phase 2 Only (Sheet → Upload)", "phase2", "Only upload from sheet")
        ]

        for label, value, tooltip in phases:
            rb = tk.Radiobutton(
                phase_buttons_frame, text=label, variable=self.phase_mode,
                value=value, bg='#f0f8ff', fg=self.text, font=('Arial', 8),
                activebackground='#f0f8ff', selectcolor='#3498db', cursor='hand2'
            )
            rb.pack(anchor=tk.W, pady=1)

        # Control buttons
        btn_frame = tk.Frame(card, bg=self.card_bg)
        btn_frame.pack(fill=tk.X, padx=15, pady=(5, 8))

        self.btn_start = tk.Button(
            btn_frame, text="▶️  Start Automation",
            command=self.start_automation, font=('Arial', 10, 'bold'),
            bg=self.success, fg='white', relief=tk.FLAT, cursor='hand2'
        )
        self.btn_start.pack(fill=tk.X, pady=2)

        self.btn_stop = tk.Button(
            btn_frame, text="⏸️  Stop Automation",
            command=self.stop_automation, font=('Arial', 10, 'bold'),
            bg='#95a5a6', fg='white', relief=tk.FLAT, cursor='hand2',
            state=tk.DISABLED
        )
        self.btn_stop.pack(fill=tk.X, pady=2)

        tk.Button(
            btn_frame, text="📤 Process Selected Channels",
            command=self.process_selected_channels, font=('Arial', 10, 'bold'),
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2'
        ).pack(fill=tk.X, pady=2)

        tk.Button(
            btn_frame, text="🔄 Refresh Stats",
            command=self.refresh_all_data, font=('Arial', 10, 'bold'),
            bg=self.warning, fg='white', relief=tk.FLAT, cursor='hand2'
        ).pack(fill=tk.X, pady=2)

    def build_settings(self, parent):
        """Folder and settings section"""
        card = tk.Frame(parent, bg=self.card_bg, relief=tk.RAISED, bd=1)
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            card, text="⚙️ Settings", font=('Arial', 10, 'bold'),
            bg=self.card_bg, fg=self.text
        ).pack(anchor=tk.W, padx=15, pady=(10, 8))

        settings_frame = tk.Frame(card, bg=self.card_bg)
        settings_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        # Credentials Folder
        tk.Label(
            settings_frame, text="Credentials Folder:", font=('Arial', 9, 'bold'),
            bg=self.card_bg, fg=self.text, anchor=tk.W
        ).grid(row=0, column=0, sticky=tk.W, pady=(5, 2), columnspan=2)

        self.creds_entry = tk.Entry(settings_frame, font=('Arial', 9), relief=tk.SOLID, bd=1)
        self.creds_entry.insert(0, self.config.get('credentials_folder', ''))
        self.creds_entry.grid(row=1, column=0, sticky='ew', pady=(0, 8), padx=(0, 5))

        tk.Button(
            settings_frame, text="📂", command=self.browse_credentials,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 9), width=4
        ).grid(row=1, column=1, pady=(0, 8))

        # Spreadsheet URL
        tk.Label(
            settings_frame, text="Google Sheets URL:", font=('Arial', 9, 'bold'),
            bg=self.card_bg, fg=self.text, anchor=tk.W
        ).grid(row=2, column=0, sticky=tk.W, pady=(5, 2), columnspan=2)

        self.sheets_entry = tk.Entry(settings_frame, font=('Arial', 9), relief=tk.SOLID, bd=1)
        self.sheets_entry.insert(0, self.config.get('spreadsheet_url', ''))
        self.sheets_entry.grid(row=3, column=0, sticky='ew', pady=(0, 8), columnspan=2)

        settings_frame.columnconfigure(0, weight=1)

        # Save button
        tk.Button(
            settings_frame, text="💾 Save Settings & Reload",
            command=self.save_settings, font=('Arial', 10, 'bold'),
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2'
        ).grid(row=4, column=0, columnspan=2, sticky='ew', pady=(8, 0))

        # Add spacer to push settings content up but allow expansion
        spacer = tk.Frame(settings_frame, bg=self.card_bg)
        spacer.grid(row=5, column=0, columnspan=2, sticky='nsew')
        settings_frame.rowconfigure(5, weight=1)

    def build_channels(self, parent):
        """Channel management section"""
        card = tk.Frame(parent, bg=self.card_bg, relief=tk.RAISED, bd=1)
        card.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        tk.Label(
            card, text="📺 Channel Management", font=('Arial', 12, 'bold'),
            bg=self.card_bg, fg=self.text
        ).pack(anchor=tk.W, padx=20, pady=(15, 10))

        tree_frame = tk.Frame(card, bg=self.card_bg)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))

        cols = ('Status', 'Channel', 'Token Age', 'Last Upload')
        self.tree = ttk.Treeview(tree_frame, columns=cols, show='headings', height=10)

        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Channel management buttons
        btn_frame = tk.Frame(card, bg=self.card_bg)
        btn_frame.pack(fill=tk.X, padx=20, pady=(0, 15))

        tk.Button(
            btn_frame, text="🔄 Scan Credentials Folder",
            command=self.scan_credentials, bg=self.accent, fg='white',
            relief=tk.FLAT, cursor='hand2', font=('Arial', 9, 'bold'), padx=15, pady=8
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(
            btn_frame, text="➕ Add New Channel",
            command=self.add_new_channel, bg=self.success, fg='white',
            relief=tk.FLAT, cursor='hand2', font=('Arial', 9, 'bold'), padx=15, pady=8
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(
            btn_frame, text="✏️ Edit Channel",
            command=self.edit_channel, bg='#f39c12', fg='white',
            relief=tk.FLAT, cursor='hand2', font=('Arial', 9, 'bold'), padx=15, pady=8
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(
            btn_frame, text="🔐 Re-authenticate",
            command=self.reauthenticate_channel, bg='#9b59b6', fg='white',
            relief=tk.FLAT, cursor='hand2', font=('Arial', 9, 'bold'), padx=15, pady=8
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(
            btn_frame, text="🗑️ Delete Channel",
            command=self.delete_channel, bg=self.error, fg='white',
            relief=tk.FLAT, cursor='hand2', font=('Arial', 9, 'bold'), padx=15, pady=8
        ).pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(
            btn_frame, text="🔄 Update yt-dlp",
            command=self.update_ytdlp, bg='#3498db', fg='white',
            relief=tk.FLAT, cursor='hand2', font=('Arial', 9, 'bold'), padx=15, pady=8
        ).pack(side=tk.LEFT)

    def build_log(self, parent):
        """Activity log section"""
        card = tk.Frame(parent, bg=self.card_bg, relief=tk.RAISED, bd=1)
        card.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(card, bg=self.card_bg)
        header.pack(fill=tk.X, padx=20, pady=(15, 10))

        tk.Label(
            header, text="📋 Activity Log", font=('Arial', 12, 'bold'),
            bg=self.card_bg, fg=self.text
        ).pack(side=tk.LEFT)

        tk.Button(
            header, text="🗑️", command=self.clear_log,
            bg='#f8f9fa', fg=self.text, relief=tk.FLAT, cursor='hand2',
            font=('Arial', 9), width=3
        ).pack(side=tk.RIGHT, padx=(5, 0))

        tk.Button(
            header, text="⛶", command=self.toggle_log_fullscreen,
            bg='#f8f9fa', fg=self.text, relief=tk.FLAT, cursor='hand2',
            font=('Arial', 12, 'bold'), width=3
        ).pack(side=tk.RIGHT)

        log_frame = tk.Frame(card, bg=self.card_bg)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 15))

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, font=('Consolas', 9),
            bg='#1e1e1e', fg='#d4d4d4', relief=tk.FLAT, padx=10, pady=10
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.log_text.tag_config('success', foreground='#4ec9b0')
        self.log_text.tag_config('error', foreground='#f48771')
        self.log_text.tag_config('warning', foreground='#dcdcaa')
        self.log_text.tag_config('info', foreground='#9cdcfe')
        self.log_text.tag_config('green', foreground='#00ff00')  # Bright green for highlights
        self.log_text.tag_config('red', foreground='#ff0000')  # Bright red for errors
        self.log_text.tag_config('yellow', foreground='#ffff00')  # Bright yellow for quota warnings

    def log(self, message: str, level: str = 'info'):
        """Add log message"""
        self.log_queue.put((message, level))

    def process_logs(self):
        """Process log queue"""
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                timestamp = datetime.now().strftime('%H:%M:%S')

                # Parse ANSI color codes and apply appropriate tags
                import re

                # Insert timestamp
                self.log_text.insert(tk.END, f"[{timestamp}] ", level)

                # Parse green, red, and yellow ANSI codes
                # Pattern matches: \033[92m....\033[0m (green), \033[91m....\033[0m (red), \033[93m....\033[0m (yellow)
                ansi_pattern = r'\033\[(91|92|93)m(.*?)\033\[0m'

                last_end = 0
                for match in re.finditer(ansi_pattern, message):
                    # Insert text before the colored part
                    if match.start() > last_end:
                        self.log_text.insert(tk.END, message[last_end:match.start()], level)

                    # Insert colored text with appropriate tag
                    color_code = match.group(1)
                    colored_text = match.group(2)

                    if color_code == '92':  # Green
                        self.log_text.insert(tk.END, colored_text, 'green')
                    elif color_code == '91':  # Red
                        self.log_text.insert(tk.END, colored_text, 'red')
                    elif color_code == '93':  # Yellow
                        self.log_text.insert(tk.END, colored_text, 'yellow')

                    last_end = match.end()

                # Insert remaining text
                if last_end < len(message):
                    self.log_text.insert(tk.END, message[last_end:], level)

                self.log_text.insert(tk.END, "\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass

        self.root.after(100, self.process_logs)

    def clear_log(self):
        """Clear log"""
        self.log_text.delete(1.0, tk.END)
        self.log("📋 Log cleared", 'info')

    def _on_window_resize(self, event):
        """Handle window resize to maintain responsive layout"""
        # Only process resize events from the root window
        if event.widget != self.root:
            return

        # Maintain proportional sash position on window resize
        try:
            current_width = self.root.winfo_width()
            if hasattr(self, '_last_width') and self._last_width > 0 and current_width != self._last_width:
                # Get current sash position
                try:
                    sash_pos = self.paned.sash_coord(0)[0]
                    # Calculate proportion
                    proportion = sash_pos / self._last_width if self._last_width > 0 else 0.4
                    # Set new position based on proportion
                    new_pos = int(current_width * proportion)
                    # Ensure it respects minsize constraints
                    if new_pos >= 400 and (current_width - new_pos) >= 600:
                        self.paned.sash_place(0, new_pos, 0)
                except:
                    pass
                self._last_width = current_width
        except:
            pass

    def toggle_log_fullscreen(self):
        """Toggle fullscreen view for Activity Log"""
        # Create fullscreen window
        fullscreen_window = tk.Toplevel(self.root)
        fullscreen_window.title("Activity Log - Fullscreen")
        fullscreen_window.geometry("1200x800")
        fullscreen_window.configure(bg=self.bg)

        # Header with title and close button
        header = tk.Frame(fullscreen_window, bg=self.card_bg, relief=tk.RAISED, bd=1)
        header.pack(fill=tk.X, padx=10, pady=10)

        tk.Label(
            header, text="📋 Activity Log - Fullscreen View",
            font=('Arial', 14, 'bold'), bg=self.card_bg, fg=self.text
        ).pack(side=tk.LEFT, padx=20, pady=10)

        tk.Button(
            header, text="✕ Close", command=fullscreen_window.destroy,
            bg=self.error, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 10, 'bold'), padx=15, pady=5
        ).pack(side=tk.RIGHT, padx=20, pady=10)

        tk.Button(
            header, text="🗑️ Clear", command=self.clear_log,
            bg=self.warning, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 10, 'bold'), padx=15, pady=5
        ).pack(side=tk.RIGHT, padx=5, pady=10)

        # Log text area (synchronized with main log)
        log_frame = tk.Frame(fullscreen_window, bg=self.card_bg, relief=tk.RAISED, bd=1)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        fullscreen_log = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, font=('Consolas', 10),
            bg='#1e1e1e', fg='#d4d4d4', relief=tk.FLAT, padx=15, pady=15
        )
        fullscreen_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Configure color tags
        fullscreen_log.tag_config('success', foreground='#4ec9b0')
        fullscreen_log.tag_config('error', foreground='#f48771')
        fullscreen_log.tag_config('warning', foreground='#dcdcaa')
        fullscreen_log.tag_config('info', foreground='#9cdcfe')

        # Copy current log content
        current_content = self.log_text.get(1.0, tk.END)
        fullscreen_log.insert(1.0, current_content)
        fullscreen_log.see(tk.END)  # Auto-scroll to bottom

        # Auto-update function to sync with main log
        def update_fullscreen_log():
            if fullscreen_window.winfo_exists():
                try:
                    # Get current content from main log
                    new_content = self.log_text.get(1.0, tk.END)
                    # Only update if content changed
                    if fullscreen_log.get(1.0, tk.END) != new_content:
                        fullscreen_log.delete(1.0, tk.END)
                        fullscreen_log.insert(1.0, new_content)
                        fullscreen_log.see(tk.END)  # Auto-scroll to bottom
                    # Schedule next update
                    fullscreen_window.after(500, update_fullscreen_log)
                except:
                    pass

        # Start auto-update
        update_fullscreen_log()

        # Make window stay on top (optional)
        fullscreen_window.attributes('-topmost', False)

    def browse_credentials(self):
        """Browse for credentials folder"""
        folder = filedialog.askdirectory()
        if folder:
            self.creds_entry.delete(0, tk.END)
            self.creds_entry.insert(0, folder)

    def save_interval(self):
        """Save upload interval"""
        try:
            interval_minutes = int(self.interval_var.get())
            if interval_minutes < 0:
                messagebox.showerror("Error", "Interval cannot be negative")
                return

            self.config['channel_interval_minutes'] = interval_minutes

            if self.uploader:
                self.uploader.channel_interval_minutes = interval_minutes
                if interval_minutes == 0:
                    self.log(f"✅ Upload interval: CONTINUOUS (0 min) - config: {self.config['channel_interval_minutes']}, backend: {self.uploader.channel_interval_minutes}", 'success')
                else:
                    self.log(f"✅ Upload interval: {interval_minutes} min (config: {self.config['channel_interval_minutes']}, backend: {self.uploader.channel_interval_minutes})", 'success')
            else:
                if interval_minutes == 0:
                    self.log(f"✅ Upload interval saved to config: CONTINUOUS (0 minutes)", 'success')
                else:
                    self.log(f"✅ Upload interval saved to config: {interval_minutes} minutes", 'success')

            self.save_config()
            if interval_minutes == 0:
                messagebox.showinfo("Success", "Upload interval set to CONTINUOUS (0 minutes)")
            else:
                messagebox.showinfo("Success", f"Upload interval set to {interval_minutes} minutes")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number")

    def save_time_filter(self):
        """Save TikTok time filter"""
        try:
            fetch_hours = int(self.fetch_hours_var.get())

            if fetch_hours < 0:
                messagebox.showerror("Error", "Hours must be 0 or positive (0 = All videos)")
                return

            self.config['fetch_hours_limit'] = fetch_hours

            if self.uploader:
                self.uploader.fetch_hours_limit = fetch_hours
                if fetch_hours == 0:
                    self.log(f"✅ Time filter updated: Fetch ALL videos from TikTok", 'success')
                else:
                    self.log(f"✅ Time filter updated: Fetch last {fetch_hours} hours", 'success')

            self.save_config()

            if fetch_hours == 0:
                messagebox.showinfo("Success", "Time filter set to fetch ALL videos from channel start!")
            else:
                days = fetch_hours / 24
                if days < 1:
                    messagebox.showinfo("Success", f"Time filter set to last {fetch_hours} hours")
                elif days == 1:
                    messagebox.showinfo("Success", f"Time filter set to last 1 day")
                else:
                    messagebox.showinfo("Success", f"Time filter set to last {days:.1f} days ({fetch_hours} hours)")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number")

    def set_time_filter_preset(self, hours):
        """Set time filter from preset button"""
        self.fetch_hours_var.set(str(hours))
        self.save_time_filter()

    def save_schedule_gap(self):
        """Save schedule gap settings"""
        try:
            min_hours = float(self.min_hours_var.get())
            max_hours = float(self.max_hours_var.get())
            random_minutes = float(self.random_minutes_var.get())

            if min_hours >= max_hours:
                messagebox.showerror("Error", "Min hours must be less than Max hours")
                return

            self.config['schedule_gap_min_hours'] = min_hours
            self.config['schedule_gap_max_hours'] = max_hours
            self.config['schedule_gap_random_minutes'] = random_minutes

            if self.uploader:
                self.uploader.schedule_gap_min_hours = min_hours
                self.uploader.schedule_gap_max_hours = max_hours
                self.uploader.schedule_gap_random_minutes = random_minutes
                self.log(f"✅ Schedule gap updated: {min_hours}-{max_hours} hrs ± {random_minutes} min", 'success')

            self.save_config()
            messagebox.showinfo("Success", f"Schedule gap updated!\n\nVideos will be {min_hours}-{max_hours} hrs apart\nwith ±{random_minutes} min randomization")
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers")

    def save_settings(self):
        """Save all settings and reinitialize backend"""
        self.config['credentials_folder'] = self.creds_entry.get()
        self.config['spreadsheet_url'] = self.sheets_entry.get()

        self.save_config()
        self.log("✅ Settings saved!", 'success')

        # Reinitialize in background
        self.initialize_backend()

        messagebox.showinfo("Success", "Settings saved!\n\nBackend is reinitializing in background...")

    def scan_credentials(self):
        """Scan credentials folder for channels in background"""
        if self.is_loading:
            messagebox.showinfo("Please Wait", "Another operation is in progress...")
            return

        self.is_loading = True
        self.log("🔍 Scanning credentials folder...", 'info')

        def scan_thread():
            try:
                creds_folder = Path(self.config['credentials_folder'])

                # Find all JSON credential files (exclude service_account and state files)
                all_json_files = sorted(creds_folder.glob('*.json'))
                cred_files = [f for f in all_json_files if f.name not in ['service_account.json', 'uploader_state.json']]

                if not cred_files:
                    self.log("⚠️  No credentials found", 'warning')
                    self.root.after(0, lambda: messagebox.showwarning("No Credentials", f"No credential .json files found in:\n{creds_folder}\n\nExcluding: service_account.json, uploader_state.json"))
                    self.is_loading = False
                    return

                # Auto-generate channels config
                new_channels = {}
                for idx, cred_file in enumerate(cred_files, 1):
                    filename = cred_file.stem

                    # Handle different naming formats:
                    # "client_secret_channelname.json" -> "channelname"
                    # "Channel 1 SarahMar LolaSpeak.json" -> "LolaSpeak" (last word)
                    # "kikipinch tammyfab.json" -> "tammyfab" (last word)

                    if filename.startswith('client_secret_'):
                        # Old format: client_secret_channelname
                        name_part = filename.replace('client_secret_', '').replace('channel', '').strip()
                        channel_name = name_part.split('_')[-1] if '_' in name_part else name_part
                    else:
                        # New format: use last word as channel name (most specific identifier)
                        parts = filename.split()
                        channel_name = parts[-1] if parts else filename

                    if not channel_name or channel_name.isdigit():
                        channel_name = f"Channel{idx}"

                    channel_id = f'channel{idx}'
                    new_channels[channel_id] = {
                        'channel_id': channel_id,
                        'channel_name': channel_name.title(),
                        'gmail': f'{channel_name.lower()}@gmail.com',
                        'youtube_channel_id': 'UCxxxxxxxxxxxxxx',
                        'tiktok_username': channel_name.lower(),
                        'credentials_file': cred_file.name,
                        'token_file': f'token_{cred_file.stem}',
                        'sheet_tab_name': channel_name.title(),
                        'sheet_tab_id': str(idx - 1),
                        'enabled': True
                    }

                self.channels_config = new_channels
                self.save_channels()

                self.log(f"✅ Found {len(new_channels)} channels", 'success')
                for ch_id, ch_data in new_channels.items():
                    self.log(f"  • {ch_id}: {ch_data['channel_name']}", 'info')

                # Refresh UI on main thread
                self.root.after(0, self.refresh_channels)
                self.root.after(0, lambda: messagebox.showinfo("Success", f"Scanned and found {len(new_channels)} channels!\n\nPlease edit each channel to set correct details."))

            except Exception as e:
                self.log(f"❌ Scan error: {e}", 'error')
            finally:
                self.is_loading = False

        threading.Thread(target=scan_thread, daemon=True).start()

    def add_new_channel(self):
        """Add new channel dialog"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add New Channel")
        dialog.geometry("750x720")
        dialog.configure(bg=self.bg)
        dialog.transient(self.root)
        dialog.grab_set()
        # Responsive: allow resizing but keep a usable minimum size
        dialog.minsize(620, 520)

        # Center dialog
        dialog.update_idletasks()
        win_w, win_h = 750, 720
        x = (dialog.winfo_screenwidth() // 2) - (win_w // 2)
        y = (dialog.winfo_screenheight() // 2) - (win_h // 2)
        dialog.geometry(f"{win_w}x{win_h}+{x}+{y}")

        # Fixed bottom action bar - reserve space first so it's ALWAYS visible
        bottom_bar = tk.Frame(dialog, bg=self.card_bg, padx=10, pady=10)
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Main container fills the dialog body
        main_container = tk.Frame(dialog, bg=self.bg)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        # ---- Scrollable body (canvas + scrollbar) ----
        canvas = tk.Canvas(main_container, bg=self.bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.card_bg)

        window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        # Refresh scroll region when content resizes
        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        # Responsive: stretch inner frame to match canvas width
        def _on_canvas_configure(event):
            if canvas.winfo_width() > 1:
                canvas.itemconfig(window_id, width=canvas.winfo_width())

        scrollable_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Enable mousewheel scrolling
        def _on_mousewheel(event):
            try:
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except:
                pass  # Silently ignore if widget is destroyed

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Cleanup event binding when window is closed
        def _on_close():
            canvas.unbind_all("<MouseWheel>")
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", _on_close)

        content = tk.Frame(scrollable_frame, bg=self.card_bg, padx=20, pady=20)
        content.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            content, text="Add New Channel", font=('Arial', 14, 'bold'),
            bg=self.card_bg, fg=self.text
        ).pack(anchor=tk.W, pady=(0, 20))

        # SOURCE TYPE SELECTION
        tk.Label(
            content, text="Video Source:", font=('Arial', 10, 'bold'),
            bg=self.card_bg, fg=self.text
        ).pack(anchor=tk.W, pady=(0, 5))

        source_type_var = tk.StringVar(value="local_folder" if hasattr(self, "source_var") else "tiktok")

        source_frame = tk.Frame(content, bg=self.card_bg)
        source_frame.pack(fill=tk.X, pady=(4, 12))

        tk.Radiobutton(
            source_frame, text="📱 TikTok (Fetch from TikTok API)",
            variable=source_type_var, value="tiktok",
            bg=self.card_bg, font=('Arial', 10)
        ).pack(side=tk.LEFT, padx=(0, 24))

        tk.Radiobutton(
            source_frame, text="📁 Local Folder (Videos on computer/synced cloud)",
            variable=source_type_var, value="local_folder",
            bg=self.card_bg, font=('Arial', 10)
        ).pack(side=tk.LEFT)

        # ---- 2-column grid form (fields side by side) ----
        form = tk.Frame(content, bg=self.card_bg)
        form.pack(fill=tk.X, pady=(0, 10))
        form.grid_columnconfigure(0, weight=1)
        form.grid_columnconfigure(1, weight=1)

        entries = {}

        def mk_label(row, col, text, pady=(8, 2)):
            lbl = tk.Label(form, text=text, font=('Arial', 10),
                           bg=self.card_bg, fg=self.text, anchor=tk.W)
            lbl.grid(row=row, column=col, sticky='w', padx=(0, 8), pady=pady)
            return lbl

        def mk_entry(row, col):
            ent = tk.Entry(form, font=('Arial', 10), relief=tk.SOLID, bd=1)
            ent.grid(row=row, column=col, sticky='ew', padx=(0, 8), pady=(0, 8))
            return ent

        # Row 0/1: Channel Name | Gmail
        mk_label(0, 0, 'Channel Name:')
        mk_label(0, 1, 'Gmail:')
        entries['channel_name'] = mk_entry(1, 0)
        entries['channel_name'].insert(0, 'e.g., MyChannel')
        entries['gmail'] = mk_entry(1, 1)
        entries['gmail'].insert(0, 'e.g., mychannel@gmail.com')

        # Row 2/3: YouTube Channel ID | dynamic (TikTok username / Source folder)
        mk_label(2, 0, 'YouTube Channel ID:')
        entries['youtube_channel_id'] = mk_entry(3, 0)
        entries['youtube_channel_id'].insert(0, 'UCxxxxxxxxxxxxxx')

        tiktok_label = mk_label(2, 1, 'TikTok Username:')
        tiktok_entry = mk_entry(3, 1)
        tiktok_entry.insert(0, 'e.g., mytiktok (no @)')
        entries['tiktok_username'] = tiktok_entry

        # Local-only fields (hidden for TikTok)
        source_folder_label = tk.Label(form, text='Video Source Folder:',
                                       font=('Arial', 10), bg=self.card_bg,
                                       fg=self.text, anchor=tk.W)
        source_folder_frame = tk.Frame(form, bg=self.card_bg)
        source_folder_entry = tk.Entry(source_folder_frame, font=('Arial', 10), relief=tk.SOLID, bd=1)
        source_folder_entry.insert(0, 'D:/Videos/ChannelName/')
        entries['video_source_folder'] = source_folder_entry

        def browse_source_folder():
            folder = filedialog.askdirectory(title="Select Video Source Folder")
            if folder:
                source_folder_entry.delete(0, tk.END)
                source_folder_entry.insert(0, folder)

        source_folder_btn = tk.Button(
            source_folder_frame, text="📂", command=browse_source_folder,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 9), width=4
        )

        uploaded_folder_label = tk.Label(form, text='Uploaded Folder:',
                                         font=('Arial', 10), bg=self.card_bg,
                                         fg=self.text, anchor=tk.W)
        uploaded_folder_frame = tk.Frame(form, bg=self.card_bg)
        uploaded_folder_entry = tk.Entry(uploaded_folder_frame, font=('Arial', 10), relief=tk.SOLID, bd=1)
        uploaded_folder_entry.insert(0, 'D:/Videos/ChannelName/uploaded/')
        entries['video_uploaded_folder'] = uploaded_folder_entry

        def browse_uploaded_folder():
            folder = filedialog.askdirectory(title="Select Uploaded Folder")
            if folder:
                uploaded_folder_entry.delete(0, tk.END)
                uploaded_folder_entry.insert(0, folder)

        uploaded_folder_btn = tk.Button(
            uploaded_folder_frame, text="📂", command=browse_uploaded_folder,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 9), width=4
        )
        source_folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        source_folder_btn.pack(side=tk.LEFT)
        uploaded_folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        uploaded_folder_btn.pack(side=tk.LEFT)

        sheet_free_var = tk.BooleanVar(value=False)
        sheet_free_checkbox = tk.Checkbutton(
            form,
            text="✨ Sheet-Free Mode (folder without Google Sheet)",
            variable=sheet_free_var,
            bg=self.card_bg, font=('Arial', 9, 'bold'),
            activebackground=self.card_bg, fg='#27ae60', selectcolor=self.card_bg
        )

        # Row 4/5: Credentials File | Uploaded Folder
        mk_label(4, 0, 'Credentials File:')
        creds_frame = tk.Frame(form, bg=self.card_bg)
        creds_frame.grid(row=5, column=0, sticky='ew', padx=(0, 8), pady=(0, 8))
        creds_entry = tk.Entry(creds_frame, font=('Arial', 10), relief=tk.SOLID, bd=1)
        creds_entry.insert(0, 'client_secret_mychannel.json')
        entries['credentials_file'] = creds_entry
        creds_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        def browse_creds_file():
            creds_folder = Path(self.config['credentials_folder'])
            filename = filedialog.askopenfilename(
                title="Select Credentials File",
                initialdir=str(creds_folder),
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )
            if filename:
                creds_entry.delete(0, tk.END)
                creds_entry.insert(0, Path(filename).name)

        tk.Button(
            creds_frame, text="📂", command=browse_creds_file,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 9), width=4
        ).pack(side=tk.LEFT)

        # Row 6/7: Sheet Tab Name | Enabled
        mk_label(6, 0, 'Sheet Tab Name:')
        entries['sheet_tab_name'] = mk_entry(7, 0)
        entries['sheet_tab_name'].insert(0, 'MyChannel')

        enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            form, text="Enabled", variable=enabled_var,
            bg=self.card_bg, font=('Arial', 10)
        ).grid(row=7, column=1, sticky='w', padx=(0, 8), pady=(8, 2))

        # Show/hide fields based on source type
        def update_source_fields():
            source_type = source_type_var.get()
            if hasattr(self, 'source_var') and source_type == 'local_folder':
                source_folder_frame.grid_remove()
                uploaded_folder_label.grid_remove()
                uploaded_folder_frame.grid_remove()
                sheet_free_checkbox.grid_remove()
                tiktok_label.grid_remove()
                tiktok_entry.grid_remove()
                source_folder_label.config(text='Uses shared videos + thumbnails folder from main GUI')
                source_folder_label.grid(row=2, column=1, sticky='w', padx=8, pady=8)
                return
            if source_type == "tiktok":
                tiktok_label.grid(row=2, column=1, sticky='w', padx=(0, 8), pady=(8, 2))
                tiktok_entry.grid(row=3, column=1, sticky='ew', padx=(0, 8), pady=(0, 8))
                source_folder_label.grid_remove()
                source_folder_frame.grid_remove()
                uploaded_folder_label.grid_remove()
                uploaded_folder_frame.grid_remove()
                sheet_free_checkbox.grid_remove()
            else:  # local_folder
                source_folder_label.grid(row=2, column=1, sticky='w', padx=(0, 8), pady=(8, 2))
                source_folder_frame.grid(row=3, column=1, sticky='ew', padx=(0, 8), pady=(0, 8))
                uploaded_folder_label.grid(row=4, column=1, sticky='w', padx=(0, 8), pady=(8, 2))
                uploaded_folder_frame.grid(row=5, column=1, sticky='ew', padx=(0, 8), pady=(0, 8))
                sheet_free_checkbox.grid(row=6, column=1, sticky='w', padx=(0, 8), pady=(8, 2))
                tiktok_label.grid_remove()
                tiktok_entry.grid_remove()

        # Bind radio buttons to update fields
        for widget in source_frame.winfo_children():
            if isinstance(widget, tk.Radiobutton):
                widget.config(command=update_source_fields)

        # Initialize fields
        update_source_fields()

        def save_channel():
            # Generate unique channel ID (find highest number and increment)
            existing_numbers = []
            for ch_id in self.channels_config.keys():
                if ch_id.startswith('channel'):
                    try:
                        num = int(ch_id.replace('channel', ''))
                        existing_numbers.append(num)
                    except:
                        pass

            # Get next available number (always increments, never reuses)
            channel_num = max(existing_numbers) + 1 if existing_numbers else 1
            channel_id = f'channel{channel_num}'

            # Double-check uniqueness (safety check)
            while channel_id in self.channels_config:
                channel_num += 1
                channel_id = f'channel{channel_num}'

            source_type = source_type_var.get()

            # Get values
            channel_data = {
                'channel_id': channel_id,
                'channel_name': entries['channel_name'].get(),
                'gmail': entries['gmail'].get(),
                'youtube_channel_id': entries['youtube_channel_id'].get(),
                'credentials_file': entries['credentials_file'].get(),
                'token_file': f'token_{entries["credentials_file"].get().replace(".json", "").replace("client_secret_", "")}',
                'sheet_tab_name': entries['sheet_tab_name'].get(),
                'sheet_tab_id': str(channel_num - 1),
                'enabled': enabled_var.get(),
                'source_type': source_type,
                'tiktok_username': entries['tiktok_username'].get() if source_type == 'tiktok' else '',
                'video_source_folder': entries['video_source_folder'].get() if source_type == 'local_folder' else '',
                'video_uploaded_folder': entries['video_uploaded_folder'].get() if source_type == 'local_folder' else '',
                'sheet_free_mode': sheet_free_var.get() if source_type == 'local_folder' else False
            }

            # Validate
            if not channel_data['channel_name']:
                messagebox.showerror("Error", "Channel name is required")
                return

            if source_type == 'tiktok' and not channel_data['tiktok_username']:
                messagebox.showerror("Error", "TikTok username is required for TikTok source")
                return

            if source_type == 'local_folder' and not hasattr(self, 'source_var'):
                if not channel_data['video_source_folder'] or not channel_data['video_uploaded_folder']:
                    messagebox.showerror("Error", "Both source and uploaded folder paths are required for Local Folder source")
                    return

            # Save
            self.channels_config[channel_id] = channel_data
            self.save_channels()

            self.log(f"✅ Added channel: {channel_data['channel_name']}", 'success')
            self.refresh_channels()

            if self.uploader:
                self.uploader.channels = self.channels_config

            _on_close()
            messagebox.showinfo("Success", f"Channel '{channel_data['channel_name']}' added successfully!")

        tk.Button(
            bottom_bar, text="✅ Save Channel", command=save_channel,
            bg=self.success, fg='white', font=('Arial', 11, 'bold'),
            relief=tk.FLAT, cursor='hand2', height=2
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        tk.Button(
            bottom_bar, text="❌ Cancel", command=_on_close,
            bg=self.error, fg='white', font=('Arial', 11, 'bold'),
            relief=tk.FLAT, cursor='hand2', height=2
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

    def edit_channel(self):
        """Edit selected channel with title formatting and default description"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a channel to edit")
            return

        channel_name = self.tree.item(selected[0])['values'][1]
        channel_id = None
        for ch_id, ch_data in self.channels_config.items():
            if ch_data['channel_name'] == channel_name:
                channel_id = ch_id
                break

        if not channel_id:
            messagebox.showerror("Error", "Channel not found")
            return

        channel_data = self.channels_config[channel_id]

        # Create larger edit dialog with scrollable content
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Channel: {channel_name}")
        dialog.geometry("750x850")
        dialog.configure(bg=self.bg)
        dialog.transient(self.root)
        dialog.grab_set()

        # Main container with scrollbar
        main_container = tk.Frame(dialog, bg=self.bg)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        canvas = tk.Canvas(main_container, bg=self.bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.card_bg)

        window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        # Responsive: stretch inner frame to match canvas width
        def _on_canvas_configure(event):
            if canvas.winfo_width() > 1:
                canvas.itemconfig(window_id, width=canvas.winfo_width())

        scrollable_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Enable mousewheel scrolling
        def _on_mousewheel(event):
            try:
                # Check if canvas still exists before scrolling
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            except:
                pass  # Silently ignore if widget is destroyed

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Cleanup event binding when window is closed
        def _on_close():
            canvas.unbind_all("<MouseWheel>")
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", _on_close)

        content = tk.Frame(scrollable_frame, bg=self.card_bg, padx=20, pady=20)
        content.pack(fill=tk.BOTH, expand=True)

        # Header
        tk.Label(
            content, text=f"✏️ Edit Channel: {channel_name}",
            font=('Arial', 16, 'bold'),
            bg=self.card_bg, fg=self.text
        ).pack(anchor=tk.W, pady=(0, 20))

        # ===== SECTION 1: BASIC INFO =====
        section1 = tk.LabelFrame(
            content, text="📋 Basic Information",
            font=('Arial', 12, 'bold'),
            bg=self.card_bg, fg=self.text, padx=15, pady=15
        )
        section1.pack(fill=tk.X, pady=(0, 15))

        entries = {}

        # 2-column grid layout (fields side by side)
        section1.grid_columnconfigure(0, weight=1)
        section1.grid_columnconfigure(1, weight=1)

        def mk_label(row, col, text):
            tk.Label(
                section1, text=text, font=('Arial', 10),
                bg=self.card_bg, fg=self.text, anchor=tk.W
            ).grid(row=row, column=col, sticky='w', padx=(0, 10), pady=(8, 2))

        def mk_entry(row, col, key):
            entry = tk.Entry(section1, font=('Arial', 10), relief=tk.SOLID, bd=1)
            entry.insert(0, channel_data.get(key, ''))
            entry.grid(row=row, column=col, sticky='ew', padx=(0, 10), pady=(0, 8))
            entries[key] = entry

        # Row 0/1: Channel Name | Gmail
        mk_label(0, 0, 'Channel Name:')
        mk_label(0, 1, 'Gmail:')
        mk_entry(1, 0, 'channel_name')
        mk_entry(1, 1, 'gmail')

        # Row 2/3: YouTube Channel ID | TikTok Username
        mk_label(2, 0, 'YouTube Channel ID:')
        mk_label(2, 1, 'TikTok Username:')
        mk_entry(3, 0, 'youtube_channel_id')
        mk_entry(3, 1, 'tiktok_username')

        # Row 4/5: Credentials File (+browse) | Sheet Tab Name
        mk_label(4, 0, 'Credentials File:')
        creds_frame = tk.Frame(section1, bg=self.card_bg)
        creds_frame.grid(row=5, column=0, sticky='ew', padx=(0, 10), pady=(0, 8))
        creds_entry = tk.Entry(creds_frame, font=('Arial', 10), relief=tk.SOLID, bd=1)
        creds_entry.insert(0, channel_data.get('credentials_file', ''))
        entries['credentials_file'] = creds_entry
        creds_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        def browse_creds_file():
            creds_folder = Path(self.config['credentials_folder'])
            filename = filedialog.askopenfilename(
                title="Select Credentials File",
                initialdir=str(creds_folder),
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )
            if filename:
                creds_entry.delete(0, tk.END)
                creds_entry.insert(0, Path(filename).name)

        tk.Button(
            creds_frame, text="📂", command=browse_creds_file,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 9), width=4
        ).pack(side=tk.LEFT)

        mk_label(4, 1, 'Sheet Tab Name:')
        mk_entry(5, 1, 'sheet_tab_name')

        enabled_var = tk.BooleanVar(value=channel_data.get('enabled', True))
        tk.Checkbutton(
            section1, text="✅ Channel Enabled", variable=enabled_var,
            bg=self.card_bg, font=('Arial', 10, 'bold')
        ).grid(row=6, column=0, sticky='w', padx=(0, 10), pady=(8, 2))

        # ===== SECTION 1.5: VIDEO SOURCE =====
        source_section = tk.LabelFrame(
            content, text="📹 Video Source",
            font=('Arial', 12, 'bold'),
            bg=self.card_bg, fg=self.text, padx=15, pady=15
        )
        source_section.pack(fill=tk.X, pady=(0, 15))

        current_source = channel_data.get('source_type', 'tiktok')
        source_type_var = tk.StringVar(value=current_source)

        # Radio buttons side by side
        radio_frame = tk.Frame(source_section, bg=self.card_bg)
        radio_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Radiobutton(
            radio_frame, text="📱 TikTok (Fetch from TikTok API)",
            variable=source_type_var, value="tiktok",
            bg=self.card_bg, font=('Arial', 10)
        ).pack(side=tk.LEFT, padx=(0, 24))

        tk.Radiobutton(
            radio_frame, text="📁 Local Folder (Videos on computer/synced cloud)",
            variable=source_type_var, value="local_folder",
            bg=self.card_bg, font=('Arial', 10)
        ).pack(side=tk.LEFT)

        # 2-column grid for the folder fields (local_folder source)
        source_grid = tk.Frame(source_section, bg=self.card_bg)
        source_grid.pack(fill=tk.X, pady=(0, 10))
        source_grid.grid_columnconfigure(0, weight=1)
        source_grid.grid_columnconfigure(1, weight=1)

        # Source folder (local only)
        source_folder_label = tk.Label(
            source_grid, text="Video Source Folder:", font=('Arial', 10),
            bg=self.card_bg, fg=self.text, anchor=tk.W
        )
        source_folder_frame = tk.Frame(source_grid, bg=self.card_bg)
        source_folder_entry = tk.Entry(source_folder_frame, font=('Arial', 10), relief=tk.SOLID, bd=1)
        source_folder_entry.insert(0, channel_data.get('video_source_folder', ''))
        entries['video_source_folder'] = source_folder_entry

        def browse_source_folder():
            folder = filedialog.askdirectory(title="Select Video Source Folder")
            if folder:
                source_folder_entry.delete(0, tk.END)
                source_folder_entry.insert(0, folder)

        source_folder_btn = tk.Button(
            source_folder_frame, text="📂", command=browse_source_folder,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 9), width=4
        )
        source_folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        source_folder_btn.pack(side=tk.LEFT)

        # Uploaded folder (local only)
        uploaded_folder_label = tk.Label(
            source_grid, text="Uploaded Folder:", font=('Arial', 10),
            bg=self.card_bg, fg=self.text, anchor=tk.W
        )
        uploaded_folder_frame = tk.Frame(source_grid, bg=self.card_bg)
        uploaded_folder_entry = tk.Entry(uploaded_folder_frame, font=('Arial', 10), relief=tk.SOLID, bd=1)
        uploaded_folder_entry.insert(0, channel_data.get('video_uploaded_folder', ''))
        entries['video_uploaded_folder'] = uploaded_folder_entry

        def browse_uploaded_folder():
            folder = filedialog.askdirectory(title="Select Uploaded Folder")
            if folder:
                uploaded_folder_entry.delete(0, tk.END)
                uploaded_folder_entry.insert(0, folder)

        uploaded_folder_btn = tk.Button(
            uploaded_folder_frame, text="📂", command=browse_uploaded_folder,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 9), width=4
        )
        uploaded_folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        uploaded_folder_btn.pack(side=tk.LEFT)

        # Sheet-Free Mode checkbox (only for local_folder source)
        sheet_free_var = tk.BooleanVar(value=channel_data.get('sheet_free_mode', False))
        sheet_free_checkbox = tk.Checkbutton(
            source_grid,
            text="✨ Sheet-Free Mode (Upload directly from folder without Google Sheet)",
            variable=sheet_free_var,
            bg=self.card_bg,
            font=('Arial', 9, 'bold'),
            activebackground=self.card_bg,
            fg='#27ae60',
            selectcolor=self.card_bg
        )

        # Show/hide fields based on source type
        def update_source_fields():
            source_type = source_type_var.get()
            if hasattr(self, 'source_var') and source_type == 'local_folder':
                source_folder_frame.grid_remove()
                uploaded_folder_label.grid_remove()
                uploaded_folder_frame.grid_remove()
                sheet_free_checkbox.grid_remove()
                source_folder_label.config(text='Uses shared videos + thumbnails folder from main GUI')
                source_folder_label.grid(row=0, column=0, columnspan=2, sticky='w', padx=8, pady=8)
                return
            if source_type == "local_folder":
                source_folder_label.grid(row=0, column=0, sticky='w', padx=(0, 10), pady=(5, 2))
                source_folder_frame.grid(row=1, column=0, sticky='ew', padx=(0, 10), pady=(0, 8))
                uploaded_folder_label.grid(row=0, column=1, sticky='w', padx=(0, 10), pady=(5, 2))
                uploaded_folder_frame.grid(row=1, column=1, sticky='ew', padx=(0, 10), pady=(0, 8))
                sheet_free_checkbox.grid(row=2, column=0, columnspan=2, sticky='w', padx=(0, 10), pady=(8, 2))
            else:
                source_folder_label.grid_remove()
                source_folder_frame.grid_remove()
                uploaded_folder_label.grid_remove()
                uploaded_folder_frame.grid_remove()
                sheet_free_checkbox.grid_remove()

        source_type_var.trace('w', lambda *args: update_source_fields())
        update_source_fields()  # Initial update

        # ===== SECTION 2: TITLE FORMATTING =====
        section2 = tk.LabelFrame(
            content, text="🎬 Title Formatting",
            font=('Arial', 12, 'bold'),
            bg=self.card_bg, fg=self.text, padx=15, pady=15
        )
        section2.pack(fill=tk.X, pady=(0, 15))

        tk.Label(
            section2,
            text="Customize how TikTok titles appear on YouTube",
            font=('Arial', 9, 'italic'), bg=self.card_bg, fg='#666'
        ).pack(anchor=tk.W, pady=(0, 10))

        # 2-column grid: Format | Prefix, then Suffix (side by side)
        fmt_grid = tk.Frame(section2, bg=self.card_bg)
        fmt_grid.pack(fill=tk.X, pady=(0, 5))
        fmt_grid.grid_columnconfigure(0, weight=1)
        fmt_grid.grid_columnconfigure(1, weight=1)

        # Format (col 0)
        tk.Label(
            fmt_grid, text="Format:", font=('Arial', 10),
            bg=self.card_bg, fg=self.text, anchor=tk.W
        ).grid(row=0, column=0, sticky='w', padx=(0, 10), pady=(5, 2))

        format_var = tk.StringVar(value=channel_data.get('title_format', 'replace'))
        format_combo = ttk.Combobox(
            fmt_grid, textvariable=format_var,
            values=['replace', 'prepend', 'append', 'wrap', 'sheet'],
            state='readonly', font=('Arial', 10)
        )
        format_combo.grid(row=1, column=0, sticky='ew', padx=(0, 10), pady=(0, 5))

        # Prefix (col 1)
        tk.Label(
            fmt_grid, text="Prefix (appears before title):", font=('Arial', 10),
            bg=self.card_bg, fg=self.text, anchor=tk.W
        ).grid(row=0, column=1, sticky='w', padx=(0, 10), pady=(5, 2))

        prefix_entry = tk.Entry(fmt_grid, font=('Arial', 10), relief=tk.SOLID, bd=1)
        prefix_entry.insert(0, channel_data.get('title_prefix', ''))
        prefix_entry.grid(row=1, column=1, sticky='ew', padx=(0, 10), pady=(0, 5))

        # Suffix (row 2/3, col 0; col 1 left empty)
        tk.Label(
            fmt_grid, text="Suffix (appears after title):", font=('Arial', 10),
            bg=self.card_bg, fg=self.text, anchor=tk.W
        ).grid(row=2, column=0, sticky='w', padx=(0, 10), pady=(5, 2))

        suffix_entry = tk.Entry(fmt_grid, font=('Arial', 10), relief=tk.SOLID, bd=1)
        suffix_entry.insert(0, channel_data.get('title_suffix', ''))
        suffix_entry.grid(row=3, column=0, sticky='ew', padx=(0, 10), pady=(0, 5))

        # Format descriptions
        format_desc_label = tk.Label(
            section2, text="", font=('Arial', 9),
            bg=self.card_bg, fg='#666', wraplength=680, justify=tk.LEFT
        )
        format_desc_label.pack(anchor=tk.W, pady=(0, 10))

        def update_format_desc(*args):
            descriptions = {
                'replace': "📝 Original TikTok title (no changes)",
                'prepend': "📝 Prefix + TikTok title\nExample: '🎓 English: How to pronounce words'",
                'append': "📝 TikTok title + Suffix\nExample: 'Chocolate recipe 🍫 #ChocolateArt'",
                'wrap': "📝 Prefix + TikTok title + Suffix\nExample: '✨ Beauty tip | Beauty Tips'",
                'sheet': "📊 Google Sheets title + Prefix/Suffix\nUses title from Column C in your sheet with prefix/suffix"
            }
            format_desc_label.config(text=descriptions.get(format_var.get(), ''))

        format_var.trace('w', update_format_desc)
        update_format_desc()

        # Title preview
        title_preview_label = tk.Label(
            section2, text="", font=('Arial', 10, 'bold'),
            bg='#fff3cd', fg='#856404', relief=tk.SOLID, bd=1,
            wraplength=680, justify=tk.LEFT, padx=10, pady=8
        )
        title_preview_label.pack(fill=tk.X, pady=(5, 0))

        def update_title_preview(*args):
            sample = "Amazing chocolate recipe"
            sheet_sample = "Title from Google Sheet"  # Sample for sheet format
            fmt = format_var.get()
            prefix = prefix_entry.get()
            suffix = suffix_entry.get()

            if fmt == 'replace':
                result = sample
            elif fmt == 'prepend':
                result = f"{prefix} {sample}" if prefix else sample
            elif fmt == 'append':
                result = f"{sample} {suffix}" if suffix else sample
            elif fmt == 'wrap':
                parts = []
                if prefix: parts.append(prefix)
                parts.append(sample)
                if suffix: parts.append(suffix)
                result = ' '.join(parts)
            elif fmt == 'sheet':
                # Use sheet sample with prefix/suffix
                parts = []
                if prefix: parts.append(prefix)
                parts.append(sheet_sample)
                if suffix: parts.append(suffix)
                result = ' '.join(parts)
            else:
                result = sample

            title_preview_label.config(text=f"Preview: {result[:100]}")

        prefix_entry.bind('<KeyRelease>', update_title_preview)
        suffix_entry.bind('<KeyRelease>', update_title_preview)
        format_var.trace('w', update_title_preview)
        update_title_preview()

        # ===== SECTION 3: DEFAULT DESCRIPTION =====
        section3 = tk.LabelFrame(
            content, text="📝 Default Description",
            font=('Arial', 12, 'bold'),
            bg=self.card_bg, fg=self.text, padx=15, pady=15
        )
        section3.pack(fill=tk.X, pady=(0, 15))

        tk.Label(
            section3,
            text="This will be combined with TikTok captions on each upload",
            font=('Arial', 9, 'italic'), bg=self.card_bg, fg='#666'
        ).pack(anchor=tk.W, pady=(0, 10))

        # Toolbar with buttons
        toolbar = tk.Frame(section3, bg=self.card_bg)
        toolbar.pack(fill=tk.X, pady=(0, 10))

        # Template dropdown
        tk.Label(
            toolbar, text="Quick Templates:", font=('Arial', 9),
            bg=self.card_bg, fg=self.text
        ).pack(side=tk.LEFT, padx=(0, 5))

        templates = {
            'Blank': '',
            'English Learning': """📚 Learn English with us!
📧 Contact: contact@example.com
🌐 Website: example.com
📱 Follow us on Instagram

#EnglishLearning #LearnEnglish #ESL #shorts""",
            'Food/Recipes': """🍴 Delicious recipes daily!
📧 Contact: hello@foodchannel.com
🌐 Recipe blog: example.com
📱 Instagram: @foodchannel

🎵 Music: Epidemic Sound
#FoodShorts #Recipes #Cooking #shorts""",
            'Facts/Education': """💡 Amazing facts daily!
📧 Contact: facts@example.com
🔔 Subscribe for more!
📱 Follow us on TikTok & Instagram

#DidYouKnow #Facts #Education #shorts""",
            'Beauty/Wellness': """✨ Beauty tips & wellness advice
📧 Collabs: beauty@example.com
🌐 Website: example.com
📱 Instagram: @beautytips

#BeautyTips #Skincare #Wellness #shorts""",
            'DIY/Crafts': """🎨 Creative DIY ideas!
📧 Contact: craft@example.com
🛍️ Shop materials: example.com
📱 Instagram: @diycraft

#DIY #Crafts #Handmade #shorts"""
        }

        template_var = tk.StringVar(value='Blank')
        template_combo = ttk.Combobox(
            toolbar, textvariable=template_var,
            values=list(templates.keys()),
            state='readonly', font=('Arial', 9), width=18
        )
        template_combo.pack(side=tk.LEFT, padx=(0, 10))

        def apply_template():
            desc_text.delete('1.0', tk.END)
            desc_text.insert('1.0', templates[template_var.get()])
            update_char_count()

        tk.Button(
            toolbar, text="📋 Apply", command=apply_template,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 9), padx=10, pady=3
        ).pack(side=tk.LEFT, padx=(0, 10))

        # Import from file button
        def import_from_file():
            filename = filedialog.askopenfilename(
                title="Select Description File",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )
            if filename:
                try:
                    with open(filename, 'r', encoding='utf-8') as f:
                        content_text = f.read()
                    desc_text.delete('1.0', tk.END)
                    desc_text.insert('1.0', content_text)
                    update_char_count()
                    messagebox.showinfo("Success", "Description imported successfully!")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to import file: {e}")

        tk.Button(
            toolbar, text="📂 Import File", command=import_from_file,
            bg=self.accent, fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 9), padx=10, pady=3
        ).pack(side=tk.LEFT)

        # Description text area
        desc_frame = tk.Frame(section3, bg=self.card_bg)
        desc_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        desc_text = scrolledtext.ScrolledText(
            desc_frame, font=('Arial', 10),
            height=12, relief=tk.SOLID, bd=1, wrap=tk.WORD
        )
        desc_text.pack(fill=tk.BOTH, expand=True)
        desc_text.insert('1.0', channel_data.get('default_description', ''))

        # Character counter
        char_count_label = tk.Label(
            section3, text="", font=('Arial', 9),
            bg=self.card_bg, anchor=tk.E
        )
        char_count_label.pack(fill=tk.X, pady=(5, 5))

        def update_char_count(*args):
            content_text = desc_text.get('1.0', tk.END).strip()
            length = len(content_text)

            if length > 5000:
                char_count_label.config(
                    text=f"❌ {length}/5000 characters (EXCEEDS LIMIT!)",
                    fg='#d32f2f'
                )
            elif length > 4500:
                char_count_label.config(
                    text=f"⚠️ {length}/5000 characters (approaching limit)",
                    fg='#f57c00'
                )
            else:
                char_count_label.config(
                    text=f"✓ {length}/5000 characters",
                    fg='#388e3c'
                )

        desc_text.bind('<KeyRelease>', update_char_count)
        update_char_count()

        # Preview button
        def show_preview():
            tiktok_sample = "🍫 Making delicious chocolate truffles! Try this easy recipe at home 😍 #chocolate #recipe"
            default_desc = desc_text.get('1.0', tk.END).strip()

            if default_desc:
                combined = f"{tiktok_sample}\n\n{'='*50}\n\n{default_desc}"
            else:
                combined = tiktok_sample

            # Create preview dialog
            preview_dialog = tk.Toplevel(dialog)
            preview_dialog.title("Description Preview")
            preview_dialog.geometry("650x600")
            preview_dialog.transient(dialog)

            tk.Label(
                preview_dialog,
                text="📺 YouTube Description Preview",
                font=('Arial', 14, 'bold'), padx=20, pady=15
            ).pack()

            tk.Label(
                preview_dialog,
                text="Sample TikTok Caption + Your Default Description",
                font=('Arial', 9, 'italic'), fg='#666'
            ).pack(pady=(0, 10))

            preview_text = scrolledtext.ScrolledText(
                preview_dialog, font=('Arial', 10),
                height=25, wrap=tk.WORD, padx=10, pady=10
            )
            preview_text.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))
            preview_text.insert('1.0', combined)
            preview_text.config(state=tk.DISABLED)

            tk.Label(
                preview_dialog,
                text=f"Total length: {len(combined)} characters",
                font=('Arial', 9), fg='#666'
            ).pack(pady=(5, 10))

            tk.Button(
                preview_dialog, text="Close", command=preview_dialog.destroy,
                bg=self.accent, fg='white', font=('Arial', 10),
                relief=tk.FLAT, cursor='hand2', padx=20, pady=8
            ).pack(pady=(0, 20))

        tk.Button(
            section3, text="👁️ Preview Combined Description", command=show_preview,
            bg='#2196f3', fg='white', relief=tk.FLAT, cursor='hand2',
            font=('Arial', 10), pady=8
        ).pack(fill=tk.X)

        # ===== YOUTUBE TAGS & PLAYLIST (side by side) =====
        tags_playlist_grid = tk.Frame(section3, bg=self.card_bg)
        tags_playlist_grid.pack(fill=tk.X, pady=(15, 0))
        tags_playlist_grid.grid_columnconfigure(0, weight=1)
        tags_playlist_grid.grid_columnconfigure(1, weight=1)

        # Tags column
        tk.Label(
            tags_playlist_grid, text="🏷️ YouTube Tags (comma-separated):",
            font=('Arial', 11, 'bold'), bg=self.card_bg, anchor=tk.W
        ).grid(row=0, column=0, sticky='w', padx=(0, 10), pady=(0, 5))

        tags_entry = tk.Entry(tags_playlist_grid, font=('Arial', 10), relief=tk.SOLID, bd=1)
        tags_entry.insert(0, channel_data.get('default_tags', 'shorts, tiktok'))
        tags_entry.grid(row=1, column=0, sticky='ew', padx=(0, 10), pady=(0, 4))

        tk.Label(
            tags_playlist_grid,
            text="💡 movie explained shorts, explained movies shorts",
            font=('Arial', 9), bg=self.card_bg, fg='#666', anchor=tk.W
        ).grid(row=2, column=0, sticky='w', padx=(0, 10))

        # Playlist column
        tk.Label(
            tags_playlist_grid, text="📂 Auto-Add to Playlist (Optional):",
            font=('Arial', 11, 'bold'), bg=self.card_bg, anchor=tk.W
        ).grid(row=0, column=1, sticky='w', padx=(0, 10), pady=(0, 5))

        playlist_entry = tk.Entry(tags_playlist_grid, font=('Arial', 10), relief=tk.SOLID, bd=1)
        playlist_entry.insert(0, channel_data.get('default_playlist_id', ''))
        playlist_entry.grid(row=1, column=1, sticky='ew', padx=(0, 10), pady=(0, 4))

        tk.Label(
            tags_playlist_grid,
            text="💡 Enter Playlist ID (e.g., PLxxx...) - empty to skip",
            font=('Arial', 9), bg=self.card_bg, fg='#666', anchor=tk.W
        ).grid(row=2, column=1, sticky='w', padx=(0, 10))

        # ===== SAVE/CANCEL BUTTONS =====
        def save_changes():
            # Validate character count
            desc_content = desc_text.get('1.0', tk.END).strip()
            if len(desc_content) > 5000:
                messagebox.showerror(
                    "Error",
                    "Description exceeds 5000 character limit!\nPlease shorten it before saving."
                )
                return

            # Save basic fields
            for key, entry in entries.items():
                channel_data[key] = entry.get()
            channel_data['enabled'] = enabled_var.get()

            # Save title formatting
            channel_data['title_format'] = format_var.get()
            channel_data['title_prefix'] = prefix_entry.get()
            channel_data['title_suffix'] = suffix_entry.get()

            # Save default description
            channel_data['default_description'] = desc_content

            # Save default tags
            channel_data['default_tags'] = tags_entry.get().strip()

            # Save playlist ID
            channel_data['default_playlist_id'] = playlist_entry.get().strip()

            # Save video source type
            channel_data['source_type'] = source_type_var.get()

            # Save sheet-free mode setting
            if source_type_var.get() == 'local_folder':
                channel_data['sheet_free_mode'] = sheet_free_var.get()
            else:
                channel_data['sheet_free_mode'] = False

            self.save_channels()
            self.log(f"✅ Updated channel: {channel_data['channel_name']}", 'success')
            self.refresh_channels()

            if self.uploader:
                self.uploader.channels = self.channels_config

            canvas.unbind_all("<MouseWheel>")
            dialog.destroy()
            messagebox.showinfo("Success", "Channel updated successfully!")

        btn_frame = tk.Frame(scrollable_frame, bg=self.card_bg, padx=20)
        btn_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Button(
            btn_frame, text="✅ Save Changes", command=save_changes,
            bg=self.success, fg='white', font=('Arial', 12, 'bold'),
            relief=tk.FLAT, cursor='hand2', height=2
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        tk.Button(
            btn_frame, text="❌ Cancel",
            command=lambda: (canvas.unbind_all("<MouseWheel>"), dialog.destroy()),
            bg=self.error, fg='white', font=('Arial', 12, 'bold'),
            relief=tk.FLAT, cursor='hand2', height=2
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def reauthenticate_channel(self):
        """Re-authenticate selected channel in background"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a channel to re-authenticate")
            return

        if self.is_loading:
            messagebox.showinfo("Please Wait", "Another operation is in progress...")
            return

        channel_name = self.tree.item(selected[0])['values'][1]

        # Find channel
        channel_config = None
        for ch_id, ch_data in self.channels_config.items():
            if ch_data['channel_name'] == channel_name:
                channel_config = ch_data
                break

        if not channel_config:
            messagebox.showerror("Error", "Channel not found")
            return

        if not self.uploader:
            messagebox.showerror("Error", "Backend not initialized")
            return

        self.is_loading = True
        self.log(f"🔐 Preparing to re-authenticate {channel_name}...", 'info')

        def reauth_thread():
            try:
                # Delete token file
                token_path = Path(self.config['credentials_folder']) / f"{channel_config['token_file']}.pickle"
                if token_path.exists():
                    try:
                        token_path.unlink()
                        self.log(f"🗑️  Deleted old token for {channel_name}", 'info')
                    except Exception as e:
                        self.log(f"⚠️  Could not delete token: {e}", 'warning')

                # Trigger re-authentication (OAuth browser window will open)
                self.log(f"🔐 Opening browser for OAuth... Please authorize in the browser.", 'info')

                # Use get_youtube_service which handles authentication
                service = self.uploader.get_youtube_service(channel_config)

                if service:
                    self.log(f"✅ Re-authentication successful for {channel_name}", 'success')
                    success_msg = f"Re-authentication successful!\n\nChannel: {channel_name}"
                    self.root.after(0, lambda msg=success_msg: messagebox.showinfo("Success", msg))
                else:
                    self.log(f"❌ Re-authentication failed for {channel_name}", 'error')
                    self.root.after(0, lambda: messagebox.showerror("Error", "Re-authentication failed. Check logs for details."))

            except Exception as e:
                error_msg = str(e)
                self.log(f"❌ Re-auth error: {error_msg}", 'error')
                self.root.after(0, lambda msg=error_msg: messagebox.showerror("Error", f"Re-authentication error: {msg}"))
            finally:
                self.is_loading = False

        threading.Thread(target=reauth_thread, daemon=True).start()

    def delete_channel(self):
        """Delete selected channel"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a channel to delete")
            return

        channel_name = self.tree.item(selected[0])['values'][1]

        # Confirm
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete channel '{channel_name}'?\n\nThis will NOT delete credential files."):
            return

        # Find and delete
        channel_id = None
        for ch_id, ch_data in self.channels_config.items():
            if ch_data['channel_name'] == channel_name:
                channel_id = ch_id
                break

        if channel_id:
            del self.channels_config[channel_id]
            self.save_channels()

            self.log(f"🗑️  Deleted channel: {channel_name}", 'warning')
            self.refresh_channels()

            if self.uploader:
                self.uploader.channels = self.channels_config

            messagebox.showinfo("Success", f"Channel '{channel_name}' deleted")

    def update_ytdlp(self):
        """Check and update yt-dlp to latest version"""
        if self.is_loading:
            messagebox.showinfo("Please Wait", "Another operation is in progress...")
            return

        self.is_loading = True
        self.log("🔄 Checking yt-dlp version...", 'info')

        def update_thread():
            try:
                import subprocess
                import sys

                # Check current version
                try:
                    result = subprocess.run(
                        [sys.executable, '-m', 'yt_dlp', '--version'],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    current_version = result.stdout.strip() if result.returncode == 0 else "Unknown"
                    self.log(f"📦 Current yt-dlp version: {current_version}", 'info')
                except Exception as e:
                    self.log(f"⚠️  Could not check version: {e}", 'warning')
                    current_version = "Unknown"

                # Update yt-dlp
                self.log("⬇️  Downloading latest yt-dlp...", 'info')
                update_result = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'],
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if update_result.returncode == 0:
                    # Check new version
                    try:
                        new_result = subprocess.run(
                            [sys.executable, '-m', 'yt_dlp', '--version'],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        new_version = new_result.stdout.strip() if new_result.returncode == 0 else "Unknown"

                        if new_version == current_version:
                            self.log(f"✅ yt-dlp is already up to date: {new_version}", 'success')
                            self.root.after(0, lambda: messagebox.showinfo(
                                "Already Updated",
                                f"yt-dlp is already at the latest version!\n\nVersion: {new_version}"
                            ))
                        else:
                            self.log(f"✅ yt-dlp updated successfully!", 'success')
                            self.log(f"   Old version: {current_version}", 'info')
                            self.log(f"   New version: {new_version}", 'success')
                            self.root.after(0, lambda: messagebox.showinfo(
                                "Update Successful",
                                f"yt-dlp updated successfully!\n\n"
                                f"Old version: {current_version}\n"
                                f"New version: {new_version}\n\n"
                                f"TikTok profile fetching should work better now!"
                            ))
                    except Exception as e:
                        self.log(f"✅ yt-dlp updated (version check failed: {e})", 'success')
                        self.root.after(0, lambda: messagebox.showinfo(
                            "Update Complete",
                            "yt-dlp has been updated to the latest version!"
                        ))
                else:
                    error_output = update_result.stderr[:500] if update_result.stderr else "Unknown error"
                    self.log(f"❌ Update failed: {error_output}", 'error')
                    self.root.after(0, lambda err=error_output: messagebox.showerror(
                        "Update Failed",
                        f"Failed to update yt-dlp.\n\nError:\n{err}"
                    ))

            except subprocess.TimeoutExpired:
                self.log("❌ Update timeout (120s)", 'error')
                self.root.after(0, lambda: messagebox.showerror(
                    "Timeout",
                    "Update process timed out. Please try again or update manually."
                ))
            except Exception as e:
                error_msg = str(e)
                self.log(f"❌ Update error: {error_msg}", 'error')
                self.root.after(0, lambda msg=error_msg: messagebox.showerror(
                    "Error",
                    f"Failed to update yt-dlp:\n\n{msg}"
                ))
            finally:
                self.is_loading = False

        threading.Thread(target=update_thread, daemon=True).start()

    def refresh_all_data(self):
        """Refresh all statistics and data in background thread"""
        if self.is_loading:
            self.log("⚠️  Already refreshing...", 'warning')
            return

        self.is_loading = True
        self.log("🔄 Refreshing stats...", 'info')

        def refresh_thread():
            if not self.uploader:
                self.is_loading = False
                return

            try:
                # Update stats
                enabled_channels = len([ch for ch in self.channels_config.values() if ch.get('enabled', True)])
                self.root.after(0, lambda: self.stat_labels['Channels'].config(text=str(enabled_channels)))

                # Get total uploads from sheets (slow network!).
                # The old loop called open_by_url() once PER channel, so a
                # transient blip could fail all 9 and hang ~1 min. Now we open
                # the spreadsheet once, reuse the worksheet handles, and retry
                # briefly instead of zeroing every stat on the first hiccup.
                if self.uploader.sheets_client:
                    total_uploads = 0
                    total_videos = 0

                    spreadsheet, ws_map, open_error = None, {}, None
                    for attempt in range(3):
                        try:
                            spreadsheet = self.uploader.sheets_client.open_by_url(
                                self.uploader.spreadsheet_url
                            )
                            ws_map = {ws.title: ws for ws in spreadsheet.worksheets()}
                            open_error = None
                            break
                        except Exception as e:
                            open_error = e
                            if attempt < 2:
                                time.sleep(2)

                    if open_error is not None:
                        self.log(f"⚠️  Could not open spreadsheet: {str(open_error)[:70]}", 'warning')
                    else:
                        for ch_id, ch_data in self.channels_config.items():
                            if not ch_data.get('enabled'):
                                continue
                            worksheet = ws_map.get(ch_data['sheet_tab_name'])
                            if worksheet is None:
                                self.log(f"⚠️  Could not read {ch_data['channel_name']}: tab '{ch_data['sheet_tab_name']}' not found", 'warning')
                                continue
                            try:
                                rows = worksheet.get_all_values()[1:]
                                total_videos += len(rows)
                                # Column J (index 9) contains status
                                uploads = len([r for r in rows if len(r) > 9 and r[9].lower() == 'done'])
                                total_uploads += uploads
                            except Exception as e:
                                self.log(f"⚠️  Could not read {ch_data['channel_name']}: {str(e)[:50]}", 'warning')

                        self.log(f"📊 Total videos: {total_videos}, Uploaded: {total_uploads}", 'info')
                        self.root.after(0, lambda v=total_videos: self.stat_labels['Videos'].config(text=str(v)))
                        self.root.after(0, lambda u=total_uploads: self.stat_labels['Uploaded'].config(text=str(u)))

                # Update token status
                self.root.after(0, lambda: self.stat_labels['Tokens'].config(text='Healthy', fg=self.success))

                # Refresh channels on main thread
                self.root.after(0, self.refresh_channels)

                self.log("✅ Stats refreshed", 'success')

            except Exception as e:
                self.log(f"⚠️  Refresh error: {e}", 'warning')
            finally:
                self.is_loading = False

        # Run in background thread to avoid freezing GUI
        threading.Thread(target=refresh_thread, daemon=True).start()

    def refresh_channels(self):
        """Refresh channel list"""
        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Add channels
        for ch_id, ch_data in self.channels_config.items():
            status = '✅' if ch_data.get('enabled', True) else '❌'
            token_age = '0 days'  # TODO: Calculate from token file
            last_upload = 'Never'  # TODO: Get from sheets

            self.tree.insert('', tk.END, values=(
                status,
                ch_data.get('channel_name', 'Unknown'),
                token_age,
                last_upload
            ))

    def _interruptible_sleep(self, seconds: float):
        """Sleep in 1-second slices so Stop can interrupt a long wait quickly."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if not self.is_running or (self.uploader and self.uploader.stop_requested):
                return
            time.sleep(1)

    def start_automation(self):
        """Start automation"""
        # CRITICAL: Use lock to prevent race condition (double-start)
        if not self.start_lock.acquire(blocking=False):
            messagebox.showwarning("Already Starting", "Automation is already starting! Please wait.")
            return

        try:
            if not self.uploader:
                messagebox.showerror("Error", "Backend not initialized!")
                return

            if not self.channels_config:
                messagebox.showerror("Error", "No channels configured!")
                return

            # Prevent double-start (if already running)
            if self.is_running:
                messagebox.showwarning("Already Running", "Automation is already running! Please stop it first.")
                return

            # Prevent starting while a previous worker thread is STILL alive
            # (e.g. Stop was pressed but the old thread hadn't finished yet).
            if self.automation_thread and self.automation_thread.is_alive():
                messagebox.showwarning(
                    "Still Finishing",
                    "The previous run is still stopping. Please wait a moment and try again."
                )
                return

            # Check if Live Monitor is running
            if hasattr(self.uploader, 'auto_check_enabled') and self.uploader.auto_check_enabled:
                messagebox.showwarning(
                    "Warning",
                    "Please stop Live Monitor before starting regular automation!"
                )
                return

            # Update backend interval from GUI before starting
            try:
                gui_interval = int(self.interval_var.get())
                if gui_interval >= 1:
                    self.uploader.channel_interval_minutes = gui_interval
            except:
                pass  # Use existing value if GUI value invalid

            # RESET to first channel when starting automation
            if self.uploader:
                self.uploader.current_channel_index = 0
                self.uploader.channels_processed_this_run = 0
                self.uploader.processed_videos_this_run = []
                self.uploader.save_state()

            self.is_running = True
        finally:
            self.start_lock.release()

        # Reset backend stop flag
        if self.uploader:
            self.uploader.stop_requested = False

        self.btn_start.config(state=tk.DISABLED, bg='#95a5a6')
        self.btn_stop.config(state=tk.NORMAL, bg=self.error)
        self.status_label.config(text="● Running", fg=self.success)

        self.log("🚀 Starting automation...", 'success')
        self.log(f"⏱️  Upload interval: {self.uploader.channel_interval_minutes} minutes", 'info')

        def automation_loop():
            class RealTimeLogger:
                def __init__(self, log_func):
                    self.log_func = log_func
                    self.buffer = ""
                    self.encoding = 'utf-8'

                def write(self, text):
                    # Handle unicode properly - replace problematic characters
                    if isinstance(text, bytes):
                        text = text.decode('utf-8', errors='replace')
                    else:
                        text = str(text).encode('utf-8', errors='replace').decode('utf-8')

                    self.buffer += text
                    while '\n' in self.buffer:
                        line, self.buffer = self.buffer.split('\n', 1)
                        if line.strip():
                            self.log_func(line, 'info')

                def flush(self):
                    if self.buffer.strip():
                        self.log_func(self.buffer, 'info')
                        self.buffer = ""

            logger = RealTimeLogger(self.log)
            old_stdout = sys.stdout

            # Get phase selection (default to phase2)
            phase_mode = self.phase_mode.get() if hasattr(self, 'phase_mode') else 'phase2'

            try:
                while self.is_running:
                    sys.stdout = logger

                    channel = self.uploader.get_next_channel()

                    if not channel:
                        sys.stdout = old_stdout
                        self.log("✅ Cycle complete - all channels processed!", 'success')
                        self.log("🔄 Starting next cycle...", 'info')
                        # Reset to start next cycle immediately
                        self.uploader.current_channel_index = 0
                        self.uploader.channels_processed_this_run = 0
                        self.uploader.save_state()
                        continue

                    # SINGLE mode: upload only 1 video per channel, then rotate
                    success = self.uploader.process_channel(channel, mode='single', phase_mode=phase_mode)

                    sys.stdout = old_stdout
                    logger.flush()

                    self.uploader.move_to_next_channel()
                    self.root.after(0, self.refresh_all_data)

                    if success:
                        self.log(f"⏳ Waiting {self.uploader.channel_interval_minutes} min before next channel...", 'info')
                        self._interruptible_sleep(self.uploader.channel_interval_minutes * 60)
                    else:
                        # Still wait the interval even if no video uploaded
                        self._interruptible_sleep(self.uploader.channel_interval_minutes * 60)

            except Exception as e:
                sys.stdout = old_stdout
                self.log(f"❌ Error: {e}", 'error')
            finally:
                sys.stdout = old_stdout

        self.automation_thread = threading.Thread(target=automation_loop, daemon=True)
        self.automation_thread.start()

    def stop_automation(self):
        """Stop automation"""
        self.is_running = False
        self.selective_mode = False

        # Tell backend to stop processing
        if self.uploader:
            self.uploader.stop_requested = True

        # CRITICAL: Wait for the automation thread to actually finish.
        # The worker's sleeps are now interruptible (checked every 1s), so
        # unless it's mid-upload this ends quickly. If it's mid-upload give
        # it a window to complete; if it's still alive afterwards, keep
        # polling in the background and finalize the UI once it truly exits.
        if self.automation_thread and self.automation_thread.is_alive():
            self.log("⏳ Waiting for automation thread to finish...", 'warning')
            self.automation_thread.join(timeout=30)
            if self.automation_thread.is_alive():
                self.log("⚠️  Thread still running (mid-flight) - halting in background", 'warning')
                self.root.after(1000, self._finalize_stop_ui)
                return

        self._finalize_stop_ui()

    def _finalize_stop_ui(self):
        """Reset the Start/Stop UI once the worker thread has fully exited."""
        if self.automation_thread and self.automation_thread.is_alive():
            self.root.after(1000, self._finalize_stop_ui)
            return
        self.automation_thread = None
        self.btn_start.config(state=tk.NORMAL, bg=self.success)
        self.btn_stop.config(state=tk.DISABLED, bg='#95a5a6')
        self.status_label.config(text="● Stopped", fg=self.warning)
        self.log("⏸️  Automation stopped", 'warning')

    def process_selected_channels(self):
        """Open channel selection dialog and process selected channels"""
        if not self.uploader:
            messagebox.showerror("Error", "Backend not initialized!")
            return

        if not self.channels_config:
            messagebox.showerror("Error", "No channels configured!")
            return

        # CRITICAL: Check if already running OR if thread is still alive (prevents race condition!)
        if self.is_running or (self.automation_thread and self.automation_thread.is_alive()):
            messagebox.showwarning("Warning", "Automation is already running! Please stop it first and wait for it to finish.")
            return

        # Show channel selection dialog
        dialog = ChannelSelectionDialog(self.root, self.channels_config)
        result = dialog.show()

        if not result:
            self.log("❌ Channel selection cancelled", 'warning')
            return

        self.selected_channels = result['channels']
        self.upload_mode = result['mode']

        # Update backend interval from GUI before starting
        try:
            gui_interval = int(self.interval_var.get())
            if gui_interval >= 1:
                self.uploader.channel_interval_minutes = gui_interval
        except:
            pass  # Use existing value if GUI value invalid

        # Get phase selection
        phase_mode = self.phase_mode.get()

        self.log(f"📺 Selected {len(self.selected_channels)} channels", 'info')
        self.log(f"🎯 Mode: {self.upload_mode.upper()}", 'info')
        self.log(f"📋 Phase: {phase_mode.upper()}", 'info')
        self.log(f"⏱️  Upload interval: {self.uploader.channel_interval_minutes} minutes", 'info')

        # Start processing
        self.is_running = True
        self.selective_mode = True

        # Reset backend stop flag
        if self.uploader:
            self.uploader.stop_requested = False

        self.btn_start.config(state=tk.DISABLED, bg='#95a5a6')
        self.btn_stop.config(state=tk.NORMAL, bg=self.error)
        self.status_label.config(text="● Running (Selective)", fg=self.accent)

        if self.upload_mode == 'single':
            self.log("📤 Starting SINGLE mode upload...", 'success')
            self.process_single_mode(phase_mode)
        else:
            self.log("🔄 Starting CONTINUOUS mode upload...", 'success')
            self.process_continuous_mode(phase_mode)

    def process_single_mode(self, phase_mode='phase2'):
        """Process one video from each selected channel"""
        def process():
            class RealTimeLogger:
                def __init__(self, log_func):
                    self.log_func = log_func
                    self.buffer = ""
                    self.encoding = 'utf-8'

                def write(self, text):
                    # Handle unicode properly - replace problematic characters
                    if isinstance(text, bytes):
                        text = text.decode('utf-8', errors='replace')
                    else:
                        text = str(text).encode('utf-8', errors='replace').decode('utf-8')

                    self.buffer += text
                    while '\n' in self.buffer:
                        line, self.buffer = self.buffer.split('\n', 1)
                        if line.strip():
                            self.log_func(line, 'info')

                def flush(self):
                    if self.buffer.strip():
                        self.log_func(self.buffer, 'info')
                        self.buffer = ""

            logger = RealTimeLogger(self.log)
            old_stdout = sys.stdout

            try:
                for ch_id in self.selected_channels:
                    if not self.is_running:
                        break

                    channel = self.channels_config.get(ch_id)
                    if not channel or not channel.get('enabled'):
                        continue

                    sys.stdout = logger
                    # Pass mode and phase_mode to backend
                    success = self.uploader.process_channel(channel, mode=self.upload_mode, phase_mode=phase_mode)
                    sys.stdout = old_stdout
                    logger.flush()

                    self.root.after(0, self.refresh_all_data)

                    if success and self.is_running:
                        self.log(f"⏳ Waiting {self.uploader.channel_interval_minutes} min...", 'info')
                        self._interruptible_sleep(self.uploader.channel_interval_minutes * 60)

                sys.stdout = old_stdout
                self.log("✅ Single mode complete!", 'success')
                self.root.after(0, self.stop_automation)

            except Exception as e:
                sys.stdout = old_stdout
                self.log(f"❌ Error: {e}", 'error')
                import traceback
                self.log(traceback.format_exc(), 'error')
                self.root.after(0, self.stop_automation)
            finally:
                sys.stdout = old_stdout

        self.automation_thread = threading.Thread(target=process, daemon=True)
        self.automation_thread.start()

    def process_continuous_mode(self, phase_mode='phase2'):
        """Keep uploading 1 video per channel in rotation, cycling forever"""
        def process():
            class RealTimeLogger:
                def __init__(self, log_func):
                    self.log_func = log_func
                    self.buffer = ""
                    self.encoding = 'utf-8'

                def write(self, text):
                    # Handle unicode properly - replace problematic characters
                    if isinstance(text, bytes):
                        text = text.decode('utf-8', errors='replace')
                    else:
                        text = str(text).encode('utf-8', errors='replace').decode('utf-8')

                    self.buffer += text
                    while '\n' in self.buffer:
                        line, self.buffer = self.buffer.split('\n', 1)
                        if line.strip():
                            self.log_func(line, 'info')

                def flush(self):
                    if self.buffer.strip():
                        self.log_func(self.buffer, 'info')
                        self.buffer = ""

            logger = RealTimeLogger(self.log)
            old_stdout = sys.stdout
            channel_index = 0

            try:
                while self.is_running:
                    ch_id = self.selected_channels[channel_index % len(self.selected_channels)]
                    channel = self.channels_config.get(ch_id)

                    if not channel or not channel.get('enabled'):
                        channel_index += 1
                        continue

                    sys.stdout = logger
                    # SINGLE mode: upload only 1 video, then rotate
                    success = self.uploader.process_channel(channel, mode='single', phase_mode=phase_mode)
                    sys.stdout = old_stdout
                    logger.flush()

                    self.root.after(0, self.refresh_all_data)

                    channel_index += 1

                    # Check if we completed one full cycle
                    if channel_index % len(self.selected_channels) == 0:
                        sys.stdout = old_stdout
                        self.log("✅ Cycle complete - all selected channels processed!", 'success')
                        self.log("🔄 Starting next cycle...", 'info')

                    if self.is_running:
                        self.log(f"⏳ Waiting {self.uploader.channel_interval_minutes} min before next channel...", 'info')
                        self._interruptible_sleep(self.uploader.channel_interval_minutes * 60)

                sys.stdout = old_stdout
                self.log("⏸️  Continuous mode stopped", 'warning')

            except Exception as e:
                sys.stdout = old_stdout
                self.log(f"❌ Error: {e}", 'error')
                import traceback
                self.log(traceback.format_exc(), 'error')
            finally:
                sys.stdout = old_stdout

        self.automation_thread = threading.Thread(target=process, daemon=True)
        self.automation_thread.start()

    # ═══════════════════════════════════════════════════════════
    # LIVE MONITOR METHODS
    # ═══════════════════════════════════════════════════════════

    def toggle_live_monitor(self):
        """Toggle Live Monitor on/off"""
        if not self.uploader:
            messagebox.showerror("Error", "Backend not initialized!")
            return

        if not hasattr(self.uploader, 'start_auto_check'):
            messagebox.showerror(
                "Backend Error",
                "Backend doesn't support Live Monitor!\n\n"
                "Please replace tiktok_youtube_uploader.py with the enhanced version."
            )
            return

        if self.uploader.auto_check_enabled:
            # Stop Live Monitor
            self.uploader.stop_auto_check()
            self.monitor_status_label.config(text="🔴 Stopped", fg=self.warning)
            self.btn_monitor_start.config(state=tk.NORMAL)
            self.btn_monitor_stop.config(state=tk.DISABLED)
            self.btn_start.config(state=tk.NORMAL)  # Re-enable regular automation
            self.log("🔴 Live Monitor stopped", 'warning')
        else:
            # Check if regular automation is running
            if self.is_running:
                messagebox.showwarning(
                    "Warning",
                    "Please stop regular automation before starting Live Monitor!"
                )
                return

            # Validate and set interval
            try:
                interval = int(self.monitor_interval_var.get())
                if interval < 1 or interval > 60:
                    messagebox.showerror("Invalid Interval", "Interval must be between 1 and 60 minutes!")
                    return
            except ValueError:
                messagebox.showerror("Invalid Input", "Please enter a valid number for interval!")
                return

            # Set interval in backend
            self.uploader.set_auto_check_interval(interval)

            # Set fetch hours from GUI (Upload Controls)
            try:
                fetch_hours = int(self.fetch_hours_var.get())
                if fetch_hours < 0:
                    fetch_hours = 0
                self.uploader.fetch_hours_limit = fetch_hours
            except:
                pass  # Use default

            # Set log callback to redirect auto-check logs to GUI
            def log_callback(message):
                self.root.after(0, lambda: self.log(message, 'info'))

            self.uploader.set_auto_check_log_callback(log_callback)

            # Start Live Monitor
            success = self.uploader.start_auto_check()

            if success:
                self.monitor_status_label.config(text="🟢 ACTIVE", fg=self.success)
                self.btn_monitor_start.config(state=tk.DISABLED)
                self.btn_monitor_stop.config(state=tk.NORMAL)
                self.btn_start.config(state=tk.DISABLED)  # Disable regular automation

                interval = int(self.monitor_interval_var.get())
                self.log(f"🟢 Live Monitor started - checking every {interval} min", 'success')

    def update_monitor_stats(self):
        """Update Live Monitor statistics display"""
        if not self.uploader:
            return

        if not hasattr(self.uploader, 'get_auto_check_stats'):
            return

        try:
            stats = self.uploader.get_auto_check_stats()

            # Update labels with actual values
            checks = stats.get('total_checks', 0)
            found = stats.get('videos_found', 0)
            uploaded = stats.get('videos_uploaded', 0)

            self.monitor_checks_label.config(text=str(checks))
            self.monitor_found_label.config(text=str(found))
            self.monitor_uploaded_label.config(text=str(uploaded))

        except Exception as e:
            # Log error for debugging
            print(f"Monitor stats update error: {e}")

    def manual_check_selected(self):
        """Manually check selected channels for new videos"""
        if not self.uploader:
            messagebox.showerror("Error", "Backend not initialized")
            return

        # Show channel selection dialog
        dialog = ChannelSelectionDialog(self.root, self.channels_config)
        result = dialog.show()

        if not result:
            return  # User cancelled

        # Get selected channels
        selected_channel_ids = result['channels']
        mode = result['mode']  # 'single' or 'continuous'

        selected_configs = [self.channels_config[ch_id] for ch_id in selected_channel_ids]

        self.log(f"🔎 Manual check for {len(selected_configs)} channel(s) - {mode.upper()} mode", 'info')

        def check_thread():
            import sys

            # Redirect stdout to GUI
            class StdoutRedirector:
                def __init__(self, log_func):
                    self.log_func = log_func

                def write(self, text):
                    if text.strip():
                        self.log_func(text.rstrip())

                def flush(self):
                    pass

            old_stdout = sys.stdout
            sys.stdout = StdoutRedirector(lambda msg: self.root.after(0, lambda: self.log(msg, 'info')))

            # Set up logging callback
            def log_callback(message):
                self.root.after(0, lambda: self.log(message, 'info'))

            old_callback = self.uploader.auto_check_log_callback
            self.uploader.set_auto_check_log_callback(log_callback)

            # Track stats for this manual check
            total_found = 0
            total_uploaded = 0

            try:
                for channel in selected_configs:
                    self.log(f"\n📺 Checking: {channel['channel_name']}", 'info')

                    source_type = channel.get('source_type', 'tiktok')

                    if source_type == 'tiktok':
                        # Fetch TikTok videos
                        videos = self.uploader.fetch_tiktok_videos(channel['tiktok_username'])

                        # Use fetch_hours from GUI (Upload Controls)
                        try:
                            fetch_hours = int(self.fetch_hours_var.get())
                            if fetch_hours < 0:
                                fetch_hours = 0  # 0 means all videos
                        except:
                            fetch_hours = 72  # Default fallback

                        recent_videos = self.uploader.filter_recent_videos(videos, hours=fetch_hours)
                        self.log(f"  Found {len(recent_videos)} recent videos", 'info')

                        videos_uploaded_for_channel = 0
                        for video in recent_videos:
                            video_id = video['id']

                            if not self.uploader.check_duplicate_in_sheet(channel['sheet_tab_name'], video_id):
                                total_found += 1  # Count new videos found
                                # Build video info
                                username = video.get('author', {}).get('unique_id') or channel['tiktok_username']
                                video_info = {
                                    'video_id': video_id,
                                    'title': video.get('title') or video.get('desc', 'Untitled'),
                                    'caption': video.get('desc') or video.get('title', ''),
                                    'mp4_url': video.get('play') or video.get('download_addr', ''),
                                    'tiktok_url': f"https://www.tiktok.com/@{username}/video/{video_id}",
                                    'tiktok_upload_time': datetime.fromtimestamp(video.get('create_time', 0)).strftime('%d-%b-%Y %I:%M %p')
                                }

                                self.log(f"\n  🆕 NEW Video: {video_info['title'][:50]}", 'info')
                                self.log(f"  🆔 ID: {video_id}", 'info')
                                self.log(f"  🔗 URL: {video_info['tiktok_url']}", 'info')

                                # Download
                                self.log(f"  📥 Downloading...", 'info')
                                video_data = self.uploader.download_video_binary(video_info['mp4_url'], video_id)
                                if not video_data:
                                    self.log(f"  ❌ Download failed", 'error')
                                    continue

                                self.log(f"  ✅ Downloaded {len(video_data) / (1024*1024):.2f} MB", 'success')

                                # Calculate schedule
                                scheduled_time = self.uploader.calculate_schedule_time(channel['sheet_tab_name'])

                                # Upload
                                self.log(f"  📤 Uploading to YouTube...", 'info')
                                youtube_data = self.uploader.upload_to_youtube(channel, video_data, video_info, scheduled_time)
                                if not youtube_data:
                                    self.log(f"  ❌ Upload failed", 'error')
                                    continue

                                # Log to sheet
                                self.uploader.log_to_sheet(channel['sheet_tab_name'], video_info, youtube_data, scheduled_time, 'done')

                                total_uploaded += 1  # Count successful uploads
                                videos_uploaded_for_channel += 1

                                upload_completed = datetime.now().strftime('%d-%b-%Y %I:%M %p')
                                self.log(f"  ✅ Upload completed: {upload_completed}", 'success')
                                self.log(f"  📅 Scheduled to publish: {scheduled_time}", 'success')
                                self.log(f"  🔗 YouTube: {youtube_data.get('youtube_url', 'N/A')}", 'info')

                                # Refresh stats after each upload (with small delay for sheets to sync)
                                self.log(f"  🔄 Refreshing stats...", 'info')
                                time.sleep(2)  # Give sheets time to update
                                self.root.after(0, self.refresh_all_data)

                                # In single mode, stop after first video uploaded for this channel
                                if mode == 'single':
                                    self.log(f"  ℹ️  Single mode - moving to next channel", 'info')
                                    break

                                # Wait for next video in continuous mode
                                # Use Live Monitor interval from GUI, not config file
                                try:
                                    interval = int(self.monitor_interval_var.get())
                                except:
                                    interval = self.uploader.channel_interval_minutes
                                self.log(f"  ⏳ Waiting {interval} min before next video...", 'warning')
                                self._interruptible_sleep(interval * 60)
                    else:
                        # Local folder check
                        self.log(f"  📁 Checking local folder...", 'info')
                        local_videos = self.uploader.find_local_videos_in_sheet(
                            channel['sheet_tab_name'],
                            channel.get('video_source_folder', '')
                        )
                        self.log(f"  Found {len(local_videos)} local videos", 'info')
                        total_found += len(local_videos)  # Count local videos found

                        for row_index, video_info, video_file_path in local_videos:
                            self.log(f"  📥 Processing: {video_info.get('video_id')}", 'info')
                            success = self.uploader.process_local_video(
                                channel, channel['sheet_tab_name'], row_index, video_info, video_file_path
                            )
                            if success:
                                total_uploaded += 1  # Count successful local uploads

                                # In single mode, stop after first video
                                if mode == 'single':
                                    self.log(f"  ℹ️  Single mode - moving to next channel", 'info')
                                    break

                                # Use Live Monitor interval from GUI
                                try:
                                    interval = int(self.monitor_interval_var.get())
                                except:
                                    interval = self.uploader.channel_interval_minutes
                                self._interruptible_sleep(interval * 60)

                # Update Live Monitor stats
                if hasattr(self.uploader, 'auto_check_stats'):
                    self.uploader.auto_check_stats['total_checks'] += 1
                    self.uploader.auto_check_stats['videos_found'] += total_found
                    self.uploader.auto_check_stats['videos_uploaded'] += total_uploaded

                self.log(f"✅ Manual check complete! Found: {total_found}, Uploaded: {total_uploaded}", 'success')
                self.root.after(0, self.refresh_all_data)

            except Exception as e:
                self.log(f"❌ Error during manual check: {e}", 'error')
                import traceback
                self.log(traceback.format_exc(), 'error')
            finally:
                self.uploader.set_auto_check_log_callback(old_callback)
                sys.stdout = old_stdout  # Restore stdout

        threading.Thread(target=check_thread, daemon=True).start()

    def start_monitor_stats_update(self):
        """Start background thread to update monitor stats"""
        def update_loop():
            while True:
                # Always try to update stats (method handles when backend not ready)
                try:
                    self.root.after(0, self.update_monitor_stats)
                except:
                    pass

                time.sleep(2)  # Update every 2 seconds

        self.monitor_update_thread = threading.Thread(target=update_loop, daemon=True)
        self.monitor_update_thread.start()

    # ═══════════════════════════════════════════════════════════
    # END LIVE MONITOR METHODS
    # ═══════════════════════════════════════════════════════════



def main():
    """Main entry point"""
    print("="*70)
    print("TikTok to YouTube Auto Uploader GUI")
    print("="*70)

    root = tk.Tk()
    app = TikTokYouTubeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
