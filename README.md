# Kleos

**Kleos** is a desktop media community dashboard built with Python and Qt. It fetches, stores, and visualizes creator activity across YouTube and Twitch, providing per-member media history, global leaderboards, interactive analytics charts, and AI-assisted content verification.

---

## Table of Contents

1. [Overview](#overview)
2. [Tech Stack](#tech-stack)
3. [Features](#features)
4. [Installation](#installation)
5. [Running from Source](#running-from-source)
6. [Configuration](#configuration)
7. [Project Structure](#project-structure)
8. [Architecture Overview](#architecture-overview)
9. [Database & Profiles](#database--profiles)
10. [API Integration](#api-integration)
11. [Auto-Verification](#auto-verification)
12. [Charts & Visualization](#charts--visualization)
13. [Import / Export](#import--export)
14. [License](#license)

---

## Overview

Kleos is designed for community managers who need to monitor a roster of content creators and streamers. It maintains a local SQLite database per-profile, pulls public metadata from the YouTube Data API v3 and Twitch Helix API, caches thumbnails and profile pictures locally, and exposes everything through a dark-themed PyQt6 GUI with matplotlib-powered charts.

Key design goals:
- **Offline-first**: Once data is fetched, the entire dashboard and history work without internet.
- **Multi-profile**: Separate, isolated databases for unrelated communities.
- **Extensible verification pipeline**: Manual toggling plus optional Claude-powered auto-verification.
- **Responsive UI**: All network IO happens on background threads; the main thread never blocks.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| GUI Framework | PyQt6 |
| Database | SQLite (WAL mode, dual-connection architecture) |
| Charts | matplotlib (backend_qtagg) |
| HTTP | requests (with urllib3 retry adapter) |
| AI Verification | anthropic SDK (optional) |
| Packaging | PyInstaller (planned) |

---

## Features

- **Creator Management**
  - Add/remove media members with YouTube, Twitch, or dual-platform support.
  - Custom roles with hex color coding — create, rename, and edit roles from Settings or the context menu.
  - Per-creator tags/labels — organize members with custom tags visible on cards.
  - Nickname, platform tags, join date, and role assignment.
  - Internal notes per creator (visible in history, included in profile exports).
  - Role change directly from the card context menu — no need to open Settings.

- **Data Fetching**
  - YouTube Data API v3: channel profile resolution, uploads playlist pagination, video stats, short detection (ISO 8601 duration parse).
  - Twitch Helix: OAuth2 client-credentials flow, user profile lookup, live streams, past broadcasts & highlights (cursor-based pagination).
  - Configurable per-creator video limit (0 = unlimited).
  - Automatic thumbnail pre-scaling (320×180) for faster loading and reduced memory.
  - Concurrency cap (4 concurrent downloads).

- **Dashboard**
  - Role-filtered, sortable, searchable card grid with debounced search (200ms). Search also matches tag text.
  - Empty state with call-to-action when no members are added yet.
  - Subscriber/follower display with compact formatting (e.g. `1.2M subs`).
  - Activity sparkline — 7 dots per card showing upload frequency over the last 7 weeks.
  - New-activity alerts (orange ⚠ badge).
  - Cascade entrance animations and hover physics (lift + shadow).
  - Lazy card creation — cards render in batches and update in-place without full rebuilds.
  - Keyboard navigation — Tab to focus cards, Up/Down arrows to move between cards, Enter to open.
  - Keyboard shortcuts: Ctrl+R (Refresh All), Ctrl+N (Add Member), Ctrl+F (Focus Search), Escape (Clear Search).
  - Tooltips on all toolbar buttons and controls.

- **Per-Creator History**
  - Sort, filter, and search within the media list:
    - Sort by Date (newest/oldest), Title A-Z, or Views (high-low).
    - Filter by All, Verified only, Shorts only, Videos only, or Streams only.
    - Search content by title.
  - Content type override — right-click any content row to manually set its type (Video, Short, Stream) or reset to auto-detect. Overrides persist across data refreshes via the `type_override` column.
  - Paginated media list (50 items per page) with lazy thumbnail recovery.
  - Verify / Unverified toggle.
  - Double-click to open content URL in browser.
  - Per-member notes with auto-save indicator ("Saving…" → "Saved ✓").
  - Deferred chart rendering — charts load only when you visit the Stats tab.
  - Toggleable interactive charts — Timeline and Upload Activity each get the full tab when selected.
  - Stats tab filter controls — Verified only checkbox, Type combo (All types/Shorts/Videos/Streams), Range combo (All time/Last year/Last month/Last week).
  - Per-creator report and HTML export — generate a plain-text report or self-contained HTML dashboard scoped to a single creator.

- **Leaderboard & Analytics**
  - Interactive trajectory and monthly-upload charts with filter controls — Verified only checkbox, Type combo (All types/Shorts/Videos/Streams), Range combo (All time/Last year/Last month/Last week).
  - Clipboard-ready plain-text reports (weekly / monthly / yearly / all time) with separate Verified only and Type filters.
  - HTML export — generate a self-contained, shareable community dashboard page with inline SVG charts.
  - Separate filter controls for charts and reports to avoid confusion.

- **Milestone Notifications**
  - Automatic toast notifications when creators hit subscriber milestones (1K, 5K, 10K, 25K, 50K, 75K, 100K, 250K, 500K, 750K, 1M).
  - Configurable view-count alert thresholds (e.g. 10K, 100K, 1M total views).
  - Notifications slide in from the top-right corner and auto-dismiss.
  - Reset triggered alerts from Settings to re-trigger them.

- **Auto-Verification**
  - Anthropic Claude API integration for YES/NO classification of unverified videos against a user-supplied community description.
  - Supports Haiku 4.5, Sonnet 4.6, and Opus 4.8 models.
  - Exponential backoff retry logic for rate limits.
  - Cancelable background worker with progress reporting.
  - Cooldown timer with live countdown when fetches are rate-limited.

- **Import / Export**
  - Full profile export/import as JSON (versioned schema v6, includes `tags`, `community_description`, and `type_override`).
  - Single-creator export/import (includes notes, tags, and community description).
  - Drag-and-drop import support on the main window.
  - Import merge/dedup — when importing a creator whose YouTube/Twitch link already exists, you can merge their media into the existing creator.

- **Persistence**
  - Profile-scoped SQLite databases with WAL journaling (schema v6 — includes `tags` column, `alerts` table, and `type_override` column).
  - Dual-connection architecture: separate read and write connections for lock-free reads.
  - Global settings stored in `global_settings.json` (API keys shared across profiles, startup profile remembered).
  - Automatic timestamped backups (keeps last 3 per profile).
  - First-run wizard on initial launch — multi-step walkthrough (Welcome → API Keys → 8 feature pages with visual mockups).

- **Design System**
  - Unified design token system (`C.*` colors, `M.*` motion constants) in `ui/theme/tokens.py`.
  - Centralized dark-theme stylesheet (`build_dialog_qss()`) used across all dialogs.
  - Consistent visual language across every window and dialog.

---

## Installation

### Installer (Recommended)
Download **`Kleos-Setup.exe`** from the [GitHub Releases](https://github.com/ThoriaDevelopment/Kleos/releases) page and run it. The wizard installs the app to `C:\Program Files\Kleos`, creates Start Menu and Desktop shortcuts, and registers it in Windows Add/Remove Programs. No Python or other dependencies are required.

> **Uninstalling:** The uninstaller removes the application files, shortcuts, and the `%APPDATA%\.kleos` user data folder (databases, cache, and backups).

### Running from Source

1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Launch the application:
   ```bash
   python -m main
   ```

Optional: for auto-verification, install the Anthropic SDK (already covered by `requirements.txt`):
```bash
pip install anthropic>=0.40.0
```

---

## Configuration

### API Keys
Open **Settings → API Keys** and provide:

- **YouTube Data API v3 Key** (39 characters, starts with `AIza`)
- **Twitch Client ID**
- **Twitch Client Secret**
- **Anthropic API Key** (optional, required for Auto-Verify)

API keys are stored globally and shared across all profiles.

Alternatively, set environment variables before launching:
- `KLEOS_YT_API_KEY`
- `KLEOS_TWITCH_CLIENT_ID`
- `KLEOS_TWITCH_CLIENT_SECRET`

### Global Settings (`global_settings.json`)
- `api_keys_json` – serialized dict of all keys (shared across profiles)
- `last_profile` – remembered startup profile

### Per-Profile Settings (in each profile's SQLite database)
- `fetch_video_limit` – integer cap per creator (0 = unlimited)
- `thumbnail_quality` – `"low"` (cached) or `"high"` (re-fetch)
- `community_description` – up to 300 words for auto-verify context
- `auto_verify_model` – `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, or `claude-opus-4-8`
- `notification_view_thresholds` – comma-separated view counts that trigger alerts (default: `10000,100000,1000000`)

---

## Project Structure

```
Kleos/
├── main.py                 # Entry point, FirstRunWizard, DWM dark title-bar, app init
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── USERMANUAL.md           # End-user documentation
│
├── core/
│   ├── __init__.py
│   ├── api_client.py       # YouTubeClient, TwitchClient, FetchWorker (QThread)
│   ├── cache_manager.py    # Thumbnail/PFP download, local caching, pre-scaling
│   ├── db_manager.py       # DatabaseManager: SQLite, dual-conn, schema v6, CRUD, import/export
│   ├── html_export.py      # Self-contained HTML community dashboard generator
│   ├── paths.py            # APP_DIR, STORAGE_DIR, BACKUPS_DIR, THUMBNAILS_DIR, GLOBAL_SETTINGS_PATH
│   ├── report_generator.py # Plain-text report generation (clipboard)
│   └── verify_worker.py    # VerifyWorker (QThread) for Claude auto-verify
│
└── ui/
    ├── __init__.py
    ├── app_icon.py           # Programmatic app icon generation
    ├── chart_utils.py        # _ZoomableFigureCanvas mixin (scroll-zoom, drag-pan, dblclk-reset)
    ├── dialog_utils.py       # Dark QMessageBox wrappers, fullscreen helpers
    ├── main_window.py        # MainWindow, GradientCanvasV2, _AddCreatorDialog, _InlineEditDialog
    ├── analytics_window.py   # AnalyticsWindow: leaderboard, charts, HTML export
    ├── notification.py       # NotificationToast: slide-in toast with auto-dismiss
    ├── settings_dialog.py    # SettingsDialog: API Keys, Verify, Profiles, Roles, Appearance, Notifications tabs
    ├── theme/
    │   ├── __init__.py       # build_global_qss()
    │   ├── stylesheet.py     # build_dialog_qss() centralized dark-theme QSS
    │   └── tokens.py         # Design tokens (C.* colors, M.* motion)
    └── components/
        ├── __init__.py
        ├── creator_card.py   # CreatorCard, _SparklineWidget, _TagManagerDialog, relative_time
        ├── history_dialog.py # HistoryDialog: sort/filter/search, notes save indicator, deferred charts
        └── loading_overlay.py # LoadingOverlay: semi-transparent spinner
```

---

## Architecture Overview

### Threading Model
- **Main Thread**: Handles all Qt widgets, animations, and layout.
- **FetchWorker** (`QThread`): One concurrent fetch at a time. Queries YouTube/Twitch APIs, writes to DB via `upsert_media_batch()`.
- **VerifyWorker** (`QThread`): Classifies unverified videos via the Anthropic API. Emits progress signals.
- **ThreadPoolExecutor** (4 workers): Thumbnail downloads in HistoryDialog are capped at 4 concurrent downloads to prevent crashes from missing thumbnails.
- All workers communicate through Qt signals; the main thread never waits on network IO.

### Database Layer (`DatabaseManager`)
- Uses two SQLite connections per profile: `_conn` (writes) with `_write_lock` and `_read_conn` (reads) with `_read_lock`, enabling lock-free concurrent reads in WAL mode.
- Foreign keys enforced (`PRAGMA foreign_keys=ON`).
- Schema versioning via `PRAGMA user_version` with migrations (currently v6 — includes `tags` column, `alerts` table, and `type_override` column).
- Global settings (API keys, last profile, first-run flag) stored in `global_settings.json` with atomic writes.
- Auto-backup runs in a background thread after writes, keeping the last 3 snapshots per profile.

### Schema
```sql
settings        (key PRIMARY KEY, value)
roles           (id PRIMARY KEY, role_name UNIQUE, role_color)
creators        (id PRIMARY KEY, nickname, platforms JSON, role_id FK,
                 youtube_type, youtube_channel_id, youtube_link, twitch_link,
                 pfp_url, date_added, is_new_activity, notes, tags TEXT DEFAULT '[]')
media_content   (id PRIMARY KEY, creator_id FK, platform CHECK('youtube','twitch'),
                 content_id UNIQUE, title, thumbnail_path, thumbnail_url,
                 upload_date, view_count, is_verified, is_short, is_stream,
                 type_override TEXT DEFAULT NULL, description)
alerts          (id PRIMARY KEY AUTOINCREMENT, creator_id FK, alert_type, threshold,
                 triggered_at, UNIQUE(creator_id, alert_type, threshold))
```

### Caching
- Thumbnails and profile pictures are downloaded to `%APPDATA%\.kleos\thumbnails`.
- Images are pre-scaled to 320×180 (2× display size for HiDPI) at download time for faster loading.
- A ThreadPoolExecutor (max 4 workers) fetches missing ones concurrently.
- Download errors are silently caught to prevent crashes from missing thumbnails.

---

## Database & Profiles

- **Profile = SQLite file** (`{name}.db` in `STORAGE_DIR`).
- Switching profiles closes the old connections and opens the new file. The last-used profile is remembered across sessions via `global_settings.json`.
- Profile export serializes creators (including notes, tags, and community description), media, roles, and settings into a JSON envelope with `version: 1`.
- Profile import deserializes into a **new** database file, mapping role names to the first available role in the target profile. Uses upsert semantics for settings.
- Creator import checks for duplicates by YouTube/Twitch link and offers a merge option to combine media into the existing creator.
- API keys are **not** included in profile exports — they are stored globally and shared across all profiles.

---

## API Integration

### YouTube
- Channel resolution via `forHandle` or `id` parameter.
- Uploads fetched via `playlistItems` on the `UU…` uploads playlist, avoiding the expensive `/search` endpoint.
- Video stats batch-fetched via `/videos` with `statistics,contentDetails`.
- Short detection based on ISO 8601 duration parsing (≤90 seconds) plus `liveStreamingDetails` for stream identification.

### Twitch
- OAuth2 token obtained via `client_credentials` grant.
- Streams: `helix/streams`.
- Past videos: `helix/videos` with cursor pagination.
- Profile: `helix/users`.

---

## Auto-Verification

The `VerifyWorker` sends each unverified video's title and description to the Claude API with the following system prompt:

> You are a content moderator for an online community... Respond with ONLY "YES" or "NO".

- Temperature locked to `0` for deterministic outputs on Haiku.
- Max retries: 3 with exponential delays (1s, 2s, 4s) on `RateLimitError`.
- Authentication and connection errors surface as modal warnings.
- Cooperative profile guard: if the user switches profiles mid-verification, the worker aborts cleanly.

---

## Charts & Visualization

- Built on `matplotlib.backends.backend_qtagg`.
- **Filter controls**: Both the per-creator Stats tab and the global Analytics window offer Verified only, Type (Shorts/Videos/Streams), and Range (All time/Year/Month/Week) filter combos that update charts in real time.
- **Toggleable charts**: Both the per-creator Stats tab and the global Analytics window offer Timeline and Upload Activity chart modes. Toggle between them using the "Timeline" / "Upload Activity" buttons — the selected chart fills the full panel.
- **Deferred rendering**: Charts are created lazily on first visit to avoid slowing down the initial tab load.
- **HTML chart export**: The HTML export embeds timeline and bar charts as inline SVG — no external dependencies needed.
- `_ZoomableFigureCanvas` mixin provides:
  - **Scroll**: zoom in/out centered on cursor.
  - **Drag**: pan both axes.
  - **Double-click**: reset to home limits.
  - Y-axis clamped at 0 for metrics that can't be negative (views, uploads).

---

## Import / Export

### Creator JSON Schema (`type: creator`)
```json
{
  "version": 1,
  "type": "creator",
  "creator": { ..., "notes": "Internal notes", "tags": ["tag1", "tag2"] },
  "media_content": [ ... ],
  "stats": { "youtube_subscribers": ..., "twitch_followers": ... },
  "community_description": "..."
}
```

### Profile JSON Schema (`version: 1`)
```json
{
  "version": 1,
  "profile": "name",
  "creators": [ ..., "notes": "...", "tags": [...] ],
  "media_content": [ ... ],
  "roles": [ ... ],
  "settings": [ ... ]
}
```

Notes, tags, and community descriptions are included in both creator and profile exports/imports. Drag-and-drop `.json` files onto the main window; Kleos introspects the `type` and `version` fields to route the import correctly. When importing a creator whose link matches an existing member, Kleos offers a merge option.

---

## License

Kleos is released under the **MIT License**. See `LICENSE` for details.