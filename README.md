# Multi-channel Video Library — v2

One permanent library of videos/thumbnails, one master Videos tab, one output tab per YouTube channel, and local SQLite upload history. No repeated copies and no moving media after upload.

## Install / start

Run `setup\setup.bat`, then `RUN.bat`. Python 3.10+ is required. Setup creates a local `.venv`, reuses compatible installed dependencies and installs only missing requirements. After moving this app to another drive/PC, rerun setup. Configure credentials and source paths for that PC.

## Upgrade from the previous uploader

1. Stop the old window and reopen RUN.bat.
2. The first run migrates `broadcast_state.json` into `library.sqlite3` automatically. Successful uploads and uncertain attempts are preserved per channel; the old JSON remains as an export for recovery.
3. Set the shared Library folder. The optional Previous Uploaded folder is also indexed, without moving its files back or duplicating them. Your current files can stay in FernStyle and FernStyle/Uploaded.
4. Enable Google Sheets through the original source-channel settings (sheet-free mode must be off), and keep your spreadsheet URL configured.
5. Use **Sync library / Sheets (no video uploads)** before starting uploads. It discovers local files, imports title/description metadata from existing configured source tabs, and populates the new master/output tabs. Existing legacy tabs such as Multi remain untouched.
6. Start Automation or Process Selected Channels. Every video is processed across the selected destinations before moving to the next video. Its media files remain permanently available.

## Excel / Google Sheets template

`templates/MultiUploader_Template.xlsx` contains the exact header schema plus instructions and current channel tab names. Import it as Google Sheets, or copy the tabs. Keep row 1 headers and tab names exactly. Delete the Sample Video example row before production. You can also let **Sync library / Sheets** create and populate the tabs automatically in your existing spreadsheet.

**Videos** columns: `video_id`, `filename`, `title`, `description`, `thumbnail`, `source_url`.

- Enter only `video_id`, e.g. My Video. Leave `filename` blank: the app finds My Video.mp4 automatically (also supported video extensions), then fills the filename itself. No full video path is required in the Sheet.
- Edit the master title and description to control metadata. Thumbnail detection uses the same-name PNG/JPG/JPEG next to the actual video file. Keep only one matching thumbnail.
- Local discovery automatically adds files not yet in Videos. Different videos must not share the same filename stem.
- Internal content hashes recognize identical video data; hashes are never used as Sheet video IDs.

Channel tabs are generated as `Uploads - <short channel name> - <channel ID suffix>`. Names fit both Excel and Google Sheets. The stable tab mapping is stored in SQLite. Each tab has these columns:

`video_id`, `filename`, `title`, `description`, `thumbnail`, `yt_video_url`, `youtube_id`, `upload_time`, `schedual_time`, `status`, `thumbnail_status`, `error`.

Output tabs are mirrors, not the authority for deciding which videos to upload. Editing an uploaded/status cell will not reset a real upload. SQLite saves success before attempting Sheet sync; if Sheets fails, later runs synchronize the existing results without re-uploading videos. Keep a working private database to avoid duplicates. Only history attributable to known channel IDs in the legacy JSON migrates automatically; shared cells alone cannot reliably prove channel ownership.

## Adding channels

On the first library run for a new destination, choose **Yes** to include every existing/future video, **No** to accept only files discovered after that initial scan, or Cancel to stop. Existing channels with migrated history include the existing library and skip their successful uploads. Use **Include existing videos for selected channels** to change a future-only channel to backfill later. Video upload and thumbnail completion are tracked separately for every channel.

## Thumbnail behavior

Same-name PNG/JPG/JPEG thumbnails are set after YouTube processing. Oversized images are compressed in memory below the installed client limit; originals stay unchanged. Thumbnail errors are recorded but do not block subsequent destinations/videos. Later runs retry missing thumbnails without uploading videos again.

## Source modes / safety

The first enabled channel supplies TikTok username and sheet-free setting. The shared Library folder can be changed independently in the new library controls. TikTok downloads are staged locally and use this same permanent-library workflow. Phase 1 / Sync indexes and syncs without video uploads; Phase 2/Both run the upload queue. Select Single to process one video needing uploads, or continuous/all for all pending videos. Quota-blocked or uncertain destinations are left pending; other destinations continue. Review uncertain results against YouTube before allowing retries.

## Private files / backups

The repository excludes `.app_password`, OAuth tokens, `youtube_credentials`, private channel/config JSON, `library.sqlite3` and its WAL/SHM files, legacy history and backups. For another PC, stop the app first, then transfer your private credentials/config/history/database separately. A fresh clone has no accounts or prior upload history. Back up the database while the app is closed; do not delete it just to resolve an error.
