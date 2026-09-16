# NOAA JetStream — Cloud Data Management Transfer System
<img align="right" src="https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/jetstream_logo_400px.png" alt="jetstream" width="250">

A comprehensive web-based application for managing Google Cloud Storage uploads and Google Drive transfers, with features including job queuing, real-time analytics, and batch processing capabilities.

### Features

- **Upload Management** — queue-backed GCS uploads with retry, scheduling, and no-clobber support
- **Analytics & Monitoring** — real-time job stats, file-type breakdown, activity timeline
- **Cloud Bucket Analysis** — browse and analyze GCS bucket contents
- **Native Google Drive Upload** — OAuth-authenticated upload and folder sync to Google Drive
- **File Filtering** — include/exclude patterns for uploads
- **Web Dashboard** — browser-based UI at `http://localhost:8000`
- **Terminal UI (TUI)** — full-featured htop-style dashboard for terminals and remote sessions

## Screenshots

| Dashboard | Upload Jobs | Analytics |
|-----------|-------------|----------|
| ![Home](https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/screenshot_home.png) | ![Uploads](https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/screenshot_uploads.png) | ![Analytics](https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/screenshot_analytics.png) |


### Prerequisites

- **Python 3.9+** - 
- **Google Cloud SDK** (includes gsutil) — for GCS upload features
- **Permissions** to target GCS buckets
---
### Google Cloud Setup
In a terminal window run the following command:
```bash
# Install Google Cloud SDK
# Download from: https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth login
```
> **⚠️ Important:** If you encounter a `Reauthentication required.` error, Google requires rotating or re-authenticating credentials at unspecified times. (~ every 16hrs)
> 
> To fix this, simply login again

## Installation
In a python, conda promt window run the following command:
```bash
pip install noaa-jetstream
```
## Upgrade/Update Jetstream
In a python, conda promt window run the following command:
```
pip install --no-cache --upgrade noaa-jetstream
```

## Starting the Application

### If Installed via pip

```bash
# Start the server (opens browser automatically)
jetstream
```
## Install Jetstream Desktop Shortcut
Desktop and Start Menu shortcuts are included with the default install. The shortcut will automatically use the JetStream icon (`icon.ico`) when created.

```bash
# Create desktop + Start Menu shortcut (uses JetStream icon automatically)
jetstream-create-shortcuts

# Remove shortcuts
jetstream-remove-shortcuts
```

Shortcuts launch JetStream directly using the current Python environment and open a terminal window. On Windows a `.lnk` shortcut is created on the desktop and in the Start Menu. On macOS/Linux a `.app`/`.desktop` shortcut is created in Applications.

---

### Troubleshooting Startup Issues

**If the server appears to start but you can't connect:**

1. **Run diagnostics:**
   ```bash
   python diagnose.py
   ```
   
2. **Run with debug logging:**
   ```bash
   jetstream --log-level debug
   # or from source:
   python -m uvicorn jetstream.main:app --reload --log-level debug
   ```
---

## Troubleshooting

**Cannot connect to GCS:**
- Verify authentication: `gcloud auth list`
- Check bucket permissions
- Ensure Application Default Credentials are set

**Jobs stuck in queue:**
- Check queue status in dashboard
- Verify no jobs are blocking the queue
- Restart the application if needed

**Database errors:**
- Delete `jetstream.db` to reset (loses history)
- Check file permissions in application directory

**API not responding:**
- Check if port 8000 is already in use
- View logs in terminal for error messages
- Ensure all dependencies are installed

## Terminal UI (TUI)

JetStream ships a full terminal dashboard — think **htop + ranger + gsutil** — that runs in any terminal or SSH session without a browser.
## Screenshots

| Dashboard | Upload Jobs | Analytics |
|-----------|-------------|----------|
| ![Home](https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/tui_s01.png) | ![Uploads](https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/tui_s02.png) | ![Analytics](https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/tui_s03.png) |

![TUI](./docs/tui_01.gif)

### Launch

```bash
# If installed via pip
jetstream-tui
```

----------
#### Disclaimer
This repository is a scientific product and is not official communication of the National Oceanic and Atmospheric Administration, or the United States Department of Commerce. All NOAA GitHub project content is provided on an 'as is' basis and the user assumes responsibility for its use. Any claims against the Department of Commerce or Department of Commerce bureaus stemming from the use of this GitHub project will be governed by all applicable Federal law. Any reference to specific commercial products, processes, or services by service mark, trademark, manufacturer, or otherwise, does not constitute or imply their endorsement, recommendation or favoring by the Department of Commerce. The Department of Commerce seal and logo, or the seal and logo of a DOC bureau, shall not be used in any manner to imply endorsement of any commercial product or activity by DOC or the United States Government.

## License
See the [LICENSE.md](./LICENSE.md) for details