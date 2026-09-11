from __future__ import annotations

import re
from pathlib import Path

from filewatch.paths import relative_posix, to_posix

# Keep a posix glob translator instead of watchdog.utils.patterns.match_any_paths.
# That helper is built for full native paths: on Windows, `**/*.md` misses files in
# the watch root, and `*.md` matches nested files via PureWindowsPath. Relative
# posix globs with empty globstar (**/ == optional prefix) match YAML rules
# like `**/*.md` and `**/*` the way users write them.

_GLOB_CACHE: dict[tuple[str, bool], re.Pattern[str]] = {}


def glob_to_regex(pattern: str, ignore_case: bool = False) -> re.Pattern[str]:
    key = (pattern, ignore_case)
    cached = _GLOB_CACHE.get(key)
    if cached:
        return cached
    i = 0
    out: list[str] = ["^"]
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        ch = pattern[i]
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    out.append("$")
    flags = re.IGNORECASE if ignore_case else 0
    compiled = re.compile("".join(out), flags)
    _GLOB_CACHE[key] = compiled
    return compiled


def glob_match(rel_posix: str, pattern: str, ignore_case: bool = False) -> bool:
    rel = to_posix(rel_posix)
    if rel.startswith("./"):
        rel = rel[2:]
    pat = to_posix(pattern)
    regex = glob_to_regex(pat, ignore_case=ignore_case)
    if regex.fullmatch(rel):
        return True
    name = rel.rsplit("/", 1)[-1]
    return regex.fullmatch(name) is not None


def any_glob_match(rel_posix: str, patterns: tuple[str, ...] | list[str], ignore_case: bool = False) -> bool:
    return any(glob_match(rel_posix, pattern, ignore_case=ignore_case) for pattern in patterns)


def path_is_ignored(root: Path, path: Path, ignore: tuple[str, ...], ignore_case: bool = False) -> bool:
    rel = relative_posix(root, path)
    if rel is None:
        return True
    if any_glob_match(rel, ignore, ignore_case=ignore_case):
        return True
    parts = Path(rel).parts
    return any(part in {".git", "__pycache__", ".venv", "venv"} for part in parts)
