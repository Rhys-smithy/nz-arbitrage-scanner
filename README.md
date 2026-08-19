# NZ Auction Opportunity Scanner

Tracks 4 categories across Turners, Thorntons, and Mainland Auctions, scores
opportunities, and writes a CSV report (plus a Telegram ping) of what's
worth watchlisting yourself.

**Two very different levels of confidence in this report, by design:**

- **Turners (real value scoring):** Turners has a separate, fully
  server-rendered catalog view with genuine per-item prices, reserve
  status, and condition ratings. The scanner groups similar items (e.g.
  three different "18V Drill" listings), has Claude compare price against
  condition across the group, and estimates roughly how far below retail
  each one sits. This is a real, if still approximate, value judgement.
- **Thorntons & Mainland Auctions (blurb scoring only):** both run
  JavaScript-only live bidding platforms with no equivalent static catalog
  -- individual lot prices and condition simply aren't visible to a
  lightweight scraper (confirmed: even Google can't index Thorntons'
  bidding platform, it's a pure JS app). So these get scored on the
  auction-EVENT listing language only (words like "unreserved,"
  "liquidation," "deceased estate") -- a much weaker signal. Every row is
  labelled with its `data_basis` so you always know which kind you're
  looking at.

## Categories tracked

**General Goods** (Turners' server-rendered catalog, real prices):
Electronics & Tech, Machinery & Tools, Sport & Leisure, Jewellery & Watches,
Toys & Games, House & Garden, Health & Beauty, Antiques & Collectables,
Clothing, Automotive Parts.

**Vehicles** (a different part of Turners' site -- Year/Make/Model listings,
odometer, Buy Now prices): Cars, Trucks & Machinery, Motorbikes, Trailers &
Caravans. Built from a smaller real-page sample than General Goods, so
treat this one as less battle-tested -- check `scanner/scrapers/
turners_vehicles.py` first if a vehicle division returns 0 results.

Edit `config.json` → `turners_categories` / `watch_categories` to change
these -- see "Configuration" below.

## Guaranteeing at least a couple of items per category

If a category doesn't have enough similar items to form a real comparison
group, the scanner backfills with the cheapest ungrouped items instead of
reporting nothing -- these get an individual AI assessment (judged against
general knowledge of typical pricing, not group peers) and are clearly
flagged `"No comparable item found this run"` in the `notes` column so you
know it's a weaker signal than a real group comparison. Controlled by
`min_items_per_category` in config.json (default 2).

## What this does and doesn't do

- **Does:** scrape Turners' real catalog prices + condition, have Claude
  score value within each group of similar items, scrape Thorntons/Mainland
  Auctions event listings and score them on listing language, build
  one-click Trade Me / Facebook Marketplace / eBay-sold-listings search
  links for every match, and write a report capped to your top N per
  category (default 3).
- **Doesn't:** know the actual FINAL winning bid (only current bid at
  scrape time), guarantee the "estimated new price" is accurate (it's
  Claude's general knowledge, not a live retail lookup -- always verify
  anything that matters), or run continuously by itself.
- **On "estimated new price":** treat this as a rough sanity-check, not a
  quote. It can be wrong for newer products, regional pricing, or obscure
  items -- Claude is told to return nothing rather than guess wildly when
  unsure, so a blank value means "no reliable estimate," not zero.

## Setup

1. Install Python 3.9+ if you don't already have it.
2. Open a terminal in this folder and install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Add your Anthropic API key (same account as Cinder & Rune's API billing)
   to `config.json` → `"anthropic_api_key"`, or set it as an environment
   variable / GitHub secret (see "Running it from your phone" below). Cost
   is small -- Claude Haiku, only called on items that already matched a
   category or grouped with similar peers.
4. (Optional but recommended) Set up Telegram notifications -- see below.

## Configuration (`config.json`)

- `turners_categories` -- list of category names to run the real Turners
  value-scoring pipeline for. Must match keys in `CATEGORY_SLUGS` inside
  `scanner/scrapers/turners_catalog.py` (that's where the actual Turners
  category URL slugs live -- edit both together if you add a category).
- `watch_categories` -- keyword lists used to match Thorntons/Mainland
  Auctions event blurbs. Keys should match `turners_categories` names so
  everything lands in the same report sections.
- `sites` -- turn Thorntons / Mainland Auctions on or off individually.
  Turners always runs (it's the primary real-data source).
- `max_items_per_category` -- report cap per category, highest score first.
- `min_group_size` / `similarity_threshold` -- control how Turners items get
  grouped for comparison. Lower `similarity_threshold` groups more loosely
  (more false-positive groupings); higher is stricter (more singletons get
  dropped since there's nothing to compare them against).

## Running it

```
python main.py              # normal run — only reports NEW listings since last run
python main.py --rescan     # ignore history, report everything currently matching
```

Reports land in `reports/opportunities_<timestamp>.csv`, grouped by
category with a blank separator row between each, highest-scored items
first.

**First run:** if the Turners catalog scraper returns 0 results, or a
Thorntons/Mainland scraper returns 0, the site likely changed its page
structure -- check the relevant file in `scanner/scrapers/`.

## The spreadsheet report

Alongside the CSV, every run also generates an `.xlsx` version with **live
formulas** — one row per opportunity, plus editable assumption cells at the
top (buyer's premium %, marketplace fee %, listing/postage cost). Change an
assumption once and every row's landed cost / net resale / profit
recalculates automatically. This is the same math as a standalone
landed-cost calculator, just applied across every opportunity in one sheet
instead of one item at a time.

It's delivered straight to your Telegram chat as a file attachment (not
just linked) so you don't need to dig through GitHub Actions artifacts to
get it — look for the document alongside the text summary each run.

## Hunting: starring opportunities to track

`reports/deal_queue.html` (the Command Centre / Deal Queue dashboard) has a
star on every opportunity. Starring one marks it "Hunting" -- I'm
interested, keep tracking it -- and saves your own notes and target-offer
price against it, kept completely separate from anything the scanner
computes.

`deal_queue.html` is a plain generated static file with no server of its
own, so a star click has nowhere to write to unless something is
listening. Run:

```
python -m scanner.dashboard_server
```

then open the URL it prints (`http://127.0.0.1:8765/deal_queue.html`)
instead of double-clicking the file. The status line at the top of the
page tells you whether starring is live ("stars save to disk") or you're
looking at a read-only snapshot (opened via `file://`, or the server
isn't running). Stop the server with Ctrl+C when you're done -- it's a
small stdlib-only script (no new dependency, no database), meant to run
only while you're actively reviewing the dashboard.

Stars persist in `data/hunting_state.json` and survive both a plain
browser refresh (the page re-fetches live state from the server) and the
next scan run regenerating the dashboard (a read-only snapshot is always
embedded in the freshly generated file too). That file isn't touched by
`.gitignore`, so if you want a star made locally to show up the next time
the scheduled GitHub Actions run regenerates the dashboard, commit and
push it yourself (`git add data/hunting_state.json`) -- there's no
automatic sync between your machine and the cloud run yet.

Hunting today is intentionally just: starred, when you starred it, your
own notes, and an optional target-offer price shown next to (never
replacing) the scanner's own computed max buy price. Purchased/Sold
stages, price-drop tracking, and notifications build on this same record
later but aren't implemented yet.

## Reading the report

- `data_basis` — "Real price + condition" (Turners) vs "Listing language
  only" (Thorntons/Mainland) — always check this before trusting a score.
- `score` — 1-10, higher = more promising.
- `reasons` — quick-scan bullet points for the score.
- `explanation` — the actual reasoning, 1-2 full sentences, for when you
  want the "why" instead of just a number.
- `buy_now_price_nzd` — set when a listing has an instant Buy Now option
  (common on vehicle listings, occasional on General Goods) instead of or
  alongside a bid price.
- `suggested_resale_price_nzd` / `potential_profit_nzd` / `potential_profit_pct` —
  Claude's estimate of what this specific item (in its actual condition) would
  sell for secondhand on Trade Me/Facebook Marketplace NZ, and the resulting
  gross margin against the current auction price. **This is a starting
  estimate, not a real quote** — it does NOT include buyer's premium, GST,
  platform selling fees, or shipping. Once you actually know your winning
  bid price, run it through the landed-cost spreadsheet (ask Claude for one
  if you don't have it handy) for the real numbers before deciding.
- `value_vs_new_pct` — roughly how far below Claude's estimated NEW/retail price
  the current bid sits (Turners items only, and only when Claude was
  confident enough to estimate a new price). Different from the resale
  margin above — this compares against buying new, not reselling secondhand.
- `trademe_search_url` / `facebook_search_url` / `ebay_search_url` — one-tap
  manual comparable-price checks. eBay's link uses their sold+completed
  listings filter, the closest thing to real sold-price data available
  anywhere in this report (see below).

## Why not more price data everywhere?

- **Trade Me:** their API terms as of 2026 restrict registration to
  approved in-trade/commercial sellers, explicitly excluding personal-use
  tools like this one. Their website also doesn't publicly show past sold
  prices (unlike eBay), even to browse manually.
- **Facebook Marketplace:** no public API, actively blocks automated
  scraping, requires login for real access.
- **Thorntons / Mainland Auctions:** JavaScript-only live bidding platforms,
  no static catalog to scrape (Turners is the exception here, not the rule).
- **eBay:** does support a public sold-listings search, so that's included
  as a search link. NZ presence is thin though (Trade Me dominates) --
  treat eBay results as "what's this worth on the wider market," not what
  NZ buyers are actually paying.

## Running it from your phone

A background script can't literally live on your phone, but you can get the
same effect two ways, and I'd set both up together:

### 1. Automatic scheduled runs (no phone action needed)

This repo includes a GitHub Actions workflow (`.github/workflows/scan.yml`)
that runs the scanner daily in the cloud -- free, no server to maintain.

1. Push this folder to a **private** GitHub repo
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret**, add:
   - `ANTHROPIC_API_KEY` (from console.anthropic.com -- same account as your Cinder & Rune API billing)
   - `TELEGRAM_BOT_TOKEN` (see below)
   - `TELEGRAM_CHAT_ID` (see below)
3. Done -- it now runs every day at 6am NZST automatically (edit the `cron`
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
   and find `"chat":{"id": ...}` in the response -- that's your **chat ID**
4. Add both as GitHub secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) as above

Now every run that finds new matches pushes a summary straight to your
Telegram app, grouped by category with clickable links and scores -- check
it from anywhere. The full CSV is also attached to each GitHub Actions run
under "Artifacts" if you want the complete detail.

## Scheduling regular scans locally instead (Windows Task Scheduler)

If you'd rather not use GitHub Actions, this also works run entirely from
your own PC on a schedule -- you just won't get the "trigger from phone"
part, only the Telegram notifications (which still work either way).

1. Open **Task Scheduler** → **Create Basic Task**
2. Name it e.g. "NZ Auction Scanner"
3. Trigger: **Daily**
4. Action: **Start a program**
   - Program/script: `C:\Path\To\Python\python.exe`
   - Arguments: `main.py`
   - Start in: wherever you put this folder
5. Finish, then right-click the task → **Run** once to confirm it works

## Being a good citizen about scraping

- The scrapers use a light rate limit (`request_delay_seconds` in config)
  and a descriptive User-Agent -- don't remove these or crank up frequency.
- Double-check each site's Terms of Service occasionally.
- This is built for personal, low-volume use, not commercial scale.

## Extending it

- **Add a Turners category:** add the real slug(s) to `CATEGORY_SLUGS` in
  `scanner/scrapers/turners_catalog.py` (check
  https://www.turners.co.nz/General-Goods/Search/ for the current list),
  then add the category name to `config.json` → `turners_categories`.
- **Add another blurb-scored site:** follow the pattern in
  `scanner/scrapers/thorntons.py`, register it in
  `scanner/scrapers/__init__.py` and `config.json` → `sites`.

## Phase 3: AI Flip Hunter -- opportunity discovery via web search

Everything above (Turners/Thorntons/Mainland scanning) is the original,
default `python3 main.py` pipeline and is unaffected by any of this.
Phase 3 adds a second, separate entry point:

```
python3 main.py --mode discover
```

which searches the open web (via a configured search API, not direct
scraping) for resale opportunities beyond the three auction sites, runs
them through the same Phase 2 valuation/cost/max-buy-price/Flip Score
engine, and ranks the results. It does nothing until you opt in --
`config.json` → `"discovery"` → `"enabled"` defaults to `false`.

### AVAILABLE NOW vs REQUIRES API CREDENTIALS

| Capability | Status |
|---|---|
| Turners/Thorntons/Mainland scanning (`--mode scan`, default) | **Available now** -- no setup beyond what Phase 1/2 already needed |
| Deterministic valuation/cost/max-buy-price/Flip Score engine | **Available now** -- pure Python, no external service |
| `--mode discover` web search + comparable research | **Requires** a search provider API key (see below) |
| AI product identification / Researcher / Trader passes | **Requires** `ANTHROPIC_API_KEY` (same key Phase 2 already uses) -- without it, product ID is skipped and evidence review is skipped, discovery still runs on deterministic evidence stats alone |
| Telegram flip alerts from discovery mode | **Requires** `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (same as existing notifier) |

### Search provider setup

Discovery mode calls a legitimate third-party search API -- it never
scrapes Google/Bing/DuckDuckGo HTML directly and never bypasses a search
engine's bot protection. Set `WEB_SEARCH_PROVIDER` to select one:

**`tavily` -- recommended, free tier, no credit card** (verify current
terms at tavily.com before relying on this long-term; researched August
2026): 1,000 free API credits/month, basic search = 1 credit/request.
Supports domain-restricted search (used here instead of Google's `site:`
operator for e.g. `site:trademe.co.nz` style discovery).

```
WEB_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=<your key from tavily.com>
```

**`brave`** and **`serpapi`** -- also implemented and swappable via the
same `WEB_SEARCH_PROVIDER` env var, but as of the research done for this
phase (Feb 2026), Brave Search API dropped its free tier (now
credit-based/paid) and SerpApi has never had more than a 100-search trial.
Both are here as ready-to-use options if you later decide the paid tiers
are worth it -- they are **not** selected by default and require their own
`BRAVE_API_KEY` / `SERPAPI_API_KEY`.

With no `WEB_SEARCH_PROVIDER` set, discovery mode prints a clear
"not configured, no results fabricated" message and exits cleanly --
it never invents listings or prices.

### Environment variables (Phase 3 additions)

| Variable | Required for | Notes |
|---|---|---|
| `WEB_SEARCH_PROVIDER` | `--mode discover` | `tavily` (recommended), `brave`, or `serpapi` |
| `TAVILY_API_KEY` | `WEB_SEARCH_PROVIDER=tavily` | Free tier, no card |
| `BRAVE_API_KEY` | `WEB_SEARCH_PROVIDER=brave` | Paid as of Feb 2026 |
| `SERPAPI_API_KEY` | `WEB_SEARCH_PROVIDER=serpapi` | Paid, 100-search free trial only |
| `ANTHROPIC_API_KEY` | AI product ID + Researcher/Trader | Already used by Phase 2 |

### Rate limits / search budget

`config.json` → `"discovery"` controls how many searches a single
`--mode discover` run can make:

```json
"discovery": {
  "enabled": false,
  "max_queries_per_run": 15,
  "max_results_per_query": 8,
  "max_research_items": 5,
  "prefer_purchase_price_below": 250,
  "products": ["Nintendo Switch", "Canon camera", ...]
}
```

At the shipped defaults, one run does at most 15 discovery queries plus up
to 5 researched candidates × ~4 comparable-research queries each (≈35
queries/run worst case). Run once daily and that comfortably fits inside
Tavily's 1,000/month free credits with room to spare; tune
`max_queries_per_run`/`max_research_items` down further, or run less than
daily, if you add more product categories.

### Legal / ToS limitations (unchanged from Phase 2, restated for Phase 3)

- No CAPTCHA bypass, no authentication bypass, no bot-detection evasion,
  no fake accounts, no scraping Trade Me or Facebook Marketplace directly,
  no scraping search engine result pages directly.
- Trade Me and Facebook Marketplace listings are only ever discovered
  through a search provider's already-public index (e.g. `site:
  trademe.co.nz` via the search API) -- this app never talks to either
  site's servers directly for discovery.
- eBay "sold" evidence comes from search-snippet text signals (e.g. a
  listing titled "... - sold") or explicit sold flags where the provider
  supplies one -- not from logging into eBay or using an unlicensed
  scraper.

### Example discovery command and output

```
$ python3 main.py --mode discover
[discover] running 15 discovery queries...
[discover] 42 raw results -> 18 unique listings (11 newly seen).

🔥 TOP FLIPS

1. Carrera Digital 132 GT Championship bundle NZ - Trade Me
Current: $180
Quick resale: $288-328
Expected profit: $40-80
ROI: 16%-32%
Max buy: $137
Score: 46
Confidence: 28%
Decision: PASS
Listing: https://www.trademe.co.nz/a/example-listing-1
...
```

(Real output depends entirely on what the configured search provider
actually returns that day -- the numbers above are from a mocked test run,
not a live scan, and are shown only to illustrate the report shape.)

### What Phase 3 does NOT do

- Does not scrape Trade Me, Facebook Marketplace, or any search engine's
  HTML directly.
- Does not fabricate comparable evidence, sold prices, or listings when a
  provider is unconfigured or a request fails -- it returns nothing and
  says so.
- Does not let AI perform final profit/ROI/max-buy-price arithmetic --
  that's still 100% Python (`scanner/valuation.py`, unchanged from Phase 2).
  The Researcher/Trader AI passes only interpret evidence and can flag
  specific comparables as unreliable; Python recomputes the valuation from
  whatever evidence remains.
- Does not yet have real eBay/Trade Me sold-price API integration (no
  licensed API wired up) -- eBay evidence today comes from search-snippet
  text signals only, which is weaker than a real sold-listings API and is
  labelled accordingly (`evidence_type`).
