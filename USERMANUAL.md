# Kleos User Manual

**Kleos** — your personal media management dashboard. Kleos helps you keep track of all the creators and streamers in your community in one beautiful, easy to use window. You can see who's been active, how their content is performing, and keep everything organized without ever needing a spreadsheet again.

---

## Table of Contents

1. [Getting the App](#getting-the-app)
2. [First-Time Setup](#first-time-setup)
3. [The Main Dashboard](#the-main-dashboard)
4. [Adding a Media Member](#adding-a-media-member)
5. [Reading a Creator Card](#reading-a-creator-card)
6. [Opening a Member's History & Stats](#opening-a-members-history--stats)
7. [Creator Notes](#creator-notes)
8. [Verification](#verification)
9. [Leaderboard & Analytics](#leaderboard--analytics)
10. [Generating Reports](#generating-reports)
11. [Exporting a Community Page](#exporting-a-community-page)
12. [Per-Creator Reports & HTML](#per-creator-reports--html)
13. [Working with Profiles](#working-with-profiles)
14. [Roles](#roles)
15. [Tags & Labels](#tags--labels)
16. [Milestone Notifications](#milestone-notifications)
17. [Settings](#settings)
18. [Importing & Exporting Creators](#importing--exporting-creators)
19. [Importing & Exporting Profiles](#importing--exporting-profiles)
20. [Search, Sort & Filter](#search-sort--filter)
21. [Tips & Shortcuts](#tips--shortcuts)

---

## Getting the App

### Option 1: Installer (Recommended)
The easiest way to start using Kleos is to download the installer from the **Releases** page on GitHub.

1. Look for the file named **`Kleos-Setup.exe`** and download it.
2. Double-click the file to run the installer.
3. Follow the steps in the setup wizard (you can leave the install location as the default).
4. Once finished, you can open Kleos from your **Start Menu** or the **Desktop shortcut** that was created.

> **Tip:** If you ever want to remove Kleos, you can uninstall it like any other Windows app through *Settings → Apps*.

### Option 2: Running from Source
If you prefer, you can also run Kleos directly from the source code. This requires Python to be installed on your computer. You can find the source code on the GitHub repository.

---

## First-Time Setup

When you open Kleos for the first time, a **welcome wizard** will appear. It walks you through the basics across several pages:

1. **Welcome** — A brief introduction to Kleos.
2. **API Keys** — Optionally set up your YouTube and Twitch API keys right away (you can skip this and add them later in Settings).
3. **Feature Walkthrough** — Eight pages, each showing a key feature with a visual preview:
   - 🎬 **Add Members** — How to add creators and assign roles.
   - 📊 **View History** — Double-click a card to see media history and stats.
   - 🖱️ **Right-Click Menu** — Quick access to edit, notes, delete, and more.
   - ✅ **Verify Content** — Mark videos as community content or use Auto-Verify.
   - 👑 **Leaderboard & Analytics** — Rankings, charts, and reports.
   - 🔍 **Search & Filter** — Find members, sort, and filter by role.
   - 📝 **Creator Notes** — Internal notes that are auto-saved and exported.
   - ⌨️ **Keyboard Shortcuts** — Quick-reference for all shortcuts.

Use the **Next →** and **← Back** buttons to navigate. The wizard only appears once — on subsequent launches, Kleos opens straight to the dashboard. You can always add API keys later by clicking **⚙ Settings → API Keys**.

Before the app can fetch videos and stats from YouTube or Twitch, you will need to add your API keys.

### Where to get a YouTube Data API key
Here is a quick example of how to get the key for YouTube:

1. Open your web browser and go to the **Google Cloud Console** (search for it on Google).
2. Sign in with your Google account.
3. Create a **new project** and give it any name you like (for example, "Kleos Dashboard").
4. In the left-hand menu, click **APIs & Services → Library**.
5. Search for **YouTube Data API v3** and click it.
6. Press the **Enable** button.
7. Now click **Credentials** in the left-hand menu, then **Create Credentials → API key**.
8. Google will show you a long string of letters and numbers — that is your key. Copy it.
9. Back in Kleos, click **⚙ Settings** at the top of the main window.
10. Go to the **API Keys** tab and paste the key into the **YouTube API Key** box.
11. Click **OK** to save.

You only have to do this once. If you also want Twitch data, the Twitch Client ID and Secret follow a similar process on the Twitch Developer portal. The Anthropic key is only needed if you plan to use Auto-Verify later.

> **Note:** API keys are stored globally and shared across all your profiles, so you only need to enter them once.

> **Important:** Before you can click **+ Add Media Member**, you must create at least one role. Every member needs a role assigned to them. To create your first role, click **⚙ Settings**, go to the **Roles** tab, type a name (for example, "Member"), pick a color, and click **Add Role**. Once you have at least one role, you are ready to add people to your community.

---

## The Main Dashboard

The main window is your home base. It shows every person in your community as a card in a scrollable list. At the very top are the controls you'll use most often:

- **+ Add Media Member** — Opens a form to add someone new.
- **⟳ Refresh All** — Fetches the latest videos, streams, stats, and thumbnails for everyone at once.
- **✓ Auto-Verify** — Runs an automatic check on unverified videos to see if they belong in your community.
- **⚙ Settings** — Opens the settings panel for keys, profiles, roles, appearance, and notifications.
- **♛ Leaderboard** — Opens the global analytics and ranking window.

Below those buttons you'll find:
- A **Search** box to quickly find someone by nickname or tag.
- A **Sort** dropdown (Date Added, Name, or Subscribers).
- A **Filter** dropdown to show only people with a certain role.
- A **Profile** dropdown to switch between different saved lists.

All buttons have tooltips — hover over any button to see what it does.

### Empty State
If your community is empty (no members added yet), the dashboard shows a friendly empty state with a 🎬 icon, a message, and an **"+ Add Media Member"** button to get you started right away.

The background of the dashboard gently shifts between soft colors, giving the app a calm, modern feel.

---

## Adding a Media Member

To add someone to your community:

1. Click **+ Add Media Member** at the top left (or press **Ctrl+N**).
2. Fill out the form:
   - **Nickname** — The name you want to see in the dashboard (this can be their channel name or a custom name).
   - **Platforms** — Check the boxes for **YouTube**, **Twitch**, or both.
   - **Channel Links** — When you check a platform, a text box will appear where you can paste the direct link to their channel (for example, a YouTube channel URL or a Twitch channel URL).
   - **Role** — Choose a role from the dropdown. Roles are like tags that group people together (for example, "Founder," "Streamer," or "Editor"). You can create your own roles in Settings.
3. Click **OK**. The new member will appear immediately in your dashboard.

> **Tip:** You must create at least one role before you can add any members. You can do this in **Settings → Roles**.

---

## Reading a Creator Card

Each person in your community appears as a card. From left to right, a card shows:

- **Nickname** — The name you gave them.
- **Avatar** — Their channel profile picture (fetched automatically once data comes in).
- **Platform Tag** — Tells you at a glance if they are a "Creator" (YouTube), "Streamer" (Twitch), or "Streamer / Creator" (both).
- **Subscribers / Followers** — Compact numbers like `1.2M subs` or `450K flw`.
- **Activity Sparkline** — A row of 7 small dots to the right of the subscriber count. Each dot represents one week of upload activity. Bigger, brighter dots mean more uploads that week. Dim dots mean little or no activity. This gives you a quick visual sense of how active a creator has been recently.
- **Activity Alert** — An orange ⚠ icon appears when new content has been detected since the last time you looked at their history.
- **Last Activity** — How long ago their most recent video or stream went live.
- **Tags** — Small colored chip labels below the main card content, showing any tags you've assigned.
- **Duration** — How long this person has been in your community (based on the date you added them).

The left edge of each card is colored according to their role, so you can spot groups instantly.

Cards react smoothly when you move your mouse over them, lifting slightly and glowing softly.

### Keyboard Navigation
- **Tab** to move focus onto the card grid.
- **Up / Down arrows** to move between cards.
- **Enter** to open the selected member's history.
- A blue focus ring appears around the card that currently has keyboard focus.

### Right-Click Context Menu
Right-click any card to access these actions:
- **Edit Nickname** — Change the display name.
- **Edit Platforms** — Toggle YouTube/Twitch.
- **Edit Date Added** — Change the join date.
- **Change Role** — Submenu listing all roles; pick one to reassign this member's role.
- **Manage Tags** — Add or remove tags/labels on this member.
- **Refresh Data** — Re-fetch this creator's data from the APIs.
- **Delete Member** — Remove the creator (with confirmation).
- **Edit Notes** — Add or edit internal notes about this creator.
- **Export Creator** — Save this creator's data to a JSON file.

---

## Opening a Member's History & Stats

To dive deeper into a single person, **double-click their card** (or select it and press **Enter**). A new window titled *Media History* will open. This window has two tabs.

### Media Tab
Here you see every video or stream Kleos has fetched for this person. At the top of the media list you'll find controls:

- **Sort** — Choose from Date (newest), Date (oldest), Title A-Z, or Views (high-low).
- **Filter** — Choose from All, Verified only, Shorts only, Videos only, or Streams only.
- **Search** — Type to filter content by title. Search activates after a brief pause (debounced).

Each content row shows:
- A **thumbnail** image.
- The **title** of the video or stream.
- How long ago it was **uploaded** or went live.
- A **Verify / In Community** button to mark whether this piece of content belongs in your community.
- The **view count**.

At the bottom of the list you'll see a count like "Showing 50 of 120" and a **Load More** button if there are additional items to display.

If you **double-click** any row, it will open that video or stream directly in your web browser.

#### Content Type Override
Sometimes Kleos misclassifies content — for example, a premiere might show up as a stream, or a short video might not be detected as a Short. You can fix this by **right-clicking** any content row and choosing:
- **Set as Video** — Mark this content as a regular video.
- **Set as Short** — Mark this content as a short.
- **Set as Stream** — Mark this content as a stream.
- **Reset to Auto-Detect** — Remove the override and let Kleos classify it automatically again.

Overrides are saved permanently and persist across data refreshes. A small pencil indicator (✎) appears next to the type badge on overridden items so you can tell which ones you've manually set.

The top of the window also shows:
- Their **nickname** and **subscriber / follower counts**.
- When their **last verified content** was published.
- A **notes** text area where you can write internal comments about this member. Notes are auto-saved as you type — you'll see a **"Saving…"** indicator that changes to **"Saved ✓"** and then fades away.
- Buttons to **Refresh Content**, **Delete Member**, or **Export** this member's data.

### Stats Tab
This tab shows interactive charts for the selected member. The charts are loaded on demand — they only render when you first click the Stats tab, keeping the initial window load fast.

At the top you'll find filter controls:
- **Verified only** — Check this to include only verified content in the charts. Unchecked shows all content.
- **Type** — Choose from All types, Shorts, Videos, or Streams to filter by content type.
- **Range** — Choose from All time, Last year, Last month, or Last week to narrow the date range.

Use the **Timeline** and **Upload Activity** toggle buttons to switch between:
- **Timeline** — A line chart showing their view trajectory over time.
- **Upload Activity** — A bar chart showing how many pieces of content they uploaded each month.

The selected chart fills the entire tab area for a clearer, larger view.

Both charts can be zoomed in and out with your mouse wheel, panned by clicking and dragging, and reset by double-clicking.

Below the charts is a report row where you can generate a report or export an HTML dashboard scoped to this creator:
- **Period** — Choose Weekly, Monthly, Yearly, or All time.
- **Verified only** — Whether the report counts only verified content.
- **Type** — Filter the report by content type (All types, Shorts, Videos, Streams).
- **Copy Report** — Generates a plain-text report and copies it to your clipboard.
- **Export HTML** — Generates a self-contained HTML dashboard page for this creator and saves it to a file.

See the [Per-Creator Reports & HTML](#per-creator-reports--html) section for more details.

---

## Creator Notes

Every member can have internal notes attached to them. Notes are a freeform text field where you can write reminders, context, or any information you want to keep about a creator.

There are two ways to edit notes:
1. **Right-click a creator card** on the dashboard and choose **Edit Notes**.
2. **Open their Media History** window — the notes text area appears in the header at the top.

Notes are auto-saved with a short debounce (half a second after you stop typing), so you never lose your work. A **"Saving…"** → **"Saved ✓"** indicator appears next to the notes field to confirm. Notes are included when you export a profile or a creator, so collaborators can see your notes too.

---

## Verification

Verification is how you tell Kleos, "Yes, this video or stream belongs to our community." Verified content is counted in leaderboards, charts, and reports. Unverified content is hidden from those summaries by default.

### Manual Verification
Inside any member's *Media History* window, you'll see a button on every row:
- **Verify** (gray) — This content is not yet approved.
- **In Community** (green) — This content is approved.

Simply click the button to toggle it.

### Auto-Verify
If you have an Anthropic API key saved in Settings, you can let Kleos verify videos automatically:

1. Go to **Settings → Verify** and write a short **Community Description**. This tells the assistant what your community is about (for example, "A Minecraft survival community focused on redstone engineering"). Keep it under 300 words.
2. Choose a **Claude Model**:
   - **Haiku 4.5** — Fastest and cheapest.
   - **Sonnet 4.6** — Balanced speed and accuracy.
   - **Opus 4.8** — Most thorough.
3. Back on the main dashboard, click **✓ Auto-Verify**.
4. Kleos will ask for confirmation, then begin checking every unverified video against your description. Videos that match will be marked as verified automatically.

A progress bar appears at the top of the dashboard so you can see how far along the process is. You can press **Cancel** anytime to stop.

---

## Leaderboard & Analytics

Click the **♛ Leaderboard** button on the main dashboard to open the global analytics window. This is where you see how your entire community is performing.

### Filter Controls
At the top of the window you'll find filter controls:
- **Verified only** — Check this to include only verified content in the charts. Unchecked shows all content.
- **Type** — Choose from All types, Shorts, Videos, or Streams to filter by content type.
- **Range** — Choose from All time, Last year, Last month, or Last week to narrow the date range.

### Charts
Use the **Timeline** and **Upload Activity** toggle buttons to switch between:
- **View Trajectory** — A line chart showing how views have accumulated across your community over time.
- **Monthly Upload Activity** — A bar chart showing how many videos or streams were uploaded each month.

The selected chart fills the main area for a larger, clearer view. Like the individual stats charts, you can zoom with the scroll wheel, pan by dragging, and reset by double-clicking. The charts update automatically when you change any of the filters.

---

## Generating Reports

At the bottom of the Analytics window, you'll find a report generator:

1. Choose a time period: **Monthly**, **Weekly**, **Yearly**, or **All time**.
2. Optionally choose a **Role** to narrow the report to a specific group.
3. Optionally check **Verified only** to count only verified content.
4. Optionally choose a **Type** filter (All types, Shorts, Videos, Streams).
5. Click **Copy Report**.

Kleos builds a clean, plain-text summary and copies it directly to your clipboard. You can then paste it into Discord, a forum post, a text document, or anywhere else you like. The report includes:
- The date range covered.
- Total uploads and total views for that period.
- A ranked leaderboard of everyone included.
- Subscriber and follower counts where available.

---

## Exporting a Community Page

Also in the Analytics window, next to **Copy Report**, you'll find an **Export HTML** button. This generates a self-contained HTML page — a beautiful, dark-themed community dashboard that you can share with anyone.

1. Choose the time period and role filter (same as for reports).
2. Optionally check **Verified only** and choose a **Type** filter.
3. Click **Export HTML**.
4. Choose where to save the file.

The resulting HTML file includes:
- Your community name and description.
- A card for each creator with their role badge, platform tag, subscriber count, and view stats.
- An interactive timeline chart showing view trajectories over time.
- A monthly upload activity bar chart.
- A totals summary table.
- A footer with the generation timestamp.

The file is completely self-contained — all CSS and charts are embedded as inline SVG — so you can send it as-is, host it on a web server, or drop it in a shared drive. No internet connection is needed to view it.

---

## Per-Creator Reports & HTML

Inside any member's **Media History → Stats** tab, you'll find a report row at the bottom that works the same way as the global report, but scoped to that single creator:

1. Choose a time period: **Monthly**, **Weekly**, **Yearly**, or **All time**.
2. Optionally check **Verified only** to count only verified content.
3. Optionally choose a **Type** filter (All types, Shorts, Videos, Streams).
4. Click **Copy Report** to copy a plain-text summary to your clipboard, or **Export HTML** to save a self-contained HTML dashboard page for that creator.

The per-creator HTML export includes the same chart types (timeline and monthly uploads), a creator card, and a totals summary — all filtered to that member's data only.

---

## Working with Profiles

Profiles let you keep completely separate communities. For example, you might have one profile for your gaming team and another for your podcast network.

To manage profiles, open **Settings → Profiles**.

### Creating a New Profile
1. Type a name in the **New profile name** box.
2. Click **Create**.
3. Kleos switches to the new profile immediately. It starts empty, so you can add members from scratch.

### Switching Profiles
Use the **Profile** dropdown at the top of the main dashboard, or go to Settings → Profiles and click **Switch To**. The main dashboard will refresh to show the members of that profile.

Kleos remembers which profile you were using and opens it automatically the next time you launch the app.

### Deleting a Profile
1. Select a profile in the list.
2. Click **Delete**.
3. Confirm the deletion. **Warning:** This permanently deletes that profile and all its data. You cannot delete the profile you are currently using.

---

## Roles

Roles are a way to label and color-code members. Every member must have exactly one role.

To manage roles, open **Settings → Roles**.

### Adding a Role
1. Type a **Role name** (for example, "Admin" or "VIP").
2. Either type a color code or click **Pick Color** to choose one visually.
3. Click **Add Role**.

### Editing a Role
1. Select a role in the list.
2. Click **Edit Selected Role**.
3. Change the name or color and click **OK**.

### Deleting a Role
1. Select a role in the list.
2. Click **Delete Selected Role**.

You can only delete a role if no member is currently using it. If anyone is still assigned to it, Kleos will warn you and show you who needs to be reassigned first.

### Changing a Member's Role
You can also change a member's role directly from the dashboard:
1. **Right-click** the member's card.
2. Hover over **Change Role** in the context menu.
3. Select the new role from the submenu.

---

## Tags & Labels

Tags let you organize and quickly identify members with custom labels. Tags appear as small colored chips below the main card content.

### Adding and Removing Tags
1. **Right-click** a creator card and choose **Manage Tags**.
2. In the tag manager dialog:
   - Type a tag name and click **Add** to create a new tag.
   - Click the **×** button next to any tag to remove it.
3. Click **OK** to save your changes.

Tags are also searchable — type a tag name in the main dashboard search box and all members with that tag will appear.

---

## Milestone Notifications

Kleos automatically notifies you when your creators hit important milestones:

### Subscriber Milestones
When a creator crosses any of these subscriber thresholds, you'll see a toast notification slide in from the top-right corner:
- 1K · 5K · 10K · 25K · 50K · 75K · 100K · 250K · 500K · 750K · 1M subscribers

These milestones are fixed and automatic — no configuration needed.

### View Count Alerts
You can configure custom view-count thresholds. By default, Kleos alerts you when a creator's total views cross 10,000, 100,000, and 1,000,000. To change these:
1. Open **Settings → Notifications**.
2. Edit the comma-separated list in **View Count Alert Thresholds** (for example: `5000,50000,500000`).
3. Click **OK** to save.

### Resetting Alerts
If you want previously-triggered alerts to fire again (for example, after a data refresh), open **Settings → Notifications** and click **Reset All Triggered Alerts**.

---

## Settings

The Settings window is split into tabs for easy navigation.

### API Keys
Here you enter the credentials that let Kleos talk to YouTube and Twitch:
- **YouTube API Key** — Required to fetch YouTube videos and channel stats.
- **Twitch Client ID & Secret** — Required to fetch Twitch streams and videos.
- **Anthropic API Key** — Required to use the Auto-Verify feature.

API keys are stored globally and shared across all profiles, so you only need to enter them once.

There is also a **Videos per creator** spinner. Set this to limit how many recent videos Kleos fetches per person. Set it to **All** (0) if you want the entire history.

### Verify
This tab is home to the Auto-Verify feature:
- **Community Description** — Describe what your community is about in 300 words or fewer.
- **Claude Model** — Pick the intelligence level you want for automatic verification.

### Profiles
See [Working with Profiles](#working-with-profiles) above.

### Roles
See [Roles](#roles) above.

### Appearance
- **Thumbnail Quality** — Choose between Low (uses cached thumbnails, faster) or High (re-downloads original thumbnails, sharper but slower).

### Notifications
- **View Count Alert Thresholds** — Comma-separated numbers (for example, `10000,100000,1000000`). Kleos will notify you when a creator's total views cross each threshold.
- **Subscriber Milestones** — Informational display showing the fixed milestones (1K, 5K, etc.).
- **Reset All Triggered Alerts** — Clears all previously-triggered alerts so they can fire again on the next data refresh.

---

## Importing & Exporting Creators

You can share individual members between computers or friends by exporting them as small files. Notes and tags are included in the export.

### Exporting a Creator
There are three ways to export a single member:
1. **Right-click their card** on the main dashboard and choose **Export Creator**.
2. **Open their Media History** window and click the **Export** button at the top.
3. In the **Settings → Profiles** tab, click **Export Creator**.

Kleos will ask where to save a `.json` file. Give it a clear name (for example, `AliceCreator.json`) and save it.

### Importing a Creator
There are two ways to bring a creator file into Kleos:
1. **Drag and drop** the `.json` file directly onto the main dashboard. Kleos will detect it and add the member to your current profile.
2. Go to **Settings → Profiles** and click **Import Creator**. Browse to the `.json` file and select it.

### Merging Duplicate Creators
If you import a creator whose YouTube or Twitch link matches someone already in your community, Kleos will ask:
> "A creator with this link already exists. Merge media into the existing creator?"

- **Yes** — The imported content (videos, streams) will be merged into the existing creator. No duplicate will be created.
- **No** — The import is skipped and the existing creator remains unchanged.

---

## Importing & Exporting Profiles

Profiles can be exported as single files too, making it easy to back up your entire community or move it to another computer. Notes, tags, and community descriptions are included in profile exports.

### Exporting a Profile
1. Open **Settings → Profiles**.
2. Click **Export Profile**.
3. Choose a safe location and filename. The file will be saved as `.json`.

This file contains every member (with notes, tags, and community description), every video, every role, and all settings for that profile. **API keys are not included** — they are stored globally and shared across profiles.

### Importing a Profile
There are two ways to import a profile:
1. **Drag and drop** the `.json` file onto the main dashboard. Kleos will recognize it as a full profile, create a new profile with the same name (or a numbered variation if the name already exists), and switch to it automatically.
2. Open **Settings → Profiles**, click **Import Profile**, and browse to the `.json` file.

> **Note:** Importing a profile always creates a brand-new profile. It will not overwrite your current one.

---

## Search, Sort & Filter

These tools are located just below the top button row on the main dashboard.

### Search
Type into the **Search members…** box (or press **Ctrl+F** to focus it). The list filters after a short pause, showing only members whose nickname or tags contain what you typed. Press **Escape** to clear the search.

### Sort
Use the **Sort** dropdown to reorder the cards:
- **Date Added** — Newest members first.
- **Name** — Alphabetical by nickname.
- **Subscribers** — Highest subscriber / follower count first.

### Filter
Use the **Filter** dropdown to show only members with a specific role, or choose **All Roles** to see everyone.

### History Sort & Filter
Inside any member's Media History window, you can also sort and filter the content list:
- **Sort** — Date (newest), Date (oldest), Title A-Z, Views (high-low).
- **Filter** — All, Verified only, Shorts only, Videos only, Streams only.
- **Search** — Type to search content by title.
- **Right-click → Content Type Override** — If Kleos misclassified a video, right-click the row and choose "Set as Video," "Set as Short," or "Set as Stream." You can also "Reset to Auto-Detect" to undo the override. Overrides are saved permanently and survive data refreshes.

---

## Tips & Shortcuts

- **Keyboard Shortcuts:**
  - **Ctrl+R** — Refresh All (fetch latest data for everyone).
  - **Ctrl+N** — Add a new media member.
  - **Ctrl+F** — Focus the search bar and select all text.
  - **Escape** — Clear the search box (if it has text), or toggle fullscreen (if the search is empty).
  - **F11** — Toggle fullscreen mode.
  - **Tab** — Move focus onto the card grid.
  - **Up / Down arrows** — Navigate between cards when one is focused.
  - **Enter** — Open the focused card's Media History.
- **Tooltips:** Hover over any toolbar button or control to see a short description.
- **Cooldown Timer:** After a Refresh All, there is a short cooldown period. A countdown timer in the status bar shows how many seconds remain before you can refresh again.
- **New Activity Alert:** The orange ⚠ on a card disappears automatically when you open that member's Media History window.
- **Cancel Long Operations:** Both **Refresh All** and **Auto-Verify** can be cancelled if you change your mind or need to do something else urgently.
- **Drag & Drop Import:** Keep a folder of creator or profile exports handy on your desktop. Dragging them straight onto Kleos is the fastest way to import.
- **Right-Click Context Menu:** Right-click any creator card to quickly edit fields, change role, manage tags, delete the member, add notes, or export their data.
- **Creator Notes:** Every member has a notes field. Access it from the right-click menu (**Edit Notes**) or directly in the Media History header. Notes auto-save as you type with a "Saving…" → "Saved ✓" indicator.
- **Tags:** Use tags to label and group members. They show up as small chips on cards and are searchable from the main search box.
- **Activity Sparkline:** The 7 dots on each card show weekly upload activity at a glance — brighter and bigger dots mean more activity that week.
- **Milestone Alerts:** Watch for toast notifications in the top-right corner when creators hit subscriber milestones or view count thresholds.
- **HTML Export:** Use the **Export HTML** button in the Analytics window or any member's Stats tab to create a shareable community dashboard page.
- **Content Type Override:** Right-click any content row in a member's Media History to manually set its type (Video, Short, Stream) if Kleos misclassified it. Overrides persist across data refreshes.
- **Maximize:** The Analytics and Media History windows can be maximized using the standard maximize button in the title bar.

---

That's everything you need to know to get the most out of Kleos. Enjoy keeping your community organized!