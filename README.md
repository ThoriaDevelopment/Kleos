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
| Database | SQLite (WAL mode) |
| Charts | matplotlib (backend_qtagg) |
| HTTP | requests (with urllib3 retry adapter) |
| AI Verification | anthropic SDK (optional) |
| Packaging | PyInstaller (planned) |

---

## Features

- **Creator Management**
  - Add/remove media members with YouTube, Twitch, or dual-platform support.
  - Custom roles with hex color coding.
  - Nickname, platform tags, join date, and role assignment.

- **Data Fetching**
  - YouTube Data API v3: channel profile resolution, uploads playlist pagination, video stats, short detection (ISO 8601 duration parse).
  - Twitch Helix: OAuth2 client-credentials flow, user profile lookup, live streams, past broadcasts & highlights (cursor-based pagination).
  - Configurable per-creator video limit (0 = unlimited).
  - Automatic thumbnail and PFP caching.

- **Dashboard**
  - Role-filtered, sortable, searchable card grid.
  - Subscriber/follower display.
  - New-activity alerts (orange ⚠ badge).
  - Cascade entrance animations and hover physics (lift + shadow).

- **Per-Creator History**
  - Paginated media list (50 items per page) with lazy thumbnail recovery.
  - Verify / Unverified toggle.
  - Double-click to open content URL in browser.
  - Per-member timeline (views over time) and monthly upload bar chart.

- **Leaderboard & Analytics**
  - Global view-count leaderboard with platform filter.
  - Interactive trajectory and monthly-upload charts (zoom, pan, reset).
  - Clipboard-ready plain-text reports (weekly / monthly / yearly).

- **Auto-Verification**
  - Anthropic Claude API integration for YES/NO classification of unverified videos against a user-supplied community description.
  - Supports Haiku 4.5, Sonnet 4.6, and Opus 4.8 models.
  - Exponential backoff retry logic for rate limits.
  - Cancelable background worker with progress reporting.

- **Import / Export**
  - Full profile export/import as JSON (versioned schema v1).
  - Single-creator export/import.
  - Drag-and-drop import support on the main window.

- **Persistence**
  - Profile-scoped SQLite databases with WAL journaling.
  - Automatic timestamped backups (keeps last 3 per profile).
  - All API keys stored in the active database's settings table.

---

## Installation

### Installer (Planned)
A Windows installer will be distributed via GitHub Releases.

### Prerequisites (Source)
- Python 3.12 or newer
- `pip`

---

## Running from Source

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

Alternatively, set environment variables before launching:
- `KLEOS_YT_API_KEY`
- `KLEOS_TWITCH_CLIENT_ID`
- `KLEOS_TWITCH_CLIENT_SECRET`

### Settings Stored in Database
- `api_keys_json` – serialized dict of all keys
- `fetch_video_limit` – integer cap per creator (0 = unlimited)
- `thumbnail_quality` – `"low"` (cached) or `"high"` (re-fetch)
- `community_description` – up to 300 words for auto-verify context
- `auto_verify_model` – `claude-haiku-4-5`, `claude-sonnet-4-6`, or `claude-opus-4-8`
- `current_profile` – active profile name

---

## Project Structure

