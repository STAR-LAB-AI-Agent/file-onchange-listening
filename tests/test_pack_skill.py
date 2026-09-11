from __future__ import annotations

import zipfile
from pathlib import Path

import pack_skill


def _fake_skill(tmp_path: Path) -> Path:
    root = tmp_path / "file-watch"
    (root / "scripts" / "filewatch" / "webui" / "assets").mkdir(parents=True)
    (root / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    (root / "requirements.txt").write_text("watchdog\n", encoding="utf-8")
    (root / "scripts" / "filewatch" / "webui" / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    (root / "scripts" / "filewatch" / "webui" / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (root / "web" / "src").mkdir(parents=True)
    (root / "web" / "package.json").write_text("{}", encoding="utf-8")
    (root / "web" / "src" / "App.tsx").write_text("export default function App(){return null}", encoding="utf-8")
    (root / "web" / "node_modules" / "pkg").mkdir(parents=True)
    (root / "web" / "node_modules" / "pkg" / "index.js").write_text("unused", encoding="utf-8")
    (root / "scripts" / "__pycache__").mkdir()
    (root / "scripts" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    (root / "dist").mkdir()
    (root / "dist" / "old.zip").write_bytes(b"PK")
    return root


def test_iter_skill_files_skips_junk(tmp_path: Path) -> None:
    root = _fake_skill(tmp_path)
    files = [path.relative_to(root).as_posix() for path in pack_skill.iter_skill_files(root)]
    assert "SKILL.md" in files
    assert "scripts/filewatch/webui/index.html" in files
    assert "web/src/App.tsx" in files
    assert "web/package.json" in files
    assert not any(name.startswith("web/node_modules/") for name in files)
    assert not any("__pycache__" in name for name in files)
    assert "dist/old.zip" not in files


def test_iter_skill_files_can_drop_web_src(tmp_path: Path) -> None:
    root = _fake_skill(tmp_path)
    files = [path.relative_to(root).as_posix() for path in pack_skill.iter_skill_files(root, include_web_src=False)]
    assert "scripts/filewatch/webui/index.html" in files
    assert not any(name.startswith("web/") for name in files)


def test_pack_skip_build_writes_zip(tmp_path: Path, monkeypatch) -> None:
    root = _fake_skill(tmp_path)
    monkeypatch.setattr(pack_skill, "_version", lambda: "1.0.0")
    dest = tmp_path / "out" / "skill.zip"
    payload = pack_skill.pack(root=root, output=dest, skip_build=True)
    assert payload["ok"] is True
    assert dest.is_file()
    with zipfile.ZipFile(dest) as archive:
        names = archive.namelist()
    assert "file-watch/SKILL.md" in names
    assert "file-watch/scripts/filewatch/webui/index.html" in names
    assert "file-watch/web/src/App.tsx" in names
    assert not any("node_modules" in name for name in names)


def test_pack_skip_build_requires_webui(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "file-watch"
    root.mkdir()
    (root / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    monkeypatch.setattr(pack_skill, "_version", lambda: "1.0.0")
    try:
        pack_skill.pack(root=root, output=tmp_path / "x.zip", skip_build=True)
    except pack_skill.PackError as exc:
        assert exc.error == "not_built"
    else:
        raise AssertionError("expected PackError")


def test_pack_real_skill_skip_build(tmp_path: Path) -> None:
    dest = tmp_path / "file-watch.zip"
    payload = pack_skill.pack(skip_build=True, output=dest, include_web_src=True)
    assert payload["ok"] is True
    with zipfile.ZipFile(dest) as archive:
        names = set(archive.namelist())
    assert "file-watch/SKILL.md" in names
    assert "file-watch/pack.cmd" in names
    assert "file-watch/scripts/pack_skill.py" in names
    assert "file-watch/scripts/filewatch/webui/index.html" in names
    assert not any("node_modules" in name for name in names)
    assert any(name.startswith("file-watch/web/src/") for name in names)
