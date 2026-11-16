from __future__ import annotations

import platform
import subprocess

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
