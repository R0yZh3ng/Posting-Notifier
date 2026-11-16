from __future__ import annotations

import re

from .models import Job


def _compile(pattern: str) -> re.Pattern:
    """Case-insensitive, whole-word match: "intern" matches "Intern, SWE" but not "Internal Comms"."""
    return re.compile(rf"(?<!\w)(?:{pattern})(?!\w)", re.I)


class Matcher:
    def __init__(self, criteria: dict):
        self.include = [_compile(p) for p in criteria.get("include", [])]
        self.exclude = [_compile(p) for p in criteria.get("exclude", [])]
        self.locations = [_compile(p) for p in criteria.get("locations") or []]

    def matches(self, job: Job) -> bool:
        title = job.title
        if self.include and not any(p.search(title) for p in self.include):
            return False
        if any(p.search(title) for p in self.exclude):
            return False
        if self.locations:
            haystack = f"{title} {job.location}"
            if not any(p.search(haystack) for p in self.locations):
                return False
        return True
