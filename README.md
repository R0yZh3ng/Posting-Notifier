# Posting Notifier

Continuously crawls software company job boards, notifies you when a new posting
matches your criteria, and keeps a running list of every match with links.

## Setup

```sh
uv sync
```

Edit `config.yaml`:

- `criteria.include` / `exclude`: keywords (regex, case-insensitive, whole-word) matched against the job title.
- `criteria.locations`: optional keywords matched against title + location.
- `companies`: boards to watch. Supported `type`s: `greenhouse`, `lever`, `ashby`, `workable`,
  `smartrecruiters`, and `html` (generic scraper with a CSS `selector` + href `pattern`).
  The `slug` is the identifier in the company's careers URL, e.g. `boards.greenhouse.io/<slug>`,
  `jobs.lever.co/<slug>`, `jobs.ashbyhq.com/<slug>`.
- `notify.desktop`: macOS notification. `notify.webhook`: Slack or Discord incoming webhook URL.

Prefer `config.local.yaml` (gitignored) if you put a webhook URL in there; it overrides `config.yaml`.

## Run

```sh
uv run notifier once          # crawl everything one time
uv run notifier run           # crawl forever, every poll_interval_minutes
uv run notifier run --interval 10
uv run notifier list          # print every matching job seen so far
uv run notifier rebuild       # regenerate jobs.md / jobs.html from the database
```

The first crawl on an empty database records existing matches silently so you are not
flooded with hundreds of alerts. Pass `--notify-first-run` to change that.

Outputs: `jobs.md` (newest first) and `jobs.html` (grouped by company), both regenerated
after every crawl. State lives in `jobs.db` (SQLite); delete it to start fresh.

## Run in the background (macOS)

```sh
cp com.posting-notifier.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.posting-notifier.plist
tail -f notifier.log
```

`launchctl unload ~/Library/LaunchAgents/com.posting-notifier.plist` stops it.
