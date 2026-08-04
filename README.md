# NZ Auction Opportunity Scanner

Scans Thorntons, Turners General Goods, and Mainland Auctions for new
listings, matches them against keywords you care about, pulls Trade Me
comparable pricing where available, and writes a CSV report you can sort
through in Excel.

## What this does and doesn't do

- **Does:** scrape public auction listing pages, match against your
  keywords, look up Trade Me comparable pricing via their official API,
  build a one-click Facebook Marketplace search link for manual checking,
  and write a dated CSV report.
- **Doesn't:** know the actual winning bid price (that's only known once an
  auction closes), automate Facebook Marketplace (no public API, and
  scraping it violates their terms), or run continuously by itself — you
  need to schedule it (see below) or run it manually.
- **Reality check:** this surfaces *categories worth your attention*, not
  guaranteed profit. Always view items in person / read the manifest before
  bidding — auction terms almost always say goods can't be fully
  authenticated and are sold "as is."

## Setup

1. Install Python 3.9+ if you don't already have it.
2. Open a terminal in this folder and install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Get a free Trade Me API key (used for comparable pricing):
   - Register at https://developer.trademe.co.nz
   - Create an application, copy the **consumer key**
   - Paste it into `config.json` → `"trademe_api_key"`
4. Edit `config.json` to adjust:
   - `watch_categories` — a dict of category name → list of keywords/phrases
     to match on. Add, remove, or rename categories freely; the report will
     group and sort by whatever categories you define here.
   - `sites` — turn any site on/off
   - `min_trademe_comparables` — below this count, the report flags the item as "niche, price with care"

## Reading the report

The CSV is grouped by category (alphabetical, with a blank separator row
between each), and within a category the highest Trade Me comparable price
comes first — a rough "most worth a look" ordering. A listing that touches
more than one category gets filed under whichever it matched the most
keywords for, with the others noted in the `notes` column.

## Running it

```
python main.py              # normal run — only reports NEW listings since last run
python main.py --rescan     # ignore history, report everything currently matching
python main.py --dry-run    # skip Trade Me lookups (faster, good for testing the scrapers)
```

Reports land in `reports/opportunities_<timestamp>.csv`. Open in Excel,
sort by `trademe_median_price` or `trademe_comparable_count` to see what's
worth a closer look.

**First run:** use `--dry-run` first to confirm the scrapers are pulling
listings before burning Trade Me API calls. If a scraper returns 0 results,
the site likely changed its page structure — the `DETAIL_PATTERN` regex at
the top of the relevant file in `scanner/scrapers/` is the first thing to
check and update.

## Running it from your phone

A background script can't literally live on your phone, but you can get the
same effect two ways, and I'd set both up together:

### 1. Automatic scheduled runs (no phone action needed)

This repo includes a GitHub Actions workflow (`.github/workflows/scan.yml`)
that runs the scanner daily in the cloud — free, no server to maintain.

1. Push this folder to a **private** GitHub repo
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret**, add:
   - `TRADEME_API_KEY`
   - `TELEGRAM_BOT_TOKEN` (see below)
   - `TELEGRAM_CHAT_ID` (see below)
3. Done — it now runs every day at 6am NZST automatically (edit the `cron`
   line in the workflow file to change the schedule)

### 2. Manual on-demand runs from your phone

Once it's on GitHub: open the **GitHub mobile app** → your repo → **Actions**
tab → **NZ Auction Scanner** → **Run workflow**. That triggers a real run
on GitHub's servers from your phone, no laptop needed.

### 3. Get results as a phone notification (Telegram)

Telegram bots are free and take about 2 minutes:

1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts →
   copy the **bot token** it gives you
2. Message your new bot anything (e.g. "hi") so it can message you back
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
   and find `"chat":{"id": ...}` in the response — that's your **chat ID**
4. Add both as GitHub secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) as above

Now every run that finds new matches pushes a summary straight to your
Telegram app, grouped by category with clickable links — check it from
anywhere. The full CSV is also attached to each GitHub Actions run under
"Artifacts" if you want the complete detail.

## Scheduling regular scans locally instead (Windows Task Scheduler)

If you'd rather not use GitHub Actions, this also works run entirely from
your own PC on a schedule — you just won't get the "trigger from phone"
part, only the Telegram notifications (which still work either way).


1. Open **Task Scheduler** → **Create Basic Task**
2. Name it e.g. "NZ Auction Scanner"
3. Trigger: **Daily** (or however often you want — these sites post new
   auctions a few times a week, so daily or every-other-day is plenty)
4. Action: **Start a program**
   - Program/script: `C:\Path\To\Python\python.exe`
   - Arguments: `main.py`
   - Start in: `C:\projects\nz_arbitrage_scanner` (wherever you put this folder)
5. Finish, then right-click the task → **Run** once to confirm it works

Each run only reports *new* listings (tracked in `data/seen.json`), so your
inbox/folder won't fill up with repeats.

## Being a good citizen about scraping

- The scrapers use a light rate limit (`request_delay_seconds` in config)
  and a descriptive User-Agent — don't remove these or crank up frequency.
  Hammering these sites could get your IP blocked, and it's not necessary —
  new auctions don't appear that often.
- Double-check each site's Terms of Service occasionally; auction houses
  sometimes change their stance on automated access.
- This is built for personal, low-volume use — not for reselling the data
  or running at commercial scale.

## Extending it

- **Add another site:** create a new file in `scanner/scrapers/` following
  the pattern in `thorntons.py`, then register it in
  `scanner/scrapers/__init__.py` and `config.json`.
- **Mainland Auctions also sells via Trade Me** (seller ID 6482428) — see
  the comment in `scanner/scrapers/mainland_auctions.py` if you want to pull
  that in too via the Trade Me API's member-listing search.
- **Add price-drop tracking:** the `data/seen.json` cache currently only
  stores URLs; you could extend it to store the last-seen price and flag
  when a Trade Me listing's asking price drops.
