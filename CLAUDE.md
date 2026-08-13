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

The codebase is split into 7 focused modules:

- **main.py** - Main application (`InternetArchiveGUI` class) containing all GUI logic, event handlers, and application state
- **models.py** - Data models (`DownloadStatus` enum, `DownloadItem` class)
- **threads.py** - Download threading (`SegmentDownloadThread`, `SingleDownloadThread`, `DownloadManager`) plus the global `RateLimiter`
- **themes.py** - Design tokens (`build_tokens`) and the QSS generator (`build_stylesheet`)
- **icons.py** - Vector icons drawn at runtime with QPainter (no asset files)
- **widgets.py** - Custom widgets and item delegates (sidebar, chips, progress/status delegates, speed graph, segment map)
- **utils.py** - Utility functions (logging toggle, size formatting)
- **translations.py** - Bilingual string dictionaries (Portuguese BR and English)

### UI Shell

The window is a sidebar shell, not a tab widget. `initUI` builds:

- `Sidebar` (widgets.py) → drives a `QStackedWidget` (`self.pages`) via `go_to_page(index)`
- Page indices are the module constants `PAGE_DOWNLOADS`, `PAGE_SEARCH`, `PAGE_ITEM`, `PAGE_SETTINGS`
- A status strip at the bottom shows aggregate counters, total speed, ETA and the global speed limit
- Never reference a page by a bare integer — use the constants

The downloads page is a `QSplitter`: table on top, collapsible detail panel (Info / Connections / Speed) below.

### Theming

`themes.build_tokens(mode, accent, density)` returns one dict consumed by both the QSS
(`build_stylesheet`) and every hand-painted widget. `apply_theme()` rebuilds tokens, clears the
icon cache, sets the app-wide stylesheet, and calls `apply_tokens(tokens)` on everything in
`self._themed_widgets`.

**Any new custom-painted widget or delegate must expose `apply_tokens(tokens)` and be appended to
`self._themed_widgets`**, otherwise it keeps stale colors after a theme switch.

Icons are recolored per theme, so `icons.clear_cache()` runs on every theme change.

### Download Table

The table has 8 columns addressed by the `COL_*` constants (`COL_FILE`…`COL_MESSAGE`).

- No per-row widgets. Progress is painted by `ProgressDelegate` reading `ROLE_PROGRESS` /
  `ROLE_STATUS` from the item; status is painted as a pill by `StatusPillDelegate`. Adding a
  `QProgressBar` per row would reintroduce the old scaling problem.
- Row → download lookups go through `ROLE_UID` (a UUID), never the displayed filename.
- Native sorting stays **off**; `sort_download_table` sorts on explicit header clicks and then
  rebuilds `_id_to_row`. Enabling native sorting would reorder rows on every progress tick.
- Filtering (chips + name search) hides rows via `setRowHidden`; it never removes them.
- `_paint_status_row(uid, status, error_msg)` is the single place that writes status into a row.

### Responsive Behavior

`resizeEvent` drives all adaptation:
- < 1000 px: sidebar collapses to icons only
- < 1150 px: toolbar buttons drop their labels (tooltips remain)
- `RESPONSIVE_COLUMNS` hides table columns least-first as width shrinks

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

`progress_updated` carries `segments`: a list of `(downloaded, size)` tuples that feeds the
Connections map in the detail panel. The GUI caches it per uid in `self.segment_snapshots`.

### Global Speed Limit

`threads.GLOBAL_RATE_LIMITER` is a token bucket shared by every download thread; each loop calls
`consume(len(chunk), lambda: self.is_cancelled)` after writing. Set it with
`set_global_rate_limit(bytes_per_second)` (0 = unlimited).

The bucket capacity is `max(rate, nbytes)` — with a plain `rate` capacity, a limit below the 64 KB
chunk size would wait forever for tokens that can never fit.

### Download Persistence

Download state is automatically saved to QSettings (JSON format) when status changes to COMPLETED, ERROR, or PAUSED.

Key serialization details:
- `downloaded_bytes` and `total_bytes` saved as strings to avoid JSON integer overflow
- `date_added` and `date_completed` saved as ISO 8601 strings
- `unique_id` is a UUID string for tracking across sessions
- Status deserialization: WAITING and DOWNLOADING are restored as PAUSED (requires manual resume)
- `DownloadItem.from_dict()` provides backwards compatibility for old saved data

**Important**: Downloads persist indefinitely until user clicks "Clear Completed" - they are NOT filtered out on save.

### Startup Recovery Rules (`load_downloads`)

A saved COMPLETED download is downgraded to PAUSED only when the disk holds **partial** data
that contradicts the status:

- final file present but smaller than `total_bytes` → the download never finished
- final file absent but `.part{N}` files present → the merge never ran

An empty disk is **not** evidence of an unfinished download — it means the user deleted the file
after it completed. Such an item keeps COMPLETED and is restored at 100% (`downloaded_bytes` is
reset to `total_bytes`) instead of recomputing progress from what is left on disk. Treating
`on_disk < total_bytes` as the recovery trigger regresses this: every completed-then-deleted
download reappears as PAUSED at 0%.

Because a completed item with no file on disk still needs a way to be fetched again,
`_is_restartable()` — the single source of truth for both the toolbar and the context menu —
enables Restart for COMPLETED downloads whose file is missing.

### File Opening Integration

The download table supports:
- **Right-click on filename**: Context menu with "Open File" and "Open Folder" (only shown if file/folder exists)
- **Double-click on filename**: Opens the file with system default application
- **Drag & drop**: archive.org download URLs dropped on the window are queued non-interactively
  into the default/last-used folder

Cross-platform file opening via `platform.system()`:
- Windows: `os.startfile()`
- macOS: `subprocess.run(['open', ...])`
- Linux: `subprocess.run(['xdg-open', ...])`

### Translation System

The `Translator` class in translations.py manages bilingual strings:
- Access translations via `self.t('key_name')` or `self.t('key_with_args', arg1=value1)`
- Language preference stored in QSettings as 'language'
- All user-facing strings must have entries in both `TRANSLATIONS_PT` and `TRANSLATIONS_EN`
- Language changes require restart (appearance changes do not — they apply live)

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
- `recent_identifiers` - List of identifier search history (max 50 items)
- `recent_searches` - List of archive search query history (max 20 items)
- `theme_mode` - 'dark' or 'light'
- `accent` - Accent key from `themes.ACCENTS`
- `density` - 'comfortable' or 'compact'
- `speed_limit_kb` - Global speed cap in KB/s (0 = unlimited)
- `minimize_to_tray` - Close button hides to the system tray instead of quitting
- `last_tab_index` - Last selected page index (a `PAGE_*` constant)

### Styling Considerations

- QSpinBox controls must NOT have `padding` in stylesheets - it blocks up/down arrow buttons.
  Use `min-height` instead.
- CSS-triangle arrows (`QComboBox::down-arrow`, `QSpinBox::up-arrow`/`::down-arrow`) need
  `width: 0; height: 0;` alongside the border trick, otherwise the Fusion style paints its own
  arrow over them.
- `main()` sets the Fusion style: it is the only Qt style that applies this QSS consistently.
- `icons.render_pixmap` must take the device pixel ratio from `QApplication` — hardcoding it makes
  Qt fit a 2x pixmap into a 1x slot and crop the icon.

### Tooltip Metadata

Filename column tooltips display:
- Shortened unique_id (first 8 chars)
- Date added (YYYY-MM-DD HH:MM:SS)
- Date completed (if applicable)

Updated when download completes to add completion date.
