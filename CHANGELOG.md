# 更新日志

本文件记录面向用户的变更。初始版本 **1.0.0**；小修改每次 +0.0.1；其余情况由用户指定版本。每个版本按 **新增**、**修改**、**修复** 分段。

## 1.1.4 - 2026-09-11

### 修改

- skill：改已有任务规则时先读状态目录 `config.json`；重启已停止任务须 `start --config` 原配置，禁止对已有路径 `start --path`；`serve` 须后台启动。

## 1.1.3 - 2026-09-11

### 修改

- README 推荐工作流改为示例提示词及其效果（启动与网页、设置目录、新增规则）。

## 1.1.2 - 2026-09-11

### 修改

- README 推荐工作流改为开头点明可用 Web，后续步骤全部用 Agent 调用 skill 的自然语言描述。

## 1.1.1 - 2026-09-11

### 修改

- README 补充 Skill 推荐工作流：启动守护进程与 Web、在网页或通用 Agent 中设置监听目录与新增规则。

## 1.1.0 - 2026-09-11

### 新增

- `reload`：热更新规则、忽略列表和去抖间隔，不必重启守护进程。
- `serve` 本地网页面板（默认 `127.0.0.1`）：按目录列出任务，详情可看事件并编辑规则。
- 网页支持手动规则与自然语言生成（兼容 OpenAI 的 LLM）；API Key 只写在状态目录 `settings.json`。
- `pack.cmd` / `pack.sh` / `pack_skill.py`：构建前端后打出可安装 skill zip（不含 `node_modules`）。
- 抽出 `service` 层，统一启停、按路径复用实例，以及 `watch.path` / `recursive` 变更时的 `needs_restart`。

### 修改

- 前端改为 shadcn + Vite，构建产物随 `filewatch/webui` 分发。

## 1.0.0 - 2026-09-11

### 新增

- 用 watchdog 监听目录的新建、修改、删除、移动。
- 以 Cursor skill + `scripts/filewatch_cli.py` 对外提供 CLI，skill 目录可单独拷贝安装。
- YAML 规则命中后写入 jobs 邮箱、可选 webhook，或用 `command` / `cursor_sdk` 启动智能体。
- 支持 `start` / `stop` / `wait` / `drain` / `ack`；stdout 为 JSON。
- 按路径去抖合并事件；忽略 `.git`、`*.tmp` 等默认模式。
- 附带 `scripts/test_watch_dir.py` 实测脚本。

### 修改

- 文档改为中文。
