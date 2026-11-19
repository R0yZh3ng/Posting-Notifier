from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import re
import sys
import time
from datetime import datetime

import yaml

from . import notify, report, sources
from .matcher import Matcher
from .store import Store


def load_config(path: str | None) -> dict:
    if path is None:
        path = "config.local.yaml" if os.path.exists("config.local.yaml") else "config.yaml"
    with open(path) as f:
        cfg = yaml.safe_load(f)
    if path == "config.local.yaml" and os.path.exists("config.yaml"):
        with open("config.yaml") as f:  # local file only needs the keys it overrides
            cfg = _merge(yaml.safe_load(f), cfg)
    return cfg


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def run_once(cfg: dict, store: Store, quiet_first_run: bool, workers: int = 8) -> int:
    """Crawl every company once. Returns number of new matching jobs."""
    matcher = Matcher(cfg.get("criteria", {}))
    companies = cfg.get("companies", [])
    new_matches = 0
    baselined = []
    fresh = []  # new matches to include in the email digest

    def fetch(c):
        try:
            return c, sources.fetch(c), None
        except Exception as e:  # one bad company must not stop the crawl
            return c, [], e

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for c, jobs, err in ex.map(fetch, companies):
            if err is not None:
                print(f"  ! {c.get('name', '?')}: {err}")
                continue
            # A company's very first crawl is recorded silently so adding it doesn't flood you.
            quiet = quiet_first_run and store.first_crawl(c["name"])
            new_here = 0
            for job in jobs:
                matched = matcher.matches(job)
                if store.upsert(job, matched) and matched:
                    new_here += 1
                    if quiet:
                        continue
                    print(f"  + {job.company}: {job.title} [{job.location}] {job.url}")
                    notify.send(cfg.get("notify", {}), job)
                    fresh.append(job)
            store.commit()
            if quiet:
                baselined.append((c["name"], new_here))
            else:
                print(f"  {c['name']}: {len(jobs)} postings, {new_here} new matches")
            new_matches += new_here
    notify.email_digest(cfg.get("notify", {}), fresh)
    notify.ntfy_digest(cfg.get("notify", {}), fresh)
    report.write_all(cfg.get("output", {}), store)
    if baselined:
        n = sum(k for _, k in baselined)
        print(f"First crawl of {len(baselined)} new compan{'y' if len(baselined)==1 else 'ies'}: "
              f"recorded {n} existing matches without notifying.")
    return new_matches


def summary(new: int, store: Store, cfg: dict) -> str:
    total = len(store.matched_jobs())
    md = cfg.get("output", {}).get("markdown", "jobs.md")
    return (f"{new} new matching job(s) since last crawl. {total} matching job(s) total; "
            f"full list in {md} or `notifier list`.")


def parse_since(text: str | None) -> float | None:
    """'24h', '3d', '90m' -> hours."""
    if not text:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([hdm]?)", text.strip().lower())
    if not m:
        raise SystemExit(f"bad --since {text!r}; use e.g. 24h or 3d")
    n, unit = float(m.group(1)), m.group(2) or "h"
    return n * {"h": 1, "d": 24, "m": 1 / 60}[unit]


def cmd_list(cfg: dict, store: Store, since: str | None = None) -> None:
    rows = store.matched_jobs(since_hours=parse_since(since))
    for r in rows:
        loc = f" ({r['location']})" if r["location"] else ""
        print(f"{r['posted'][:10]}  {r['company']:<18} {r['title']}{loc}\n{'':30}{r['url']}")
    print(f"\n{len(rows)} matching jobs")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="notifier", description="Watch company job boards for new matching postings.")
    p.add_argument("-c", "--config", help="config file (default: config.local.yaml, else config.yaml)")
    p.add_argument("--db", default="jobs.db", help="sqlite database path")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once", help="crawl every company one time")
    r = sub.add_parser("run", help="crawl continuously")
    r.add_argument("--interval", type=float, help="minutes between crawls (overrides config)")
    ls = sub.add_parser("list", help="print matching jobs")
    ls.add_argument("--since", help="only jobs posted within this window, e.g. 24h or 3d")
    sub.add_parser("test-email", help="send a sample digest email to check your SMTP settings")
    sub.add_parser("rebuild", help="regenerate jobs.md / jobs.html from the database")
    u = sub.add_parser("ui", help="open the web interface")
    u.add_argument("--port", type=int, default=8765)
    u.add_argument("--no-browser", action="store_true", help="don't open a browser tab automatically")
    for s in sub.choices.values():
        s.add_argument("--notify-first-run", action="store_true",
                       help="notify for every existing match on a company's first crawl instead of staying quiet")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    store = Store(args.db)
    quiet = not args.notify_first_run

    if args.cmd == "ui":
        from . import ui
        ui.serve(cfg, args.db, lambda c, s, q: run_once(c, s, q), args.port, not args.no_browser)
    elif args.cmd == "test-email":
        from .models import Job
        sample = [Job("Example Co", "Software Engineer Intern, Summer 2027", "https://example.com/jobs/1", "Remote")]
        if not notify._email_cfg(cfg.get("notify", {})):
            raise SystemExit("Set notify.email.enabled: true plus smtp_host, username, password and to.")
        notify.email_digest(cfg.get("notify", {}), sample)
    elif args.cmd == "list":
        cmd_list(cfg, store, args.since)
    elif args.cmd == "rebuild":
        report.write_all(cfg.get("output", {}), store)
        print("Rebuilt report files.")
    elif args.cmd == "once":
        n = run_once(cfg, store, quiet)
        print(summary(n, store, cfg))
    elif args.cmd == "run":
        interval = args.interval or cfg.get("poll_interval_minutes", 30)
        print(f"Polling every {interval} min. Ctrl-C to stop.")
        while True:
            print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] crawling…")
            try:
                n = run_once(cfg, store, quiet)
                print(summary(n, store, cfg))
            except Exception as e:
                print(f"crawl failed: {e}", file=sys.stderr)
            try:
                time.sleep(interval * 60)
            except KeyboardInterrupt:
                print("\nStopped.")
                return


if __name__ == "__main__":
    main()
