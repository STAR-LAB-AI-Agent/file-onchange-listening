# 更新日志

## Unreleased

## 2.0.6 - 2026-09-17

### 新增

- `when.active`：规则可按本机本地时段和星期生效（工作日、跨天如 `22:00`–`06:00`，也可写成 `"09:00-18:00"`）；省略则一直生效。网页规则表单可填开始/结束时间和星期。
- 任务详情的文件变化支持按时间范围、事件类型筛选，以及分页浏览。

### 修改

- 钉钉 Webhook / SEC 改到设置页（`settings.json` 的 `dingtalk.channels`）。规则只选择渠道：`notify.dingtalk: true` 或 `{channel: 渠道id}`；添加规则时从下拉栏选择。规则里旧的 webhook/secret 仍可用。

## 2.0.0 - 2026-09-11

### 新增

- `notify.dingtalk`：把规则命中的文件变化推到钉钉群机器人（Webhook + SEC 加签），默认每分钟汇总一次，无变化不发送。
- `agent.runner: builtin`：规则写了任务要求即启动内置 Agent 循环，调用设置页 LLM，工具含 Read / Glob / Grep / Write / Bash / PowerShell；工具调用写入 `agent-logs/`；Write 会短期抑制同路径自触发。

### 修改

- 网页规则表单以「任务要求」为主路径（非空即 builtin）；`command` / `cursor_sdk` 仍可通过 YAML 使用。
- `runner` 缺省：有 prompt 无 command → builtin；有 command → command。

## 1.1.1 - 2026-09-11

### 修改

- README 补充 Skill 推荐工作流：开头点明可用 Web；用示例提示词及其效果说明启动与网页、设置目录、新增规则（也可由 Agent 调用 skill）。
- skill：改已有任务规则时先读状态目录 `config.json`；重启已停止任务须 `start --config` 原配置，禁止对已有路径 `start --path`；`serve` 须后台启动。

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
