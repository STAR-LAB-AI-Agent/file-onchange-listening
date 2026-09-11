# filewatch

版本 **1.1.0**。给通用 Agent 用的目录监听工具。CLI 放在 skill 的 `scripts/` 里，复制整个 `.cursor/skills/file-watch/` 即可打包安装。

变更记录见 [CHANGELOG.md](CHANGELOG.md)。

```text
.cursor/skills/file-watch/
  SKILL.md
  pack.cmd / pack.sh      # 一键打包（先构建前端）
  requirements.txt
  examples/watch.yaml
  web/                    # shadcn + Vite 前端源码
  scripts/
    filewatch_cli.py      # CLI 入口
    pack_skill.py         # 打包未构建 skill
    filewatch/            # 实现
      webui/              # serve 构建产物
    test_watch_dir.py     # 实测脚本
    echo_agent.py         # 示例智能体命令
```

## 安装

只需安装 Python 依赖（不必 `pip install` 本仓库）：

```bash
pip install -r .cursor/skills/file-watch/requirements.txt
```

把该 skill 目录拷到 `~/.cursor/skills/file-watch/` 后，个人环境也可直接用。仓库里的 `web/` 是未构建源码；分发前在 skill 目录双击 `pack.cmd`（或 `python scripts/pack_skill.py`），会先 `npm run build` 再打出 `dist/file-watch-<版本>.zip`。解压到 `.cursor/skills/` 即可安装。

## 快速开始

在 skill 根目录下：

```bash
python scripts/filewatch_cli.py init --output watch.yaml
python scripts/filewatch_cli.py validate --config watch.yaml
python scripts/filewatch_cli.py start --config watch.yaml
python scripts/filewatch_cli.py reload --config watch.yaml
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

用户用自然语言描述规则时，由 Agent 改 YAML，先 `validate` 再对运行中的实例 `reload`（不必停掉守护进程）。`watch.path` / `recursive` 变更仍需重启。网页「监听规则」里的口语生成走 LLM，需先在设置页填写兼容 OpenAI 的 API Key。

## 网页

```bash
python .cursor/skills/file-watch/scripts/filewatch_cli.py serve --port 8765
```

浏览器打开输出 JSON 中的 `url`（默认 http://127.0.0.1:8765/ ）。首页按监听目录列出任务；详情里可以看文件变化，也可以在「监听规则」里手动添加或用自然语言生成规则。口语会调用 LLM，请先打开「设置」填写 API Key（也可设环境变量 `FILEWATCH_LLM_API_KEY` / `FILEWATCH_LLM_BASE_URL` / `FILEWATCH_LLM_MODEL`）。Key 保存在状态目录的 `settings.json`，接口不会回明文。粘贴 YAML/JSON 规则不经过模型。同一路径会复用已有任务；两个目录同名时，后者的 id 会带短哈希后缀。页面使用 [shadcn/ui](https://ui.shadcn.com/) 组件。

改前端后在 `web/` 下构建，产物写入 `scripts/filewatch/webui/`：

```bash
cd .cursor/skills/file-watch/web
npm install
npm run build
```

## 实测脚本

```bash
python .cursor/skills/file-watch/scripts/test_watch_dir.py --path D:/data/inbox --pretty
```

## 测试

```bash
pip install -e ".[dev]"
pytest
```
