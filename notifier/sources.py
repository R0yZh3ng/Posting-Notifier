"""Fetchers for job boards. Each returns a list of Job for one company config entry."""
from __future__ import annotations

import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import Job

UA = "posting-notifier/0.1 (+https://github.com/)"
TIMEOUT = 20


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json, text/html"}, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def greenhouse(c: dict) -> list[Job]:
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{c['slug']}/jobs?content=false").json()
    return [
        Job(c["name"], j["title"], j["absolute_url"], (j.get("location") or {}).get("name", ""))
        for j in data.get("jobs", [])
    ]


def lever(c: dict) -> list[Job]:
    data = _get(f"https://api.lever.co/v0/postings/{c['slug']}?mode=json").json()
    return [
        Job(c["name"], j["text"], j["hostedUrl"], (j.get("categories") or {}).get("location", ""))
        for j in data
    ]


def ashby(c: dict) -> list[Job]:
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{c['slug']}").json()
    jobs = []
    for j in data.get("jobs", []):
        url = j.get("jobUrl") or f"https://jobs.ashbyhq.com/{c['slug']}/{j['id']}"
        jobs.append(Job(c["name"], j["title"], url, j.get("location", "")))
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
            jobs.append(Job(c["name"], j["title"], f"https://apply.workable.com/{c['slug']}/j/{j['shortcode']}/", loc_s))
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
            jobs.append(Job(c["name"], j["name"], url, loc_s))
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
    jobs, offset, limit = [], 0, 20
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"})
    sess.get(f"{base}/{site}", timeout=TIMEOUT)  # sets cookies some tenants require
    while True:
        body = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": c.get("search", "")}
        for attempt in range(4):  # Workday tenants share rate limits; back off on 429
            r = sess.post(api, json=body, timeout=TIMEOUT)
            if r.status_code != 429:
                break
            time.sleep(5 * 2 ** attempt)
        r.raise_for_status()
        data = r.json()
        for j in data.get("jobPostings", []):
            path = j.get("externalPath", "")
            jobs.append(Job(c["name"], j.get("title", ""), f"{base}/{site}{path}", j.get("locationsText", "")))
        offset += limit
        if offset >= data.get("total", 0) or not data.get("jobPostings"):
            break
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
    "html": html,
}


def fetch(c: dict) -> list[Job]:
    try:
        fn = FETCHERS[c["type"]]
    except KeyError:
        raise ValueError(f"unknown source type {c['type']!r} for {c['name']}; expected one of {sorted(FETCHERS)}")
    return fn(c)