```
Kleos/
├── main.py                 # Entry point, DWM dark title-bar, app init
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── USERMANUAL.md           # End-user documentation
│
├── core/
│   ├── __init__.py
│   ├── api_client.py       # YouTubeClient, TwitchClient, FetchWorker (QThread)
│   ├── cache_manager.py    # Thumbnail/PFP download and local caching
│   ├── db_manager.py       # DatabaseManager: SQLite, schema, CRUD, import/export
│   ├── paths.py            # APP_DIR, STORAGE_DIR, BACKUPS_DIR, THUMBNAILS_DIR
│   ├── report_generator.py # Plain-text report generation (clipboard)
│   └── verify_worker.py    # VerifyWorker (QThread) for Claude auto-verify
│
└── ui/
    ├── __init__.py
    ├── app_icon.py           # Programmatic app icon generation
    ├── chart_utils.py        # _ZoomableFigureCanvas mixin (scroll-zoom, drag-pan, dblclk-reset)
    ├── dialog_utils.py       # Dark QMessageBox wrappers, fullscreen helpers
    ├── main_window.py        # MainWindow, GradientCanvasV2, _AddCreatorDialog, _InlineEditDialog
    ├── analytics_window.py   # AnalyticsWindow: leaderboard + timeline + bar charts
    ├── settings_dialog.py    # SettingsDialog: API Keys, Verify, Profiles, Roles, Appearance tabs
    ├── theme/
    │   ├── __init__.py       # build_global_qss()
    │   ├── stylesheet.py       # Global QSS definitions
    │   └── tokens.py           # Color constants (C.*) and motion constants (M.*)
    └── components/
        ├── __init__.py
        ├── creator_card.py   # CreatorCard widget, relative_time, format_subscriber_count
        └── history_dialog.py # HistoryDialog: paginated media list, per-member charts
```

---

## Architecture Overview

### Threading Model
- **Main Thread**: Handles all Qt widgets, animations, and layout.
- **FetchWorker** (`QThread`): One concurrent fetch at a time. Queries YouTube/Twitch APIs, writes to DB via `upsert_media_batch()`.
- **VerifyWorker** (`QThread`): Classifies unverified videos via the Anthropic API. Emits progress signals.
- All workers communicate through Qt signals; the main thread never waits on network IO.

### Database Layer (`DatabaseManager`)
- Uses a single SQLite connection per profile with `threading.Lock` for thread safety.
- WAL mode enabled (`PRAGMA journal_mode=WAL`).
- Foreign keys enforced (`PRAGMA foreign_keys=ON`).
- Schema migrations handled imperatively (adding columns if missing).
- Auto-backup runs in a background thread after writes, keeping the last 3 snapshots per profile.

### Schema
```sql
settings        (key PRIMARY KEY, value)
roles           (id PRIMARY KEY, role_name UNIQUE, role_color)
creators        (id PRIMARY KEY, nickname, platforms JSON, role_id FK,
                 youtube_type, youtube_channel_id, youtube_link, twitch_link,
                 pfp_url, date_added, is_new_activity)
media_content   (id PRIMARY KEY, creator_id FK, platform CHECK('youtube','twitch'),
                 content_id UNIQUE, title, thumbnail_path, thumbnail_url,
                 upload_date, view_count, is_verified, is_short, description)
```

### Caching
- Thumbnails and profile pictures are downloaded to `%APPDATA%\.kleos\thumbnails`.
- Images are served from disk; a background thread fetches missing ones lazily.

---

## Database & Profiles

- **Profile = SQLite file** (`{name}.db` in `STORAGE_DIR`).
- Switching profiles closes the old connection and opens the new file.
- Profile export serializes creators, media, roles, and settings into a JSON envelope with `version: 1`.
- Profile import deserializes into a **new** database file, mapping role names to the first available role in the target profile.

---

## API Integration

### YouTube
- Channel resolution via `forHandle` or `id` parameter.
- Uploads fetched via `playlistItems` on the `UU…` uploads playlist, avoiding the expensive `/search` endpoint.
- Video stats batch-fetched via `/videos` with `statistics,contentDetails`.
- Short detection based on `PT…` ISO 8601 duration parsing (≤60 seconds).

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

---

## Charts & Visualization

- Built on `matplotlib.backends.backend_qtagg`.
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
  "creator": { ... },
  "media_content": [ ... ],
  "stats": { "youtube_subscribers": ..., "twitch_followers": ... }
}
```

### Profile JSON Schema (`version: 1`)
```json
{
  "version": 1,
  "profile": "name",
  "creators": [ ... ],
  "media_content": [ ... ],
  "roles": [ ... ],
  "settings": [ ... ]
}
```

Drag-and-drop `.json` files onto the main window; Kleos introspects the `type` and `version` fields to route the import correctly.

---

## License

Kleos is released under the **MIT License**. See `LICENSE` for details.

---