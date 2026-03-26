# NOAA JetStream — Cloud Data Management Transfer System
<img align="right" src="https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/jetstream_logo_400px.png" alt="jetstream" width="250">

A comprehensive web-based application for managing Google Cloud Storage uploads with features including job queuing, real-time analytics, cloud bucket analysis, and batch processing capabilities.

### Features

- **Upload Management**
- **Analytics & Monitoring**
- **Cloud Bucket Analysis**
- **File Filtering**
- **Web Dashboard**

## Screenshots

| Dashboard | Upload Jobs | Analytics |
|-----------|-------------|----------|
| ![Home](https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/screenshot_home.png) | ![Uploads](https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/screenshot_uploads.png) | ![Analytics](https://github.com/MichaelAkridge-NOAA/jetstream/raw/main/docs/screenshot_analytics.png) |

### Prerequisites

- **Python 3.9+**
- **Google Cloud SDK** (includes gsutil) — for cloud upload features
- **Permissions** to target GCS buckets
---
### Google Cloud Setup

Required only for cloud upload features:
```bash
# Install Google Cloud SDK
# Download from: https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth login --no-launch-browser
gcloud auth application-default login --no-launch-browser

# Verify access (optional)
gsutil ls
gcloud auth list
```

### Installation
#### Option 1: Install from PyPI (Recommended)

```bash
# Install core package
pip install noaa-jetstream

# Or install with Google Cloud support
pip install noaa-jetstream[cloud]

# Or install with desktop shortcuts
pip install noaa-jetstream[shortcuts]

# Or install everything
pip install noaa-jetstream[all]
```

#### Option 2: Install from Source (Development)

```bash
# Clone the repository
git clone https://github.com/MichaelAkridge-NOAA/jetstream.git
cd jetstream

# Install in development mode
pip install -e .

# Or with all optional features
pip install -e ".[all]"
```

---

## Starting the Application

### If Installed via pip

```bash
# Start the server (opens browser automatically)
jetstream

# view options
jetstream --help
# With custom options
jetstream --port 9000
jetstream --host 127.0.0.1 --port 8080
jetstream --no-browser
jetstream --log-level debug
```

### If Running from Source

```bash
# Using the CLI
python main.py

# Or with the diagnostic startup script
python start.py

# Or directly with uvicorn
python -m uvicorn jetstream.main:app --reload
```

The application will start on **http://localhost:8000** and automatically open in your default browser.

### Desktop Shortcuts

Create desktop and Start Menu shortcuts for easy access:

```bash
# Install with shortcuts support
pip install noaa-jetstream[shortcuts]

# Create shortcuts
jetstream-create-shortcuts

# Remove shortcuts
jetstream-remove-shortcuts
```

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

----------
#### Disclaimer
This repository is a scientific product and is not official communication of the National Oceanic and Atmospheric Administration, or the United States Department of Commerce. All NOAA GitHub project content is provided on an 'as is' basis and the user assumes responsibility for its use. Any claims against the Department of Commerce or Department of Commerce bureaus stemming from the use of this GitHub project will be governed by all applicable Federal law. Any reference to specific commercial products, processes, or services by service mark, trademark, manufacturer, or otherwise, does not constitute or imply their endorsement, recommendation or favoring by the Department of Commerce. The Department of Commerce seal and logo, or the seal and logo of a DOC bureau, shall not be used in any manner to imply endorsement of any commercial product or activity by DOC or the United States Government.

## License
See the [LICENSE.md](./LICENSE.md) for details
