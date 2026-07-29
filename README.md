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
12. [Keyword Verification](#keyword-verification)
13. [Market Research & Recruitment](#market-research--recruitment)
14. [Charts & Visualization](#charts--visualization)
15. [Import / Export](#import--export)
16. [License](#license)

---

## Overview

Kleos is designed for community managers who need to monitor a roster of content creators and streamers. It maintains a local SQLite database per-profile, pulls public metadata from the YouTube Data API v3 and Twitch Helix API, caches thumbnails and profile pictures locally, and exposes everything through a themeable PyQt6 GUI (default **Kleos Soft** — a light red-and-white palette matching thoria.fyi/Kleos, with dark and other themes selectable in Settings → Appearance) with matplotlib-powered charts.

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
| AI Verification | anthropic SDK (optional), google-genai SDK (optional) |
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

- **Verification (Unified)**
  - Single **✓ Verify** button opens a card-based wizard to choose a verification method.
  - **AI Verification**: Classifies unverified videos against a user-supplied community description using Anthropic Claude or Google Gemini models. Supports Haiku 4.5, Sonnet 4.6, Opus 4.8 (Claude) and 2.5 Flash, 2.5 Pro, 2.5 Flash Lite, 3.5 Flash (Gemini). Exponential backoff retry logic for rate limits.
  - **Keyword Verification**: No-AI alternative that matches user-defined keywords against video titles and descriptions. Case-insensitive whole-word matching. Multi-word keywords allow flexible whitespace. Comma-separated keyword input.
  - Cancelable background workers with progress reporting.
  - Cooldown timer with live countdown when fetches are rate-limited.

- **Market Research & Recruitment (Discover)**
  - Search YouTube for small, high-potential creators outside your roster — the second half of media management beyond tracking your existing members. Two tabs: **Channels** and **Videos**.
  - **Channels tab**: five search modes — **Keywords**, **Category**, **Region/Language**, **Seed channels** (derives keywords from seed channels' recent uploads), and **Community keywords** (falls back to your `verify_keywords` / community name when no query is given).
  - **Videos tab**: a parallel search that returns *individual videos* with the same filters (keywords, region, language, category, sub ceiling, min subs, shorts, max results) plus a **Timeframe** (any time / last day / week / month / year) that narrows the search via `publishedAfter`. Results render in a table with per-row **Open** (watch on YouTube) and **+ Add** (promote the video's channel to the roster) actions. Sort by views, upload date, engagement, or title (client-side, 0 quota).
  - **★ Media Coverage** (Videos tab): one-click search pre-filled with your community name — finds videos that *mention* your community.
  - **📊 Stats** (Videos tab): opens a 2-chart stats panel that mirrors the roster's per-creator "Media History" Stats tab — a view-count timeline and an upload-activity bar chart — treating all found videos as one community's uploads. Charts use **only data the search already fetched, so opening them costs 0 extra YouTube quota.** Type (all/shorts/videos/streams) and Range (all/year/month/week) filters re-render client-side.
  - Pure-code **potential score** (0–100) per creator — views/sub ratio (35), upload consistency (20), recent growth signal (20), niche fit (15), engagement (10). No AI required.
  - Hard filters: sub ceiling (default 10k, configurable) and minimum views-per-sub ratio. Sort channels by potential, views/sub, smallest-first, total views, or cadence.
  - Channel results as a card grid or a dense table (toggle), with per-creator **+ Add to roster**, **Eval** (AI), and **⚑ Flag** actions.
  - **AI Evaluate**: one prompt per discovered creator asks the AI whether they're worth reaching out to and why (verdict + rationale, cached).
  - **Candidate Pool**: flagged creators persist (survive cache clears) with freeform notes — your own status, no fixed enum. One-click **+ Add to roster** promotes a candidate into the tracked dashboard.
  - Quota-optimized for the free 10K/day plan: a channel or video search ≈ 100–200 units (/search is the only expensive call; /videos and /channels batch 50 IDs at 1 unit each). Both are cached — re-running an identical search (including the same timeframe) costs 0 units.
  - No monitoring of non-roster creators; discovery notifications toggle in Settings.

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

Optional: for auto-verification, install the AI SDKs (already covered by `requirements.txt`):
```bash
pip install anthropic>=0.40.0
pip install google-genai>=1.0.0
```
You only need one of these — install the SDK for the provider you plan to use.

---

## Configuration

### API Keys
Open **Settings → API Keys** and provide:

- **YouTube Data API v3 Key** (39 characters, starts with `AIza`)
- **Twitch Client ID**
- **Twitch Client Secret**
- **Anthropic API Key** (optional, required for Auto-Verify with Claude models)
- **Gemini API Key** (optional, required for Auto-Verify with Gemini models)

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
- `community_name` – short name for your community (e.g. `ArchMC`). Used as the **★ Media Coverage** search query and as a Discover fallback when no keywords/query are given.
- `auto_verify_model` – AI model for auto-verify. Claude: `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-opus-4-8`. Gemini: `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.5-flash-lite`, `gemini-3.5-flash`
- `verify_keywords` – comma-separated community keywords. Used for keyword-based verification (no AI) and as the primary Discover search fallback when no query is given.
- `notification_view_thresholds` – comma-separated view counts that trigger alerts (default: `10000,100000,1000000`)
- `discover_sub_ceiling` – max subscriber count for a creator to be considered "small" in Discover (default: `10000`)
- `discover_min_views_per_sub` – minimum views-per-sub ratio required to keep a discovered creator (default: `10`)
- `discover_default_sort` – default result sort: `potential`, `vps`, `smallest`, `views`, or `cadence` (default: `potential`)
- `discover_shorts` – whether to include Shorts-only channels in discovery: `always` or `never` (default: `ask`)
- `discover_notifications` – `1` to surface a toast when a search finds high-potential creators, `0` to suppress (default: `1`)

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
│   ├── api_client.py        # YouTubeClient, TwitchClient, FetchWorker (QThread)
│   ├── cache_manager.py     # Thumbnail/PFP download, local caching, pre-scaling
│   ├── db_manager.py        # DatabaseManager: SQLite, dual-conn, schema v8, CRUD, import/export
│   ├── html_export.py       # Self-contained HTML community dashboard generator
│   ├── paths.py             # APP_DIR, STORAGE_DIR, BACKUPS_DIR, THUMBNAILS_DIR, GLOBAL_SETTINGS_PATH
│   ├── report_generator.py  # Plain-text report generation (clipboard)
│   ├── verify_worker.py     # VerifyWorker (QThread) for Claude/Gemini auto-verify
│   ├── keyword_verify.py    # KeywordVerifyWorker (QThread) for keyword-based verify
│   ├── discover_scorer.py   # Pure-code potential score (no AI)
│   ├── discover_worker.py   # DiscoverWorker (channels) + VideoSearchWorker (videos): YouTube search → resolve → score/persist
│   ├── ai_client.py         # Shared single-prompt Claude/Gemini call helper (retries, cancel)
│   └── discover_ai_worker.py # EvaluateWorker (single-prompt AI evaluation)
├── ui/
│   ├── __init__.py
│
└── ui/
    ├── __init__.py
    ├── app_icon.py           # Programmatic app icon generation
    ├── chart_utils.py        # _ZoomableFigureCanvas mixin (scroll-zoom, drag-pan, dblclk-reset)
    ├── dialog_utils.py       # Dark QMessageBox wrappers, fullscreen helpers
    ├── main_window.py        # MainWindow, GradientCanvasV2, _AddCreatorDialog, _InlineEditDialog
    ├── analytics_window.py   # AnalyticsWindow: leaderboard, charts, HTML export
    ├── discover_window.py    # DiscoverWindow (Channels + Videos tabs), EvaluateDialog (market research)
    ├── video_search_stats.py # VideoSearchStatsDialog — 0-quota stats panel for video search results
    ├── candidate_pool.py     # CandidatePoolDialog: flagged creators + outreach notes
    ├── notification.py       # NotificationToast: slide-in toast with auto-dismiss
    ├── settings_dialog.py    # SettingsDialog: API Keys, Verify, Profiles, Roles, Appearance, Notifications, Discover tabs
    ├── verify_dialog.py      # VerifyDialog: card-based verification method wizard
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
- **VerifyWorker** (`QThread`): Classifies unverified videos via the Anthropic or Gemini API. Emits progress signals.
- **KeywordVerifyWorker** (`QThread`): Verifies videos by matching keywords against titles and descriptions. No AI required.
- **VerifyDialog** (`QDialog`): Card-based wizard for selecting verification method (Keyword or AI), provider (Gemini or Claude), and model.
- **ThreadPoolExecutor** (4 workers): Thumbnail downloads in HistoryDialog are capped at 4 concurrent downloads to prevent crashes from missing thumbnails.
- All workers communicate through Qt signals; the main thread never waits on network IO.

### Database Layer (`DatabaseManager`)
- Uses two SQLite connections per profile: `_conn` (writes) with `_write_lock` and `_read_conn` (reads) with `_read_lock`, enabling lock-free concurrent reads in WAL mode.
- Foreign keys enforced (`PRAGMA foreign_keys=ON`).
- Schema versioning via `PRAGMA user_version` with migrations (currently v8 — adds `tags`, `alerts`, `type_override`, and the Discover tables: `search_cache`, `discovered_creators`, `candidate_pool`, `ai_evaluations`).
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

-- Discover & Recruitment (schema v8)
search_cache         (id PRIMARY KEY, params_hash UNIQUE, mode, query, results_json,
                      result_count, run_at)
discovered_creators  (channel_id PRIMARY KEY, handle, title, pfp_url,
                      subscriber_count, view_count, video_count, cadence_per_week,
                      growth_signal, engagement, niche_fit, views_per_sub,
                      potential_score, recent_titles_json, is_short_channel,
                      first_discovered_at, last_refreshed_at)
candidate_pool       (channel_id PRIMARY KEY FK, notes, flagged_at, last_updated_at)
ai_evaluations      (id PRIMARY KEY AUTOINCREMENT, channel_id FK, provider, model,
                      verdict, rationale, created_at)
```

The **Discover** tables support market research without tracking non-roster creators: `search_cache` persists prior searches (keyed by a SHA-1 of their parameters) for 0-quota re-runs, `discovered_creators` holds the scored candidate set, `candidate_pool` holds the flagged subset with freeform notes, and `ai_evaluations` caches AI verdicts per creator. Promoting a candidate inserts a row into `creators` and unflags it; non-roster creators are never monitored or notified.

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

Clicking **✓ Verify** on the main dashboard opens a card-based wizard dialog where you choose a verification method:

1. **Keyword Verification** — match videos by keywords (no AI needed)
2. **AI Verification** — classify videos using Claude or Gemini models

For AI verification, you then choose a provider (Gemini or Claude) and a model. For keyword verification, you can edit keywords directly in the dialog before starting.

The `VerifyWorker` sends each unverified video's title and description to an AI API (Anthropic Claude or Google Gemini) with the following system prompt:

> You are a content moderator for an online community... Respond with ONLY "YES" or "NO".

The provider is selected automatically based on the model ID prefix:
- Models starting with `claude-` → Anthropic Claude API
- Models starting with `gemini-` → Google Gemini API

**Anthropic Claude:**
- Temperature locked to `0` for deterministic outputs on Haiku.
- Max retries: 3 with exponential delays (1s, 2s, 4s) on `RateLimitError`.
- Authentication, connection, and timeout errors surface as modal warnings.

**Google Gemini:**
- Temperature locked to `0` for deterministic classification on all models.
- Max retries: 3 with exponential delays (1s, 2s, 4s) on HTTP 429 (rate limit).
- Authentication errors (401/403) and connection errors surface as modal warnings.
- Free-tier models available: Gemini 2.5 Flash, 2.5 Pro, 2.5 Flash Lite, 3.5 Flash.

**Both providers:**
- Cooperative profile guard: if the user switches profiles mid-verification, the worker aborts cleanly.
- Cancelable via the Cancel button in the progress bar area.

---

## Keyword Verification

Kleos offers **Keyword Verification** as a no-AI alternative — it matches user-defined keywords against video titles and descriptions.

The `KeywordVerifyWorker` reads a comma-separated list of keywords from the per-profile `verify_keywords` setting. Each keyword is compiled into a case-insensitive whole-word regex pattern:

- **Single-word keywords** like `arch.mc` match as `\barch\.mc\b` — they will match "Arch.mc server" but not "search.mc".
- **Multi-word keywords** like `ArchMC Network` match as `\bArchMC\s+Network\b` — flexible whitespace is allowed between words.
- Matching is case-insensitive: `arch.mc` matches "ARCH.MC" and "Arch.Mc".

If **any** keyword matches the title **or** description of an unverified video, that video is automatically marked as verified.

**Usage:**
1. Click **✓ Verify** on the main dashboard, then choose **Keyword Verification**.
2. Edit keywords in the dialog (pre-filled from Settings → Verify), then click **Start Verification**.

Like AI verification, keyword verification runs in a background `QThread`, shows a progress bar, and can be cancelled at any time. It also respects the cooperative profile guard.

---

## Market Research & Recruitment

Discover is the second half of media management — it finds small, high-potential YouTube creators *outside* your tracked roster so you can recruit them. The window has two tabs: **Channels** (creator search, scored and persisted) and **Videos** (individual-video search with a stats panel).

### Channels search pipeline (`DiscoverWorker`)
1. **Search** — one of five modes builds a `/search` query:
   - **Keywords** — raw query string.
   - **Category** — YouTube video category ID.
   - **Region/Language** — `regionCode` + `relevanceLanguage`.
   - **Seed channels** — Kleos fetches each seed's recent uploads, pools title/description tokens, and uses the top keywords as the query.
   - **Community keywords** — when no query/seed is given, Kleos falls back to your `verify_keywords` (community keywords), then the `community_name` setting.
   `/search` is the only expensive call (100 units/page); results are capped at `max_results` (default 200). Each search is hashed (SHA-1 of its mode + query + filters + `result_mode`) and cached in `search_cache`, so re-running an identical search costs 0 units.
2. **Stats** — `/videos` is batched at 50 IDs per call (1 unit each) to fetch view/like/comment counts and short/stream detection.
3. **Resolve** — `/channels` is batched at 50 IDs per call (1 unit each) for handle, title, PFP, and aggregate subscriber/view/video counts.
4. **Filter** — drop channels already on the roster, channels above the sub ceiling, and (optionally) Shorts-only channels.
5. **Score** — `core/discover_scorer.py` computes a pure-code 0–100 potential score per creator (no AI):
   | Component | Weight | Signal |
   |----------|-------|--------|
   | Views / sub ratio | 35 | how much each subscriber is "worth" |
   | Upload consistency | 20 | uploads per week over the last 90 days |
   | Growth signal | 20 | view velocity of recent videos relative to channel size |
   | Niche fit | 15 | whole-word overlap of recent titles vs your keywords |
   | Engagement | 10 | (likes + comments) / views |
6. **Sort & persist** — sort by potential (default), views/sub, smallest-first, total views, or cadence; `upsert_discovered_creator()` writes each result.

### Videos search pipeline (`VideoSearchWorker`)
The Videos tab runs a parallel search that returns individual videos using the same filters plus a **Timeframe**:
1. **Search** — `client.search_videos(...)` (the same `/search`, `type=video`) with `published_after` from the timeframe (any / day / week / month / year). The query falls back to `verify_keywords` → `community_name` when empty; the **★ Media Coverage** button pre-fills the query with `community_name`.
2. **Resolve channels** — one batched `/channels` call for subscriber counts (so the sub-ceiling / min-subs filters apply).
3. **Filter** — drop videos whose channel is above the sub ceiling / below min subs / already on the roster; drop Shorts when shorts = never.
4. **Stats** — one batched `/videos` call for per-video view/like/comment counts and short/stream detection.
5. **Results** — per-video dicts (title, channel, subs, views, likes, comments, upload date, type) cached in `search_cache` with `result_mode='videos'` so a repeat (same filters + timeframe) costs 0 units.
6. **📊 Stats panel** — `VideoSearchStatsDialog` plots a view-count timeline + an upload-activity bar chart from the in-memory results, mirroring the roster's per-creator Stats tab. **0 extra YouTube quota** — charts use only the data the search already fetched.

A single channel or video search typically costs 100–200 quota units against the free 10K/day allowance. `/videos` and `/channels` batch at 50 IDs per call to minimize spend.

### AI (minimal, single-prompt)
To stay within free-tier limits, Discover uses exactly one AI prompt per action — no per-video calls:

- **AI Evaluate** (`EvaluateWorker`) — one prompt per discovered creator sends their stats + recent titles and asks for `{"worth_it": bool, "reason": str}`. The verdict and rationale are cached in `ai_evaluations` so re-evaluating is free.

It uses the shared `core/ai_client.py` helper (same retry/backoff/cancel pattern as `VerifyWorker`) and is triggered only on a button click — never automatically.

### Recruitment & outreach
- **+ Add to roster** on a discovered card (or in the Candidate Pool) promotes a creator into the tracked dashboard — `promote_candidate_to_roster()` inserts a `creators` row with the first role, seeds the YouTube stat settings, and unflags them.
- **⚑ Flag** moves a creator into the **Candidate Pool**, which persists across cache clears. Each candidate has a freeform notes field (your own status text — no fixed enum) that auto-saves with a 400ms debounce.
- **Non-roster creators are never monitored or notified.** Discovery toast notifications are opt-in via `discover_notifications` in Settings.

### Cache management
Re-running an identical search reads from `search_cache` (0 quota). **Settings → Discover → Clear cached searches** drops the cache and any *unflagged* discovered rows; flagged candidates in the Candidate Pool are preserved.

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