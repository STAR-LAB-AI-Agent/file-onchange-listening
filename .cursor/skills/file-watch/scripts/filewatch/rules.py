from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

from filewatch.matching import any_glob_match
from filewatch.models import FileEvent, Rule
from filewatch.paths import relative_posix, to_posix


class RuleEngine:
    def __init__(self, root: Path, rules: tuple[Rule, ...]) -> None:
        self.root = root
        self.rules = rules
        self._last_hit: dict[tuple[str, str], float] = {}
        self._ignore_case = sys.platform == "win32"

    def matches(self, event: FileEvent) -> list[Rule]:
        rel = relative_posix(self.root, Path(event.path))
        if rel is None:
            rel = to_posix(event.path)
        hits: list[Rule] = []
        now = time.monotonic()
        for rule in self.rules:
            if not rule.enabled:
                continue
            if not self._match_one(rule, event, rel, now):
                continue
            hits.append(rule)
            self._last_hit[(rule.name, event.path)] = now
        return hits

    def _match_one(self, rule: Rule, event: FileEvent, rel: str, now: float) -> bool:
        when = rule.when
        if event.type not in when.types:
            return False
        if when.is_dir is not None and event.is_dir != when.is_dir:
            return False
        if when.glob and not any_glob_match(rel, when.glob, ignore_case=self._ignore_case):
            return False
        if when.regex:
            flags = re.IGNORECASE if self._ignore_case else 0
            if re.search(when.regex, rel, flags=flags) is None and re.search(when.regex, event.path, flags=flags) is None:
                return False
        if when.min_size_bytes is not None and not event.is_dir:
            try:
                size = os.path.getsize(event.path)
            except OSError:
                return False
            if size < when.min_size_bytes:
                return False
        if when.cooldown_seconds > 0:
            last = self._last_hit.get((rule.name, event.path), 0.0)
            if now - last < when.cooldown_seconds:
                return False
        return True
