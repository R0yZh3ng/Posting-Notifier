from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    company: str
    title: str
    url: str
    location: str = ""
    posted_at: str | None = None  # ISO 8601 UTC when the board reports it, else None

    @property
    def id(self) -> str:
        """Stable identifier: company + URL (URLs are the most reliable key across boards)."""
        return hashlib.sha1(f"{self.company}|{self.url}".encode()).hexdigest()
