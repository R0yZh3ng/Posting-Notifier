"""Local web UI: browse matches, track applications, and trigger crawls from the browser."""
from __future__ import annotations

import csv
import io
import json
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .store import Store



class _Tee(io.TextIOBase):
    """Collects crawl output so the browser can show it live."""

    def __init__(self, lines: list[str], real):
        self.lines, self.real, self._buf = lines, real, ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.lines.append(line)
            del self.lines[:-500]
        return len(s)


class Crawler:
    """Runs crawls in a background thread; optionally repeats on an interval."""

    def __init__(self, cfg: dict, db: str, run_once, report_cfg_interval: float):
        self.cfg, self.db, self.run_once = cfg, db, run_once
        self.interval = report_cfg_interval
        self.auto = False
        self.running = False
        self.log: list[str] = []
        self.last_run: str | None = None
        self.last_new: int | None = None
        self.next_run: float | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def start(self) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
        threading.Thread(target=self._crawl, daemon=True).start()
        return True

    def _crawl(self) -> None:
        self.log.clear()
        self.log.append(f"[{datetime.now():%H:%M:%S}] crawling…")
        real, sys.stdout = sys.stdout, _Tee(self.log, sys.stdout)
        store = Store(self.db)
        try:
            self.last_new = self.run_once(self.cfg, store, True)
            self.log.append(f"Done: {self.last_new} new matching job(s).")
        except Exception as e:
            self.log.append(f"Crawl failed: {e}")
        finally:
            sys.stdout = real
            self.last_run = datetime.now().isoformat(timespec="seconds")
            self.running = False

    def _loop(self) -> None:
        import time
        while not self._stop.is_set():
            if not self.auto:
                self.next_run = None
            elif not self.running:
                if self.next_run is None:
                    self.next_run = time.time() + self.interval * 60
                elif time.time() >= self.next_run:
                    self.next_run = None
                    self.start()
            time.sleep(1)


def make_handler(cfg: dict, db: str, crawler: Crawler):
    html = (Path(__file__).parent / "ui.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the terminal quiet
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            elif self.path == "/api/jobs":
                store = Store(db)
                hidden, tracked = store.hidden_ids(), store.application_job_ids()
                jobs = [
                    {"id": r["id"], "company": r["company"], "title": r["title"], "url": r["url"],
                     "location": r["location"], "posted": r["posted"], "first_seen": r["first_seen"],
                     "hidden": r["id"] in hidden, "app": tracked.get(r["id"]),
                     "reqs": json.loads(r["reqs"]) if r["reqs"] else None}
                    for r in store.matched_jobs()
                ]
                self._json({"jobs": jobs})
            elif self.path == "/api/apps":
                self._json({"apps": Store(db).applications(), "stages": list(Store.STAGES)})
            elif self.path == "/api/apps.csv":
                buf = io.StringIO()
                w = csv.writer(buf)
                cols = ["company", "title", "status", "applied_at", "follow_up", "location", "url", "contact", "salary", "notes"]
                w.writerow(cols)
                for a in Store(db).applications():
                    w.writerow([a[c] or "" for c in cols])
                body = buf.getvalue().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="applications.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/crawl":
                self._json(self._crawl_state())
            else:
                self.send_error(404)

        def _crawl_state(self):
            import time
            return {"running": crawler.running, "auto": crawler.auto, "interval": crawler.interval,
                    "log": crawler.log[-200:], "last_run": crawler.last_run, "last_new": crawler.last_new,
                    "next_in": max(0, int(crawler.next_run - time.time())) if crawler.next_run else None}

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            store = Store(db)
            if self.path == "/api/hide":
                if not isinstance(data.get("id"), str):
                    return self._json({"error": "bad request"}, 400)
                store.set_hidden(data["id"], bool(data.get("hidden")))
                self._json({"ok": True})
            elif self.path == "/api/track":  # start/move tracking a crawled job
                if data.get("status") not in Store.STAGES or not isinstance(data.get("id"), str):
                    return self._json({"error": "bad request"}, 400)
                app_id = store.track_job(data["id"], data["status"])
                self._json({"ok": app_id is not None, "id": app_id})
            elif self.path == "/api/apps/add":
                self._json({"id": store.add_application(data)})
            elif self.path == "/api/apps/update":
                ok = isinstance(data.get("id"), int) and store.update_application(data["id"], data)
                self._json({"ok": ok}, 200 if ok else 400)
            elif self.path == "/api/apps/delete":
                if not isinstance(data.get("id"), int):
                    return self._json({"error": "bad request"}, 400)
                store.delete_application(data["id"])
                self._json({"ok": True})
            elif self.path == "/api/crawl":
                self._json({"started": crawler.start()})
            elif self.path == "/api/auto":
                crawler.auto = bool(data.get("auto"))
                if isinstance(data.get("interval"), (int, float)) and data["interval"] >= 1:
                    crawler.interval = float(data["interval"])
                crawler.next_run = None
                self._json(self._crawl_state())
            else:
                self.send_error(404)

    return Handler


def serve(cfg: dict, db: str, run_once, port: int = 8765, open_browser: bool = True) -> None:
    Store(db)  # make sure schema exists
    crawler = Crawler(cfg, db, run_once, float(cfg.get("poll_interval_minutes", 30)))
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg, db, crawler))
    url = f"http://127.0.0.1:{port}/"
    print(f"Posting Notifier UI running at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
