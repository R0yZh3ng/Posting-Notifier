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
- `companies`: boards to watch (400+ preloaded, all verified live). Supported `type`s:
  `greenhouse`, `lever`, `ashby`, `workable`, `smartrecruiters`, `workday`, and `html`
  (generic scraper with a CSS `selector` + href `pattern`).
  The `slug` is the identifier in the company's careers URL, e.g. `boards.greenhouse.io/<slug>`,
  `jobs.lever.co/<slug>`, `jobs.ashbyhq.com/<slug>`. Workday boards take the public careers `url`
  plus an optional `search` term, since those boards have thousands of postings.
- `notify.desktop`: macOS notification. `notify.webhook`: Slack or Discord incoming webhook URL.

Prefer `config.local.yaml` (gitignored) if you put a webhook URL in there; it overrides `config.yaml`.

## Run

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
