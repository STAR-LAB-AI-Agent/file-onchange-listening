# 更新日志

## Unreleased

### 新增

- `pack_nanobot.py` / `pack_nanobot.cmd`：把 skill 整理成 nanobot 允许的目录（仅 `SKILL.md`、`scripts/`、`references/`）并打成 `.skill`；依赖和示例分别放到 `scripts/requirements.txt` 与 `references/examples/`。
- 设置页可拉取当前 LLM 接口的模型列表（`GET {base_url}/models`），按字母顺序从下拉框选择；未保存的接口地址 / Key / 协议也可用于拉取。面板已开时也可 `POST /api/settings/models`。

## 2.1.3 - 2026-09-19

### 新增

- 文件变化邮箱、任务邮箱和守护进程日志按本机日期切分（`events-YYYY-MM-DD.jsonl` / `jobs-YYYY-MM-DD.jsonl` / `daemon-YYYY-MM-DD.log`），默认保留 14 天，避免单个文件一直增大。可在设置页改「日志保留（天）」，写入 `settings.json` 的 `logs.keep_days`（1–365）；保存后立刻按新天数清理。未在设置里保存时也可用环境变量 `FILEWATCH_LOG_KEEP_DAYS`。启动时会把旧的 `events.jsonl` / `jobs.jsonl` / `daemon.log` 迁到带日期的文件。已结束的智能体日志同样按保留期清理，进行中的任务不删。
- 规则选了钉钉渠道且填写了内置智能体任务要求时，任务成功完成后立刻把智能体最后一轮回复推到该群（不按分钟汇总）。可写 `agent.dingtalk`，省略则沿用同规则的 `notify.dingtalk`。推送失败不影响任务 `ok` 状态。
- 网页自然语言生成或「AI编辑」规则时，LLM 输出无法校验或调用失败会把错误原因和上次输出一并再发一轮；Key 未配置或鉴权失败不重试。
- 网页规则表单可设置内置智能体任务超时。
- 文件变化列表在同一文件短时间反复出现（默认 45 秒内 ≥6 次）时，在上方单独列出候选，可全选或勾选多个后加入同一条排除规则。行级尚未结算的中间修改也计入次数。

### 修改

- 网页规则页去掉独立的「添加排除规则」按钮；排除规则在「手动添加」表单里切换规则类型即可。
- 内置智能体 `timeout_seconds` 默认改为 1800 秒（30 分钟）；省略该字段的规则按新默认解析。

## 2.1.2 - 2026-09-19

### 修改

- `serve` 启动时结束同端口上的旧进程，只保留本次实例。
- 文件变化列表不再显示「行级结算中…」；同路径后续事件会替换未结算的中间修改，安静窗口结束后直接出现行级结果。

### 新增

- 网页任务详情新增「智能体」页：先按填写了任务要求的规则筛选，点进某条后再看该规则的 SSE 实时日志轮（时间、system / user / agent / 工具命令，可展开）。
- 设置页钉钉渠道可「发送测试」：立刻向该群机器人推一条测试消息，用于核对 Webhook / SEC。
- 设置页 LLM 支持三种协议：OpenAI Chat Completions、OpenAI Responses、Anthropic Messages。`settings.json` 的 `llm.wire_api` 为 `chat` / `responses` / `anthropic`（缺省 `chat`，旧配置无需改动）；也可用环境变量 `FILEWATCH_LLM_WIRE_API`。自然语言生成规则和内置智能体都走同一套转换，内部仍按 Chat Completions 形状处理工具调用。
- 设置页可从常见国产 / 官方端点列表一键填入接口地址和示例模型（Chat Completions 含智谱、DeepSeek、百炼、Kimi 等；另有 Anthropic Messages 与 Responses 端点）。

## 2.1.1 - 2026-09-19

### 新增

- 反向规则 `exclude: true`：默认仍监听全部文件变化；命中后该路径不写入 events、不触发其它规则。网页可手动添加排除规则，自然语言「不要监听 log」也会生成。
- `watch.record_all`：默认 `true` 仍记录全部变化；`false` 时只记录命中正向规则的文件（没有规则则不入账）。网页添加目录时可关「默认监听全部文件变化」，任务页也可切换；CLI `start --path --match-rules-only`；运行中可热更新。
- 监听任务可改显示名称（默认文件夹名）。网页列表和详情可编辑；CLI `rename --id <watch_id> --name <名称>`；顶层 YAML `name` 是显示名，不改变 `watch_id`。
- 网页文件变化列表可按文件名或路径搜索，并与类型、时间筛选一起生效。
- 网页规则编辑对话框顶部「AI编辑」：输入自然语言后填入表单，确认再保存。

### 修改

- 行级快照默认安静窗口改为 30 秒（`watch.line_diff_quiet_ms` 默认 30000）。
- 设置页可修改事件入账去抖、行级快照等待和最大文件；保存后写入 `settings.json` 的 `watch`，并应用到已有任务（运行中热更新）。
- 网页自然语言生成只追加新规则，不再支持替换全部。

### 修复

- 内容未变的 `modified` 不再写入文件变化列表、也不触发规则：入账前对比文本指纹或已有行级快照。网页查询会隐藏已结算为 `+0 / −0` 的历史记录。

## 2.1.0 - 2026-09-19

### 新增

- 可读文本的行级变化：事件仍按 `watch.debounce_ms` 入账；`watch.line_diff_quiet_ms`（默认 2 秒）后再结算 `line_changes`（`+N / −M`）。二进制、过大或尚无基线为 `skipped`，结算前为 `pending`。规则匹配仍按文件级。
- 网页任务详情可展开查看增减行。

## 2.0.1 - 2026-09-17

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
