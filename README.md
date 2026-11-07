# Multi-channel Video Uploader

Upload one video to every enabled destination before moving to the next video. Based on the existing TikTok/YouTube GUI with per-channel metadata, playlists, scheduling, Google Sheets and a shared video source (first enabled channel).

## Install on Windows

1. Clone/download this repo into the folder/drive where you want the tool to live.
2. Run `setup\setup.bat`. Install Python 3.10+ with pip and Tcl/Tk from python.org if prompted, then rerun setup.
3. Setup creates `.venv` inside this folder and reuses compatible system packages. Already-satisfied dependencies are skipped; it does not force upgrades.
4. Run `RUN.bat`. Configure your own channel credentials, Sheets URL, video source and uploaded folder in the GUI.

No fixed drive letter or admin installation is required. To use another drive/PC, copy the app there and rerun `setup\setup.bat`. A copied virtual environment is recreated for its new location; the old environment is preserved. Existing channel settings are retained: update any video/credentials paths that do not exist on the new PC. Python and account access must be available on that PC. Setup needs internet for missing dependencies; it reports failure if installation cannot finish.

Put OAuth client JSONs and your Sheets `service_account.json` in `youtube_credentials`. Authenticate each YouTube channel yourself. Private configuration, passwords, tokens, credentials, downloaded media, backups and upload state are excluded from Git. A fresh clone has no configured channels or account access. Copy these private files separately only when you intend to reuse your own accounts/history.

## Shared source and Sheets

The first enabled channel supplies the shared source folder or TikTok username. In local Sheet mode, column A is the exact video filename without its extension, e.g. `My Video` matches `My Video.mp4`. Existing rows supply metadata and are updated after the uploads; no generated hash IDs are written into the Sheet. Channels sharing the same worksheet get all their YouTube links/IDs retained in that row. Sheet-free folder mode does not require Sheets.

Place one matching `My Video.jpg`, `.jpeg` or `.png` beside the video to automatically set it as the thumbnail on every destination. Video processing must finish first. Failed thumbnails can be retried without reuploading the video. Once complete, the video and matching image move to Uploaded. Uploaded can be a subfolder of Source.

Local state records successful channel uploads. An uncertain upload requires checking YouTube before retrying. Keep the private state when moving an existing workflow to avoid repeat uploads. Network failures and thumbnail permissions can still require user attention.
