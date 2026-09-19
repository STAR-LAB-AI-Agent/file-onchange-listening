from __future__ import annotations

import pytest

from filewatch.matching import glob_match, path_is_ignored
from pathlib import Path


@pytest.mark.parametrize(
    "rel,pattern",
    [
        ("readme.md", "**/*.md"),
        ("docs/a.md", "**/*.md"),
        ("file.txt", "**/*"),
        ("a/b/c.txt", "**/*"),
        (".git/HEAD", "**/.git/**"),
        ("pkg/.git/config", "**/.git/**"),
        ("foo.tmp", "**/*.tmp"),
        ("a.md", "*.md"),
    ],
)
def test_glob_match_positive(rel: str, pattern: str) -> None:
    assert glob_match(rel, pattern)


@pytest.mark.parametrize(
    "rel,pattern",
    [
        ("readme.md", "**/*.py"),
        ("dir/file.txt", "*.md"),
        ("docs/sub/a.md", "docs/*"),
        ("ab.txt", "a?.md"),
        ("a.txt", "a?.txt"),
        ("abc.txt", "a?.txt"),
    ],
)
def test_glob_match_negative(rel: str, pattern: str) -> None:
    assert not glob_match(rel, pattern)


@pytest.mark.parametrize(
    "rel,pattern",
    [
        ("docs/a.md", "docs/*"),
        ("ab.txt", "a?.txt"),
        ("dir/file.md", "*.md"),
        ("nested/foo.tmp", "**/*.tmp"),
    ],
)
def test_glob_match_extra_positive(rel: str, pattern: str) -> None:
    assert glob_match(rel, pattern)


def test_glob_match_ignore_case() -> None:
    assert glob_match("ReadMe.MD", "**/*.md", ignore_case=True)
    assert not glob_match("ReadMe.MD", "**/*.md", ignore_case=False)


def test_path_is_ignored(tmp_path: Path) -> None:
    watched = tmp_path / "root"
    git = watched / ".git" / "objects"
    git.mkdir(parents=True)
    assert path_is_ignored(watched, git / "abc", ("**/.git/**",))
    keep = watched / "keep.txt"
    keep.write_text("x", encoding="utf-8")
    assert not path_is_ignored(watched, keep, ("**/.git/**",))
    cache = watched / "pkg" / "__pycache__" / "x.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_text("", encoding="utf-8")
    assert path_is_ignored(watched, cache, ())
    tmp = watched / "nested" / "x.tmp"
    tmp.parent.mkdir()
    tmp.write_text("x", encoding="utf-8")
    assert path_is_ignored(watched, tmp, ("**/*.tmp",))
    outside = tmp_path / "other" / "a.txt"
    outside.parent.mkdir()
    outside.write_text("x", encoding="utf-8")
    assert path_is_ignored(watched, outside, ())
