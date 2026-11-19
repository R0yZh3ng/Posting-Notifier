"""Fetchers for job boards. Each returns a list of Job for one company config entry."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import Job

UA = "posting-notifier/0.1 (+https://github.com/)"
TIMEOUT = 20


def _iso(value) -> str | None:
    """Normalise an ISO string or epoch-milliseconds into ISO 8601 UTC."""
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, OverflowError):
        return None


def _workday_posted(text: str | None) -> str | None:
    """'Posted Today' / 'Posted Yesterday' / 'Posted 5 Days Ago' / 'Posted 30+ Days Ago' -> ISO date."""
    if not text:
        return None
    t = text.lower()
    now = datetime.now(timezone.utc)
    if "today" in t:
        days = 0
    elif "yesterday" in t:
        days = 1
    else:
        m = re.search(r"(\d+)\+?\s*day", t)
        if not m:
            return None
        days = int(m.group(1))
    return (now - timedelta(days=days)).isoformat(timespec="seconds")


def _get(url: str, **kw) -> requests.Response:
    for attempt in range(4):  # back off when a host rate-limits us
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json, text/html"}, timeout=TIMEOUT, **kw)
        if r.status_code != 429:
            break
        time.sleep(3 * 2 ** attempt)
    r.raise_for_status()
    return r


def greenhouse(c: dict) -> list[Job]:
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{c['slug']}/jobs?content=false").json()
    return [
        Job(c["name"], j["title"], j["absolute_url"], (j.get("location") or {}).get("name", ""),
            _iso(j.get("first_published") or j.get("updated_at")))
        for j in data.get("jobs", [])
    ]


def lever(c: dict) -> list[Job]:
    data = _get(f"https://api.lever.co/v0/postings/{c['slug']}?mode=json").json()
    return [
        Job(c["name"], j["text"], j["hostedUrl"], (j.get("categories") or {}).get("location", ""),
            _iso(j.get("createdAt")))
        for j in data
    ]


def ashby(c: dict) -> list[Job]:
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{c['slug']}").json()
    jobs = []
    for j in data.get("jobs", []):
        url = j.get("jobUrl") or f"https://jobs.ashbyhq.com/{c['slug']}/{j['id']}"
        jobs.append(Job(c["name"], j["title"], url, j.get("location", ""), _iso(j.get("publishedAt"))))
    return jobs


def workable(c: dict) -> list[Job]:
    url = f"https://apply.workable.com/api/v3/accounts/{c['slug']}/jobs"
    jobs, token = [], None
    while True:
        payload = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
        if token:
            payload["token"] = token
        r = requests.post(url, json=payload, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for j in data.get("results", []):
            loc = j.get("location") or {}
            loc_s = ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
            jobs.append(Job(c["name"], j["title"], f"https://apply.workable.com/{c['slug']}/j/{j['shortcode']}/", loc_s,
                            _iso(j.get("published"))))
        token = data.get("nextPage")
        if not token:
            break
    return jobs


def smartrecruiters(c: dict) -> list[Job]:
    jobs, offset = [], 0
    while True:
        data = _get(f"https://api.smartrecruiters.com/v1/companies/{c['slug']}/postings?limit=100&offset={offset}").json()
        content = data.get("content", [])
        for j in content:
            loc = j.get("location") or {}
            loc_s = ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
            url = f"https://jobs.smartrecruiters.com/{c['slug']}/{j['id']}"
            jobs.append(Job(c["name"], j["name"], url, loc_s, _iso(j.get("releasedDate"))))
        offset += len(content)
        if not content or offset >= data.get("totalFound", 0):
            break
    return jobs


def workday(c: dict) -> list[Job]:
    """Workday career sites. `url` is the public site root, e.g.
    https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"""
    m = re.match(r"https://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?([^/?#]+)", c["url"])
    if not m:
        raise ValueError(f"unrecognised workday url {c['url']!r}")
    tenant, wd, site = m.groups()
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    jobs, limit, seen = [], 20, set()
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"})
    sess.get(f"{base}/{site}", timeout=TIMEOUT)  # sets cookies some tenants require
    terms = c.get("search", "")
    for term in ([terms] if isinstance(terms, str) else terms):
        offset, total = 0, None
        while True:
            body = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": term}
            for attempt in range(5):  # Workday tenants share rate limits; back off on 429
                r = sess.post(api, json=body, timeout=TIMEOUT)
                if r.status_code != 429:
                    break
                time.sleep(5 * 2 ** attempt)
            r.raise_for_status()
            data = r.json()
            if total is None:  # Workday only reports `total` on the first page
                total = data.get("total", 0)
            for j in data.get("jobPostings", []):
                path = j.get("externalPath", "")
                if path in seen:
                    continue
                seen.add(path)
                jobs.append(Job(c["name"], j.get("title", ""), f"{base}/{site}{path}", j.get("locationsText", ""),
                                _workday_posted(j.get("postedOn"))))
            offset += limit
            if offset >= total or not data.get("jobPostings"):
                break
    return jobs


def _terms(c: dict) -> list[str]:
    t = c.get("search", "intern")
    return [t] if isinstance(t, str) else list(t)


def amazon(c: dict) -> list[Job]:
    """amazon.jobs search API. `search` is a term or list of terms (the board has ~10k postings)."""
    jobs, seen = [], set()
    for term in _terms(c):
        offset = 0
        while offset < 400:
            data = _get("https://www.amazon.jobs/en/search.json", params={
                "base_query": term, "result_limit": 100, "offset": offset, "sort": "recent"}).json()
            for j in data.get("jobs", []):
                url = "https://www.amazon.jobs" + j["job_path"]
                if url in seen:
                    continue
                seen.add(url)
                try:
                    posted = datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").replace(tzinfo=timezone.utc)
                    posted = posted.isoformat(timespec="seconds")
                except ValueError:
                    posted = None
                jobs.append(Job(c["name"], j["title"], url, j.get("normalized_location", ""), posted))
            offset += 100
            if offset >= data.get("hits", 0):
                break
    return jobs


def eightfold(c: dict) -> list[Job]:
    """Eightfold-hosted careers sites (Netflix, Microsoft, ...). `host` + `domain` required;
    `api: pcsx` selects the newer /api/pcsx/search shape, default is /api/apply/v2/jobs."""
    host, domain, pcsx = c["host"], c["domain"], c.get("api") == "pcsx"
    jobs, seen = [], set()
    for term in _terms(c):
        start = 0
        while start < 300:
            if pcsx:
                data = _get(f"https://{host}/api/pcsx/search", params={
                    "domain": domain, "query": term, "start": start, "sort_by": "timestamp"}).json().get("data", {})
                items = data.get("positions", [])
            else:
                data = _get(f"https://{host}/api/apply/v2/jobs", params={
                    "domain": domain, "query": term, "start": start, "num": 10}).json()
                items = data.get("positions", [])
            if not items:
                break
            for j in items:
                if pcsx:
                    url = f"https://{host}{j['positionUrl']}"
                    loc, ts = "; ".join(j.get("standardizedLocations") or j.get("locations") or []), j.get("postedTs")
                else:
                    url = j.get("canonicalPositionUrl") or f"https://{host}/careers/job/{j['id']}"
                    loc, ts = j.get("location", ""), j.get("t_create")
                if url in seen:
                    continue
                seen.add(url)
                posted = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds") if ts else None
                jobs.append(Job(c["name"], j.get("name", ""), url, loc, posted))
            start += len(items)
    return jobs


def html(c: dict) -> list[Job]:
    """Generic scraper: every <a> matching `selector` (default a[href]) whose href matches `pattern`."""
    page = _get(c["url"]).text
    soup = BeautifulSoup(page, "html.parser")
    pattern = re.compile(c["pattern"]) if c.get("pattern") else None
    seen, jobs = set(), []
    for a in soup.select(c.get("selector", "a[href]")):
        href = a.get("href")
        if not href:
            continue
        url = urljoin(c["url"], href)
        if pattern and not pattern.search(url):
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or url in seen:
            continue
        seen.add(url)
        jobs.append(Job(c["name"], title, url))
    return jobs


FETCHERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workable": workable,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
    "amazon": amazon,
    "eightfold": eightfold,
    "html": html,
}


def fetch(c: dict) -> list[Job]:
    try:
        fn = FETCHERS[c["type"]]
    except KeyError:
        raise ValueError(f"unknown source type {c['type']!r} for {c['name']}; expected one of {sorted(FETCHERS)}")
    return fn(c)
