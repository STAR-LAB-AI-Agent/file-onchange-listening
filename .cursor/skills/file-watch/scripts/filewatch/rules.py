from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime
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

    def replace_rules(self, rules: tuple[Rule, ...]) -> None:
        names = {rule.name for rule in rules}
        self.rules = rules
        self._last_hit = {key: ts for key, ts in self._last_hit.items() if key[0] in names}

    def exclude_hits(self, event: FileEvent, *, now: datetime | None = None) -> list[Rule]:
        rel = self._rel(event)
        wall = now if now is not None else datetime.now().astimezone()
        hits: list[Rule] = []
        for rule in self.rules:
            if not rule.enabled or not rule.exclude:
                continue
            if self._match_one(rule, event, rel, mono=0.0, wall=wall, apply_cooldown=False):
                hits.append(rule)
        return hits

    def selector_hits(self, event: FileEvent) -> list[Rule]:
        """Positive rules whose path/type/is_dir selector matches (ignore cooldown/active/size)."""
        rel = self._rel(event)
        hits: list[Rule] = []
        for rule in self.rules:
            if not rule.enabled or rule.exclude:
                continue
            if self._match_selector(rule, event, rel):
                hits.append(rule)
        return hits

    def matches(self, event: FileEvent, *, now: datetime | None = None) -> list[Rule]:
        if self.exclude_hits(event, now=now):
            return []
        rel = self._rel(event)
        hits: list[Rule] = []
        mono = time.monotonic()
        wall = now if now is not None else datetime.now().astimezone()
        for rule in self.rules:
            if not rule.enabled or rule.exclude:
                continue
            if not self._match_one(rule, event, rel, mono, wall):
                continue
            hits.append(rule)
            self._last_hit[(rule.name, event.path)] = mono
        return hits

    def _rel(self, event: FileEvent) -> str:
        rel = relative_posix(self.root, Path(event.path))
        if rel is None:
            return to_posix(event.path)
        return rel

    def _match_selector(self, rule: Rule, event: FileEvent, rel: str) -> bool:
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
        return True

    def _match_one(
        self,
        rule: Rule,
        event: FileEvent,
        rel: str,
        mono: float,
        wall: datetime,
        *,
        apply_cooldown: bool = True,
    ) -> bool:
        if not self._match_selector(rule, event, rel):
            return False
        when = rule.when
        if when.min_size_bytes is not None and not event.is_dir:
            try:
                size = os.path.getsize(event.path)
            except OSError:
                return False
            if size < when.min_size_bytes:
                return False
        if when.active is not None and not when.active.contains(wall):
            return False
        if apply_cooldown and when.cooldown_seconds > 0:
            last = self._last_hit.get((rule.name, event.path), 0.0)
            if mono - last < when.cooldown_seconds:
                return False
        return True
