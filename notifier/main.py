from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
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
        return yaml.safe_load(f)


def run_once(cfg: dict, store: Store, quiet_first_run: bool, workers: int = 8) -> int:
    """Crawl every company once. Returns number of new matching jobs."""
    matcher = Matcher(cfg.get("criteria", {}))
    companies = cfg.get("companies", [])
    new_matches = 0
    baselined = []

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
            store.commit()
            if quiet:
                baselined.append((c["name"], new_here))
            else:
                print(f"  {c['name']}: {len(jobs)} postings, {new_here} new matches")
            new_matches += new_here
    report.write_all(cfg.get("output", {}), store.matched_jobs())
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


def cmd_list(cfg: dict, store: Store) -> None:
    rows = store.matched_jobs()
    for r in rows:
        loc = f" ({r['location']})" if r["location"] else ""
        print(f"{r['first_seen'][:10]}  {r['company']:<18} {r['title']}{loc}\n{'':30}{r['url']}")
    print(f"\n{len(rows)} matching jobs")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="notifier", description="Watch company job boards for new matching postings.")
    p.add_argument("-c", "--config", help="config file (default: config.local.yaml, else config.yaml)")
    p.add_argument("--db", default="jobs.db", help="sqlite database path")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once", help="crawl every company one time")
    r = sub.add_parser("run", help="crawl continuously")
    r.add_argument("--interval", type=float, help="minutes between crawls (overrides config)")
    sub.add_parser("list", help="print all matching jobs seen so far")
    sub.add_parser("rebuild", help="regenerate jobs.md / jobs.html from the database")
    for s in sub.choices.values():
        s.add_argument("--notify-first-run", action="store_true",
                       help="notify for every existing match on a company's first crawl instead of staying quiet")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    store = Store(args.db)
    quiet = not args.notify_first_run

    if args.cmd == "list":
        cmd_list(cfg, store)
    elif args.cmd == "rebuild":
        report.write_all(cfg.get("output", {}), store.matched_jobs())
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
