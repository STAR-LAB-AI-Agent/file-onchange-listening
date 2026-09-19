from __future__ import annotations

import zipfile
from pathlib import Path

import pack_nanobot
import pack_skill


def _fake_skill(tmp_path: Path) -> Path:
    root = tmp_path / "file-watch"
    (root / "scripts" / "filewatch" / "webui" / "assets").mkdir(parents=True)
    (root / "examples").mkdir()
    (root / "SKILL.md").write_text(
        "---\n"
        "name: file-watch\n"
        "description: >-\n"
        "  监听文件夹变化并按规则通知或启动任务。用户提到监听目录、改规则时使用。\n"
        "---\n\n"
        "# 文件监听\n\n"
        "先定位 skill 根目录。依赖：\n\n"
        "```bash\n"
        "pip install -r requirements.txt\n"
        "```\n\n"
        "下文用 `python scripts/filewatch_cli.py` 表示相对本 skill 根目录。从本仓库调用时等价于：\n\n"
        "```bash\n"
        "python .cursor/skills/file-watch/scripts/filewatch_cli.py\n"
        "```\n\n"
        "示例见 `examples/watch.yaml`。\n\n"
        "## 打包\n\n"
        "python scripts/pack_skill.py\n",
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text("watchdog\n", encoding="utf-8")
    (root / "examples" / "watch.yaml").write_text("watch: {}\n", encoding="utf-8")
    (root / "pack.cmd").write_text("echo pack\n", encoding="utf-8")
    (root / "scripts" / "filewatch_cli.py").write_text("print('cli')\n", encoding="utf-8")
    (root / "scripts" / "pack_skill.py").write_text("# pack\n", encoding="utf-8")
    (root / "scripts" / "pack_nanobot.py").write_text("# nanobot pack\n", encoding="utf-8")
    (root / "scripts" / "filewatch" / "webui" / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    (root / "scripts" / "filewatch" / "webui" / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (root / "web" / "src").mkdir(parents=True)
    (root / "web" / "package.json").write_text("{}", encoding="utf-8")
    (root / "web" / "src" / "App.tsx").write_text("export default function App(){return null}", encoding="utf-8")
    return root


def test_rewrite_skill_md_moves_paths() -> None:
    src = (
        "---\nname: file-watch\ndescription: Watch folders when the user asks.\n---\n\n"
        "pip install -r requirements.txt\n"
        "python .cursor/skills/file-watch/scripts/filewatch_cli.py\n"
        "examples/watch.yaml\n\n"
        "## 打包\n\nCursor zip.\n"
    )
    out = pack_nanobot.rewrite_skill_md(src)
    assert "pip install -r scripts/requirements.txt" in out
    assert ".cursor/skills" not in out
    assert "references/examples/watch.yaml" in out
    assert "metadata:" in out
    assert "nanobot:" in out
    assert "安装（nanobot）" in out
    assert "## 打包" not in out


def test_stage_layout_is_nanobot_valid(tmp_path: Path) -> None:
    root = _fake_skill(tmp_path)
    staging = tmp_path / "stage"
    pack_nanobot.stage_nanobot_skill(root, staging)
    skill_dir = staging / "file-watch"
    names = {path.name for path in skill_dir.iterdir()}
    assert names == {"SKILL.md", "scripts", "references"}
    assert (skill_dir / "scripts" / "requirements.txt").is_file()
    assert (skill_dir / "references" / "examples" / "watch.yaml").is_file()
    assert not (skill_dir / "scripts" / "pack_skill.py").exists()
    assert not (skill_dir / "scripts" / "pack_nanobot.py").exists()
    assert not (skill_dir / "pack.cmd").exists()
    assert not (skill_dir / "web").exists()
    valid, message = pack_nanobot.validate_nanobot_skill(skill_dir)
    assert valid, message


def test_pack_skip_build_writes_skill(tmp_path: Path, monkeypatch) -> None:
    root = _fake_skill(tmp_path)
    monkeypatch.setattr(pack_skill, "_version", lambda: "1.0.0")
    dest = tmp_path / "out" / "file-watch.skill"
    payload = pack_nanobot.pack(root=root, output=dest, skip_build=True)
    assert payload["ok"] is True
    assert dest.is_file()
    with zipfile.ZipFile(dest) as archive:
        names = archive.namelist()
    assert "file-watch/SKILL.md" in names
    assert "file-watch/scripts/filewatch_cli.py" in names
    assert "file-watch/scripts/requirements.txt" in names
    assert "file-watch/references/examples/watch.yaml" in names
    assert "file-watch/scripts/filewatch/webui/index.html" in names
    assert not any(name.startswith("file-watch/web/") for name in names)
    assert not any(name.endswith("pack.cmd") for name in names)
    roots = {name.split("/", 1)[1].split("/", 1)[0] for name in names if name.startswith("file-watch/")}
    assert roots <= {"SKILL.md", "scripts", "references", "assets"}


def test_pack_real_skill_skip_build(tmp_path: Path) -> None:
    dest = tmp_path / "file-watch.skill"
    payload = pack_nanobot.pack(skip_build=True, output=dest)
    assert payload["ok"] is True
    with zipfile.ZipFile(dest) as archive:
        names = set(archive.namelist())
        skill_md = archive.read("file-watch/SKILL.md").decode("utf-8")
    assert "file-watch/SKILL.md" in names
    assert "file-watch/scripts/filewatch_cli.py" in names
    assert "file-watch/scripts/requirements.txt" in names
    assert "file-watch/references/examples/watch.yaml" in names
    assert "file-watch/scripts/filewatch/webui/index.html" in names
    assert "file-watch/pack.cmd" not in names
    assert "file-watch/scripts/pack_nanobot.py" not in names
    assert not any(name.startswith("file-watch/web/") for name in names)
    assert "pip install -r scripts/requirements.txt" in skill_md
    assert ".cursor/skills/file-watch" not in skill_md
    assert "references/examples/watch.yaml" in skill_md
