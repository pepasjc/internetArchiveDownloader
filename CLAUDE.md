# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PyQt6-based GUI application for downloading files from the Internet Archive with support for multi-segment/parallel downloads, pause/resume functionality, and persistent download queues.

## Running the Application

```bash
python main.py
```

The application requires:
- PyQt6
- internetarchive
- requests

## Code Architecture

### Module Organization

The codebase is split into 5 focused modules:

- **main.py** - Main application (`InternetArchiveGUI` class) containing all GUI logic, event handlers, and application state
- **models.py** - Data models (`DownloadStatus` enum, `DownloadItem` class)
- **threads.py** - Download threading (`SegmentDownloadThread`, `SingleDownloadThread`, `DownloadManager`)
- **utils.py** - Utility functions (logging toggle, size formatting)
- **translations.py** - Bilingual string dictionaries (Portuguese BR and English)

### Threading Architecture

Downloads use a three-tier threading model:

1. **DownloadManager** (QThread) - Queue manager that:
   - Maintains a Queue of pending downloads
   - Enforces max concurrent downloads limit
   - Spawns SingleDownloadThread for each download

2. **SingleDownloadThread** (QThread) - Per-file download coordinator that:
   - Decides between single or multi-segment download based on `download_item.segments`
   - For multi-segment: creates N SegmentDownloadThread instances and monitors them
   - Handles pause/resume/cancel for all child threads
   - Emits `progress_updated` and `status_changed` signals to GUI

3. **SegmentDownloadThread** (QThread) - Downloads one byte range:
   - Saves to temporary `.part{N}` files
   - Uses shared dict + mutex for thread-safe progress reporting
   - Supports resume from partial `.part{N}` files

**Signal flow**: SegmentDownloadThread → (shared dict) → SingleDownloadThread → (PyQt signals) → InternetArchiveGUI

### Download Persistence

Download state is automatically saved to QSettings (JSON format) when status changes to COMPLETED, ERROR, or PAUSED.

Key serialization details:
- `downloaded_bytes` and `total_bytes` saved as strings to avoid JSON integer overflow
- `date_added` and `date_completed` saved as ISO 8601 strings
- `unique_id` is a UUID string for tracking across sessions
- Status deserialization: WAITING and DOWNLOADING are restored as PAUSED (requires manual resume)
- `DownloadItem.from_dict()` provides backwards compatibility for old saved data

**Important**: Downloads persist indefinitely until user clicks "Clear Completed" - they are NOT filtered out on save.

### File Opening Integration

The download table supports:
- **Right-click on filename**: Context menu with "Open File" and "Open Folder" (only shown if file/folder exists)
- **Double-click on filename**: Opens the file with system default application

Cross-platform file opening via `platform.system()`:
- Windows: `os.startfile()`
- macOS: `subprocess.run(['open', ...])`
- Linux: `subprocess.run(['xdg-open', ...])`

### Translation System

The `Translator` class in translations.py manages bilingual strings:
- Access translations via `self.t('key_name')` or `self.t('key_with_args', arg1=value1)`
- Language preference stored in QSettings as 'language'
- All user-facing strings must have entries in both `TRANSLATIONS_PT` and `TRANSLATIONS_EN`
- Language changes require restart

## Important Implementation Notes

### Multi-segment Download Flow

1. File divided into N equal byte ranges (last segment gets remainder bytes)
2. Each segment downloaded to `{dest_path}.part{N}` file
3. Progress aggregated from all segment threads via shared dict + mutex
4. On completion, segments merged into final file and `.part{N}` files deleted
5. If cancelled/paused: `.part{N}` files preserved for resume

### Thread Safety Patterns

- SingleDownloadThread uses `QMutex` + `QWaitCondition` for pause coordination
- Segment progress dict protected by dedicated `QMutex`
- Cancel flag (`is_cancelled`) checked in download loops
- GUI updates via PyQt signals only (never direct GUI manipulation from threads)

### QSettings Keys

- `downloads_json` - JSON string of all downloads
- `default_download_folder` - Default destination folder
- `max_concurrent` - Max simultaneous downloads (default: 3)
- `segments_per_file` - Connections per file (default: 4)
- `enable_logging` - Console logging toggle
- `language` - UI language ('pt' or 'en')
- `recent_identifiers` - List of identifier search history (max 20 items)
- `recent_searches` - List of archive search query history (max 20 items)

### Styling Considerations

QSpinBox controls must NOT have `padding` in stylesheets - it blocks up/down arrow buttons. Use `font-size` only.

### Tooltip Metadata

Filename column tooltips display:
- Shortened unique_id (first 8 chars)
- Date added (YYYY-MM-DD HH:MM:SS)
- Date completed (if applicable)

Updated when download completes to add completion date.
