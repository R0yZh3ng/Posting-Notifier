# Posting Notifier

Continuously crawls software company job boards, notifies you when a new posting
matches your criteria, and keeps a running list of every match with links.

## Setup

```sh
uv sync
```

Edit `config.yaml`:

- `criteria.include`: a title must contain one of these (e.g. intern, new grad, summer analyst).
- `criteria.require`: and one of these too (e.g. software, quant, engineer). Leave empty to skip.
- `criteria.exclude`: and none of these (marketing, mechanical, senior, ...).
  All three are case-insensitive regexes matched on whole words.
- `criteria.locations`: optional keywords matched against title + location.
- `companies`: boards to watch (500+ preloaded, including Canadian employers and big banks/tech). Supported `type`s:
  `greenhouse`, `lever`, `ashby`, `workable`, `smartrecruiters`, `workday`, `amazon`, `eightfold` (Microsoft, Netflix), and `html`
  (generic scraper with a CSS `selector` + href `pattern`).
  The `slug` is the identifier in the company's careers URL, e.g. `boards.greenhouse.io/<slug>`,
  `jobs.lever.co/<slug>`, `jobs.ashbyhq.com/<slug>`. Workday boards take the public careers `url`
  plus an optional `search` term or list of terms (e.g. `["intern", "co-op"]`), since those boards have thousands of postings.
- `notify.ntfy.topic`: free phone push, no account. Install the ntfy app, subscribe to your topic.
- `notify.email`: one digest email per crawl that finds new matches (see below).
- `notify.desktop`: macOS notification. `notify.webhook`: Slack or Discord incoming webhook URL.

Prefer `config.local.yaml` (gitignored) for secrets like webhook URLs and your email password. It only
needs the keys you want to override; everything else comes from `config.yaml`.

## Email notifications

Create `config.local.yaml`:

```yaml
notify:
  email:
    enabled: true
    smtp_host: smtp.gmail.com     # smtp.office365.com, smtp.fastmail.com, ...
    smtp_port: 587
    username: you@gmail.com
    password: "xxxx xxxx xxxx xxxx"   # Gmail: create an App Password at myaccount.google.com/apppasswords
    to: you@gmail.com
```

Then check it with `uv run notifier test-email`. After that, every crawl (CLI, `run`, or the web UI)
that finds new matches sends a single email listing them with links. The password can instead be set
via the `POSTING_NOTIFIER_SMTP_PASSWORD` environment variable. Remember the crawl has to be running
(`uv run notifier run`, or the UI with auto-crawl) for emails to arrive.

## Web UI

```sh
uv run notifier ui            # opens http://127.0.0.1:8765
```

Three views:

- **Jobs**: every match, with search, company / time-window / region (Canada, Vancouver, Toronto, Remote) filters.
  Save, mark Applied, or Hide any job.
- **Tracker**: a drag-and-drop board (Saved, Applied, Online assessment, Interview, Offer, Rejected, Withdrawn)
  with notes, dates, follow-up reminders, contact and salary. Add applications for jobs the crawler didn't find, export CSV.
- **Stats**: applications sent, response rate, pipeline, and follow-ups due.

Everything is stored in `jobs.db`.

**Eligibility filter.** The crawler reads each matching job's description and tags requirements: US citizenship /
ITAR, security clearance, "no visa sponsorship", Master's or PhD required. Click **My eligibility** in the Jobs view to
say what applies to you (US citizen or not, need sponsorship, degree level), then flip the **Eligible only** switch to hide
jobs you can't take. The switch always starts off. Hover a tag to see the sentence it came from, since it's keyword-based
and can be wrong. Jobs whose text couldn't be read are never hidden. Descriptions come with the crawl for
Greenhouse, Lever, Ashby and Amazon; Workday ones are fetched after each crawl (`uv run notifier enrich` backfills all). **Crawl now** runs a crawl with a live log, and **auto-crawl**
repeats it every `poll_interval_minutes` while the UI is open. Use `--port` or `--no-browser` as needed.

## Run (terminal)

```sh
uv run notifier once          # crawl everything one time
uv run notifier run           # crawl forever, every poll_interval_minutes
uv run notifier run --interval 10
uv run notifier list          # print every matching job seen so far
uv run notifier list --since 24h   # only jobs posted in the last day (also 3d, 90m, ...)
uv run notifier rebuild       # regenerate jobs.md / jobs.html from the database
```

The first crawl of any company records its existing matches silently, so adding companies
never floods you with alerts. Pass `--notify-first-run` to change that. A full crawl of all
companies takes about 3 minutes.

Outputs, all regenerated after every crawl:

- `jobs.md` / `jobs.html`: every current match, newest posting first.
- `jobs-24h.md` / `jobs-3d.md` (and `.html`): only matches posted in the last 24 hours / 3 days.
  Windows are set under `output.recent` in the config; add or change them freely.

Posting dates come from the job board itself (Greenhouse, Lever, Ashby, Workday, Workable,
SmartRecruiters all report one). For `html` sources the date is when the crawler first saw the job. State lives in `jobs.db` (SQLite); delete it to start fresh.

## Run in the background (macOS)

```sh
cp com.posting-notifier.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.posting-notifier.plist
tail -f notifier.log
```

`launchctl unload ~/Library/LaunchAgents/com.posting-notifier.plist` stops it.
