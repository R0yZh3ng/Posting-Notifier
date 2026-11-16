from __future__ import annotations

import html
from datetime import datetime, timezone
from itertools import groupby


def write_markdown(path: str, rows) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# Matching jobs ({len(rows)})", "", f"_Updated {now}. Newest first._", ""]
    for r in rows:
        loc = f" · {r['location']}" if r["location"] else ""
        lines.append(f"- {r['first_seen'][:10]} **{r['company']}** — [{r['title']}]({r['url']}){loc}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_html(path: str, rows) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    e = html.escape
    parts = [
        "<!doctype html><meta charset=utf-8><title>Matching jobs</title>",
        "<style>body{font:15px/1.5 system-ui;max-width:900px;margin:2rem auto;padding:0 1rem}"
        "h2{margin-top:2rem}li{margin:.3rem 0}.m{color:#777;font-size:.85em}</style>",
        f"<h1>Matching jobs ({len(rows)})</h1><p class=m>Updated {now}</p>",
    ]
    by_company = sorted(rows, key=lambda r: r["company"].lower())
    for company, group in groupby(by_company, key=lambda r: r["company"]):
        parts.append(f"<h2>{e(company)}</h2><ul>")
        for r in group:
            loc = f" <span class=m>{e(r['location'])}</span>" if r["location"] else ""
            parts.append(
                f"<li><a href=\"{e(r['url'])}\">{e(r['title'])}</a>{loc}"
                f" <span class=m>· seen {e(r['first_seen'][:10])}</span></li>"
            )
        parts.append("</ul>")
    with open(path, "w") as f:
        f.write("\n".join(parts) + "\n")


def write_all(output_cfg: dict, rows) -> None:
    if output_cfg.get("markdown"):
        write_markdown(output_cfg["markdown"], rows)
    if output_cfg.get("html"):
        write_html(output_cfg["html"], rows)
