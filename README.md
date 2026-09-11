# filewatch

版本 **1.0.0**。给通用 Agent 用的目录监听工具。CLI 放在 skill 的 `scripts/` 里，复制整个 `.cursor/skills/file-watch/` 即可打包安装。

变更记录见 [CHANGELOG.md](CHANGELOG.md)。

```text
.cursor/skills/file-watch/
  SKILL.md
  requirements.txt
  examples/watch.yaml
  scripts/
    filewatch_cli.py      # CLI 入口
    filewatch/            # 实现
    test_watch_dir.py     # 实测脚本
    echo_agent.py         # 示例智能体命令
```

## 安装

只需安装 Python 依赖（不必 `pip install` 本仓库）：

```bash
pip install -r .cursor/skills/file-watch/requirements.txt
```

把该 skill 目录拷到 `~/.cursor/skills/file-watch/` 后，个人环境也可直接用。

## 快速开始

在 skill 根目录下：

```bash
python scripts/filewatch_cli.py init --output watch.yaml
python scripts/filewatch_cli.py start --config watch.yaml
python scripts/filewatch_cli.py wait --stream jobs --timeout 30
python scripts/filewatch_cli.py stop
```

从本仓库根目录调用：

```bash
python .cursor/skills/file-watch/scripts/filewatch_cli.py start --config .cursor/skills/file-watch/examples/watch.yaml
```

所有命令在 stdout 输出 JSON。状态目录默认是 `%LOCALAPPDATA%/filewatch`（可用 `FILEWATCH_HOME` 或 `--home` 覆盖），不要放进被监听的文件夹。

调用协议见 [`.cursor/skills/file-watch/SKILL.md`](.cursor/skills/file-watch/SKILL.md)。

## 规则示例

见 `examples/watch.yaml`。`notify` 写入 `jobs` 邮箱，也可选 webhook。`agent.runner` 可以是 `command` 或 `cursor_sdk`。

## 实测脚本

```bash
python .cursor/skills/file-watch/scripts/test_watch_dir.py --path D:/data/inbox --pretty
```

## 测试

```bash
pip install -e ".[dev]"
pytest
```
