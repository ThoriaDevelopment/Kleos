# Kleos User Manual

**Kleos** — your personal media management dashboard. Kleos helps you keep track of all the creators and streamers in your community in one beautiful, easy to use window. You can see who’s been active, how their content is performing, and keep everything organized without ever needing a spreadsheet again.

---

## Table of Contents

1. [Getting the App](#getting-the-app)
2. [First-Time Setup](#first-time-setup)
3. [The Main Dashboard](#the-main-dashboard)
4. [Adding a Media Member](#adding-a-media-member)
5. [Reading a Creator Card](#reading-a-creator-card)
6. [Opening a Member’s History & Stats](#opening-a-members-history--stats)
7. [Verification](#verification)
8. [Leaderboard & Analytics](#leaderboard--analytics)
9. [Generating Reports](#generating-reports)
10. [Working with Profiles](#working-with-profiles)
11. [Roles](#roles)
12. [Settings](#settings)
13. [Importing & Exporting Creators](#importing--exporting-creators)
14. [Importing & Exporting Profiles](#importing--exporting-profiles)
15. [Search, Sort & Filter](#search-sort--filter)
16. [Tips & Shortcuts](#tips--shortcuts)

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

When you open Kleos for the first time, it will create its home folder automatically and start with a default profile named `default`. Before the app can fetch videos and stats from YouTube or Twitch, you will need to add your API keys in **Settings**.

Don’t worry — this sounds more technical than it is. Think of an API key like a password that lets Kleos politely ask YouTube and Twitch, “What’s new?” on your behalf.

### Where to get a YouTube Data API key
Here is a quick example of how to get the key for YouTube:

1. Open your web browser and go to the **Google Cloud Console** (search for it on Google).
2. Sign in with your Google account.
3. Create a **new project** and give it any name you like (for example, “Kleos Dashboard”).
4. In the left-hand menu, click **APIs & Services → Library**.
5. Search for **YouTube Data API v3** and click it.
6. Press the **Enable** button.
7. Now click **Credentials** in the left-hand menu, then **Create Credentials → API key**.
8. Google will show you a long string of letters and numbers — that is your key. Copy it.
9. Back in Kleos, click **⚙ Settings** at the top of the main window.
10. Go to the **API Keys** tab and paste the key into the **YouTube API Key** box.
11. Click **OK** to save.

You only have to do this once. If you also want Twitch data, the Twitch Client ID and Secret follow a similar process on the Twitch Developer portal. The Anthropic key is only needed if you plan to use Auto-Verify later.

Once your keys are saved, you’re ready to build your community list.

> **Note:** If you see an orange banner saying “API keys missing,” simply click **Open Settings** inside that banner and follow the steps above.
>
> **Important:** Before you can click **+ Add Media Member**, you must create at least one role. Every member needs a role assigned to them. To create your first role, click **⚙ Settings**, go to the **Roles** tab, type a name (for example, “Member”), pick a color, and click **Add Role**. Once you have at least one role, you are ready to add people to your community.

---

## The Main Dashboard

The main window is your home base. It shows every person in your community as a card in a scrollable list. At the very top are the controls you’ll use most often:

- **+ Add Media Member** — Opens a form to add someone new.
- **⟳ Refresh All** — Fetches the latest videos, streams, stats, and thumbnails for everyone at once.
- **✓ Auto-Verify** — Runs an automatic check on unverified videos to see if they belong in your community.
- **⚙ Settings** — Opens the settings panel for keys, profiles, roles, and appearance.
- **♛ Leaderboard** — Opens the global analytics and ranking window.

Below those buttons you’ll find:
- A **Search** box to quickly find someone by nickname.
- A **Sort** dropdown (Date Added, Name, or Subscribers).
- A **Filter** dropdown to show only people with a certain role.
- A **Profile** dropdown to switch between different saved lists.

The background of the dashboard gently shifts between soft colors, giving the app a calm, modern feel.

---

## Adding a Media Member

To add someone to your community:

1. Click **+ Add Media Member** at the top left.
2. Fill out the form:
   - **Nickname** — The name you want to see in the dashboard (this can be their channel name or a custom name).
   - **Platforms** — Check the boxes for **YouTube**, **Twitch**, or both.
   - **Channel Links** — When you check a platform, a text box will appear where you can paste the direct link to their channel (for example, a YouTube channel URL or a Twitch channel URL).
   - **Role** — Choose a role from the dropdown. Roles are like tags that group people together (for example, “Founder,” “Streamer,” or “Editor”). You can create your own roles in Settings.
3. Click **OK**. The new member will appear immediately in your dashboard.

> **Tip:** You must create at least one role before you can add any members. You can do this in **Settings → Roles**.

---

## Reading a Creator Card

Each person in your community appears as a card. From left to right, a card shows:

- **Nickname** — The name you gave them.
- **Avatar** — Their channel profile picture (fetched automatically once data comes in).
- **Platform Tag** — Tells you at a glance if they are a “Creator” (YouTube), “Streamer” (Twitch), or “Streamer / Creator” (both).
- **Subscribers / Followers** — Compact numbers like `1.2M subs` or `450K flw`.
- **Activity Alert** — An orange ⚠ icon appears when new content has been detected since the last time you looked at their history.
- **Last Activity** — How long ago their most recent video or stream went live.
- **Duration** — How long this person has been in your community (based on the date you added them).

The left edge of each card is colored according to their role, so you can spot groups instantly.

Cards react smoothly when you move your mouse over them, lifting slightly and glowing softly.

---

## Opening a Member’s History & Stats

To dive deeper into a single person, **double-click their card** (or right-click it and choose an action). A new window titled *Media History* will open. This window has two tabs.

### Media Tab
Here you see every video or stream Kleos has fetched for this person, arranged from newest to oldest. Each row shows:
- A **thumbnail** image.
- The **title** of the video or stream.
- How long ago it was **uploaded** or went live.
- A **Verify / In Community** button to mark whether this piece of content belongs in your community.
- The **view count**.

At the bottom of the list you’ll see a count like “Showing 50 of 120” and a **Load More** button if there are additional items to display.

If you **double-click** any row, it will open that video or stream directly in your web browser.

The top of the window also shows:
- Their **nickname** and **subscriber / follower counts**.
- When their **last verified content** was published.
- Buttons to **Refresh Content**, **Delete Member**, or **Export** this member’s data.

### Stats Tab
This tab displays two interactive charts for the selected member:
- A **line chart** showing their view trajectory over time.
- A **bar chart** showing how many pieces of content they uploaded each month.

You can check the box labeled **Show Non-Verified Content** to include everything in these charts, or leave it unchecked to see only verified content.

Both charts can be zoomed in and out with your mouse wheel, panned by clicking and dragging, and reset by double-clicking.

---

## Verification

Verification is how you tell Kleos, “Yes, this video or stream belongs to our community.” Verified content is counted in leaderboards, charts, and reports. Unverified content is hidden from those summaries by default.

### Manual Verification
Inside any member’s *Media History* window, you’ll see a button on every row:
- **Verify** (gray) — This content is not yet approved.
- **In Community** (green) — This content is approved.

Simply click the button to toggle it.

### Auto-Verify
If you have an Anthropic API key saved in Settings, you can let Kleos verify videos automatically:

1. Go to **Settings → Verify** and write a short **Community Description**. This tells the assistant what your community is about (for example, “A Minecraft survival community focused on redstone engineering”). Keep it under 300 words.
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

### Leaderboard Panel (Left Side)
The left side shows a ranked list of all your members based on total views. Each line looks like:

```
1. Nickname — 1,250,000 views | 1.2M subs
```

You can filter this list using the buttons at the top:
- **All** — Everyone.
- **YouTube** — Only YouTube creators.
- **Streamers** — Only Twitch streamers.

There is also a checkbox:
- **Show All Stats** — When checked, the leaderboard and charts count *every* piece of content, not just verified ones.

### Charts Panel (Right Side)
Two interactive charts sit on the right:
- **View Trajectory** — A line chart showing how views have accumulated across your community over time.
- **Monthly Upload Activity** — A bar chart showing how many videos or streams were uploaded each month.

Like the individual stats charts, you can zoom with the scroll wheel, pan by dragging, and reset by double-clicking. The charts update automatically when you change the platform filter or the verified-only toggle.

---

## Generating Reports

At the bottom of the Leaderboard window, you’ll find a report generator:

1. Choose a time period: **Monthly**, **Weekly**, or **Yearly**.
2. Optionally choose a **Role** to narrow the report to a specific group.
3. Click **Copy Report**.

Kleos builds a clean, plain-text summary and copies it directly to your clipboard. You can then paste it into Discord, a forum post, a text document, or anywhere else you like. The report includes:
- The date range covered.
- Total uploads and total views for that period.
- A ranked leaderboard of everyone included.
- Subscriber and follower counts where available.

---

## Working with Profiles

Profiles let you keep completely separate communities. For example, you might have one profile for your gaming team and another for your podcast network.

To manage profiles, open **Settings → Profiles**.

### Creating a New Profile
1. Type a name in the **New profile name** box.
2. Click **Create**.
3. Kleos switches to the new profile immediately. It starts empty, so you can add members from scratch.

### Switching Profiles
1. Select a profile name in the list.
2. Click **Switch To**.
3. The main dashboard will refresh to show the members of that profile.

### Deleting a Profile
1. Select a profile in the list.
2. Click **Delete**.
3. Confirm the deletion. **Warning:** This permanently deletes that profile and all its data. You cannot delete the profile you are currently using.

---

## Roles

Roles are a way to label and color-code members. Every member must have exactly one role.

To manage roles, open **Settings → Roles**.

### Adding a Role
1. Type a **Role name** (for example, “Admin” or “VIP”).
2. Either type a color code or click **Pick Color** to choose one visually.
3. Click **Add Role**.

### Deleting a Role
1. Select a role in the list.
2. Click **Delete Selected Role**.

You can only delete a role if no member is currently using it. If anyone is still assigned to it, Kleos will warn you and show you who needs to be reassigned first.

---

## Settings

The Settings window is split into tabs for easy navigation.

### API Keys
Here you enter the credentials that let Kleos talk to YouTube and Twitch:
- **YouTube API Key** — Required to fetch YouTube videos and channel stats.
- **Twitch Client ID & Secret** — Required to fetch Twitch streams and videos.
- **Anthropic API Key** — Required to use the Auto-Verify feature.

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

---

## Importing & Exporting Creators

You can share individual members between computers or friends by exporting them as small files.

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

The imported creator will appear immediately in your dashboard with all their history intact.

---

## Importing & Exporting Profiles

Profiles can be exported as single files too, making it easy to back up your entire community or move it to another computer.

### Exporting a Profile
1. Open **Settings → Profiles**.
2. Click **Export Profile**.
3. Choose a safe location and filename. The file will be saved as `.json`.

This file contains every member, every video, every role, and all settings for that profile.

### Importing a Profile
There are two ways to import a profile:
1. **Drag and drop** the `.json` file onto the main dashboard. Kleos will recognize it as a full profile, create a new profile with the same name (or a numbered variation if the name already exists), and switch to it automatically.
2. Open **Settings → Profiles**, click **Import Profile**, and browse to the `.json` file.

> **Note:** Importing a profile always creates a brand-new profile. It will not overwrite your current one.

---

## Search, Sort & Filter

These tools are located just below the top button row on the main dashboard.

### Search
Type into the **Search members…** box. As you type, the list instantly narrows to show only nicknames that contain what you typed.

### Sort
Use the **Sort** dropdown to reorder the cards:
- **Date Added** — Newest members first.
- **Name** — Alphabetical by nickname.
- **Subscribers** — Highest subscriber / follower count first.

### Filter
Use the **Filter** dropdown to show only members with a specific role, or choose **All Roles** to see everyone.

---

## Tips & Shortcuts

- **Fullscreen:** Press **F11** on your keyboard to make any window fill the entire screen. Press **F11** again (or **Escape**) to return to normal size.
- **Maximize:** The Leaderboard and Media History windows can be maximized using the standard window buttons in the title bar.
- **New Activity Alert:** The orange ⚠ on a card disappears automatically when you open that member’s Media History window.
- **Cancel Long Operations:** Both **Refresh All** and **Auto-Verify** can be cancelled if you change your mind or need to do something else urgently.
- **Drag & Drop Import:** Keep a folder of creator or profile exports handy on your desktop. Dragging them straight onto Kleos is the fastest way to import.
- **Keyboard Alternative:** If you prefer, you can right-click a creator card instead of double-clicking to open the context menu.

---

That’s everything you need to know to get the most out of Kleos. Enjoy keeping your community organized!
