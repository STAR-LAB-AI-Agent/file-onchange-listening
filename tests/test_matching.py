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
    ],
)
def test_glob_match_negative(rel: str, pattern: str) -> None:
    assert not glob_match(rel, pattern)


def test_path_is_ignored(tmp_path: Path) -> None:
    watched = tmp_path / "root"
    git = watched / ".git" / "objects"
    git.mkdir(parents=True)
    assert path_is_ignored(watched, git / "abc", ("**/.git/**",))
    keep = watched / "keep.txt"
    keep.write_text("x", encoding="utf-8")
    assert not path_is_ignored(watched, keep, ("**/.git/**",))
