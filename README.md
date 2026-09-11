# filewatch

版本 **1.1.4**。给通用 Agent 用的目录监听工具。CLI 放在 skill 的 `scripts/` 里，复制整个 `.cursor/skills/file-watch/` 即可打包安装。

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

## Skill 推荐工作流

也可以在 Web 端完成同样的事：让 Agent 打开本机面板后，自己在首页加目录、在任务详情里改规则。更省事的做法是直接对 Agent 说话，由它调用本 skill。下面是建议发给 Agent 的提示词，以及对应效果。

### 1. 启动监控进程和 Web 端

可以这样说：

- 「用 file-watch 把监听跑起来，并打开事件网页。」
- 「先打开 filewatch 面板，目录我待会再定。」
- 「监听已经在跑的话不要重复启动，把网页地址给我。」

效果：后台开始听文件变化（已有任务会复用）；本机网页打开或给出地址，可在浏览器里看任务和事件。只要面板时，可以先不起具体目录。关掉网页不会停掉已经在听的目录。

### 2. 设置要监控的目录

可以这样说：

- 「开始监听 `D:/data/inbox`，含子目录。」
- 「看一下现在在听哪些文件夹，有 `D:/data/inbox` 就复用，没有再加。」
- 「把监听目录改成 `D:/work/docs`，不要再听原来的 inbox。」

效果：该路径成为一条监听任务；同一路径不会开两个进程。只换规则不必重启；你明确要求换目录或是否递归时，会先停再启后再生效。

### 3. 新增监控规则

把「哪些文件、什么变化、然后做什么」说清楚即可，例如：

- 「inbox 里新建或改了 markdown，通知我文件名和路径。」
- 「`D:/data/inbox` 下出现新的 `*.pdf` 时告诉我，先不要启动别的智能体。」
- 「docs 里 markdown 有改动就启动智能体做摘要，半分钟内同一文件只触发一次。」
- 「再加一条：删除 `.tmp` 以外的文件也通知我；原来的 markdown 规则留着。」

效果：口语被写成规则并校验；监听已在跑则热更新，没跑则启动。Agent 会回报已生效的规则名。没提智能体时默认只发通知。没说要换目录时，原来的监听路径和是否递归保持不变。之后文件对上规则，就会进任务邮箱（或按你的要求拉起智能体）。

调用细节见 [`.cursor/skills/file-watch/SKILL.md`](.cursor/skills/file-watch/SKILL.md)。

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
