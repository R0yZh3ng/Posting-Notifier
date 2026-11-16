from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    company: str
    title: str
    url: str
    location: str = ""

    @property
    def id(self) -> str:
        """Stable identifier: company + URL (URLs are the most reliable key across boards)."""
        return hashlib.sha1(f"{self.company}|{self.url}".encode()).hexdigest()
