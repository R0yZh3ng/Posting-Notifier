from __future__ import annotations

import html
import os
import platform
import smtplib
import subprocess
from email.message import EmailMessage

import requests

from .models import Job


def desktop(job: Job) -> None:
    if platform.system() != "Darwin":
        return
    title = f"New job at {job.company}"
    body = job.title + (f" — {job.location}" if job.location else "")
    script = f'display notification {_q(body)} with title {_q(title)} subtitle {_q(job.url)}'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def webhook(url: str, job: Job) -> None:
    text = f"*{job.company}* — {job.title}" + (f" ({job.location})" if job.location else "") + f"\n{job.url}"
    # "text" is read by Slack, "content" by Discord; sending both is harmless.
    requests.post(url, json={"text": text, "content": text}, timeout=15)


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def send(cfg: dict, job: Job) -> None:
    if cfg.get("desktop"):
        desktop(job)
    if cfg.get("webhook"):
        try:
            webhook(cfg["webhook"], job)
        except requests.RequestException as e:
            print(f"  ! webhook failed: {e}")


def _email_cfg(cfg: dict) -> dict | None:
    e = cfg.get("email") or {}
    if not e.get("enabled"):
        return None
    e = dict(e)
    e["password"] = os.environ.get("POSTING_NOTIFIER_SMTP_PASSWORD") or e.get("password") or ""
    missing = [k for k in ("smtp_host", "username", "password", "to") if not e.get(k)]
    if missing:
        print(f"  ! email enabled but missing: {', '.join(missing)}")
        return None
    return e


def build_digest(jobs: list[Job]) -> tuple[str, str, str]:
    """(subject, plain text, html) for a list of new jobs."""
    n = len(jobs)
    subject = f"{n} new job posting{'s' if n != 1 else ''}: " + ", ".join(sorted({j.company for j in jobs})[:3]) + (
        "…" if len({j.company for j in jobs}) > 3 else "")
    text = "\n\n".join(
        f"{j.company} — {j.title}" + (f" ({j.location})" if j.location else "") + f"\n{j.url}" for j in jobs)
    rows = "".join(
        f'<li style="margin:0 0 10px"><b>{html.escape(j.company)}</b> — '
        f'<a href="{html.escape(j.url)}">{html.escape(j.title)}</a>'
        + (f' <span style="color:#777">· {html.escape(j.location)}</span>' if j.location else "") + "</li>"
        for j in jobs)
    return subject, text, f'<ul style="padding-left:18px;font:15px system-ui,sans-serif">{rows}</ul>'


def email_digest(cfg: dict, jobs: list[Job]) -> None:
    """Send one email listing every new job. Never raises; failures are printed."""
    e = _email_cfg(cfg)
    if not e or not jobs:
        return
    subject, text, body_html = build_digest(jobs)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = e.get("from") or e["username"]
    msg["To"] = e["to"]
    msg.set_content(text)
    msg.add_alternative(body_html, subtype="html")
    port = int(e.get("smtp_port", 587))
    try:
        if port == 465:
            with smtplib.SMTP_SSL(e["smtp_host"], port, timeout=30) as s:
                s.login(e["username"], e["password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(e["smtp_host"], port, timeout=30) as s:
                s.starttls()
                s.login(e["username"], e["password"])
                s.send_message(msg)
        print(f"  emailed {len(jobs)} new job(s) to {e['to']}")
    except (smtplib.SMTPException, OSError) as ex:
        print(f"  ! email failed: {ex}")


def ntfy_digest(cfg: dict, jobs: list[Job]) -> None:
    """Push one summary to https://ntfy.sh/<topic> (no account; the topic name acts as the password).
    Install the ntfy app on your phone and subscribe to the same topic."""
    n = cfg.get("ntfy") or {}
    topic = (n.get("topic") or "").strip()
    if not topic or not jobs:
        return
    server = (n.get("server") or "https://ntfy.sh").rstrip("/")
    lines = [f"{j.company}: {j.title}" + (f" ({j.location})" if j.location else "") for j in jobs[:15]]
    if len(jobs) > 15:
        lines.append(f"…and {len(jobs) - 15} more")
    try:
        requests.post(f"{server}/{topic}", data="\n".join(lines).encode(), timeout=15, headers={
            "Title": f"{len(jobs)} new job posting{'s' if len(jobs) != 1 else ''}",
            "Click": jobs[0].url, "Tags": "briefcase"}).raise_for_status()
    except requests.RequestException as e:
        print(f"  ! ntfy failed: {e}")
