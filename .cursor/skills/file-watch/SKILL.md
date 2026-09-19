---
name: file-watch
description: >-
  监听指定文件夹的新建、修改、删除、移动事件，按预设规则发送通知或启动智能体任务。
  在用户用自然语言制定或修改监听规则（含生效时段）、要求监听目录、等待新文件、启停 filewatch，
  打开事件网页，配置钉钉推送，或按文件变化条件触发任务时使用。把口语写成 YAML，
  钉钉 Webhook 写入设置而不是规则，validate 校验后再 reload 热更新。
---

# 文件监听

版本 **2.1.2**。

CLI 在本 skill 的 `scripts/` 里，随 skill 一起安装。不要自己写 watcher，也不要依赖仓库根目录的 `src/`。

先定位 **本 skill 根目录**（本 `SKILL.md` 所在目录），再执行脚本。依赖：

```bash
pip install -r requirements.txt
```

所有命令只在 stdout 打印 JSON，解析 JSON，不要刮日志。

状态目录在 `%LOCALAPPDATA%/filewatch`（或 `$FILEWATCH_HOME`）。不要把状态目录放进被监听的文件夹。

下文用 `python scripts/filewatch_cli.py` 表示相对本 skill 根目录。从本仓库调用时等价于：

```bash
python .cursor/skills/file-watch/scripts/filewatch_cli.py
```

## 自然语言制定规则

用户用口语描述监听条件时，**由当前对话 Agent 写成 YAML**，不要让用户手写，也不要现场生成 watcher，也不要调用网页的 LLM 接口。

流程固定为：

```text
1. list（按 path 对上已有实例）
   - 已有 → 记下 watch_id 和 home，读 home/config.json 当底稿
     （保留其 watch.path / recursive / debounce_ms / line_diff_quiet_ms / line_diff_max_bytes / ignore / record_all 和全部旧规则）
   - 没有 → 再 init 或新建 watch.yaml
2. 把自然语言合并进这份配置的 rules（追加则留旧规则；用户说替换才清空）。
   用户提到工作日/周末/几点到几点/上班时间等 → 写 when.active；没说时段则省略（一直生效）。
   用户说不监听/排除/忽略某类文件 → 写 `exclude: true`，then 为空，glob 如 `**/*.log`。
   用户说不要默认监听全部、只听规则指定的文件 → 写 `watch.record_all: false`。
   若要推钉钉：先按「钉钉推送」写入 settings.json 的渠道，规则里只引用渠道，不要写 webhook。
3. python scripts/filewatch_cli.py validate --config <这份文件>
4. ok: false → 根据 message 改配置，再 validate，不要 reload / start
5. list / status
   - 未运行 → start --config <这份文件> --id <watch_id>
   - 已运行 → reload --config <这份文件> --id <watch_id>
6. 向用户确认已生效的规则名
```

对已有路径**禁止** `start --path`：那会用空规则覆盖 `config.json`。热更新只换规则、忽略列表、去抖间隔和 `record_all`。`watch.path` 或 `recursive` 变了会返回 `needs_restart`：先 `stop`，再 `start --config` 同一份配置。已在运行时不要再 `start`（不会应用新配置）。

写规则时：

- 递归匹配用 `**/*.md`，不要只写 `*.md`。
- `when.types` 只能是 `created` / `modified` / `deleted` / `moved`。
- 用户提到生效时段、工作日、周末、几点到几点、上班时间、晚上才通知时，写 `when.active`（本机本地时间，不要写时区）。工作日 `days: [mon, tue, wed, thu, fri]`，周末 `[sat, sun]`。没说时段则省略 `active`，不要自行编造。`end` 早于 `start` 表示跨天（如 `22:00`–`06:00`）。也可写成 `active: "09:00-18:00"`。
- `then` 每项只能是 `notify` 或 `agent` 之一。反向规则 `exclude: true` 时 `then` 必须为空。
- 模板变量只能用 `{{path}}` `{{filename}}` `{{type}}` `{{watch_id}}` `{{ts}}` `{{old_path}}` `{{json}}` `{{rule}}`。
- 用户没说启动智能体/任务要求时，默认只写 `notify`（写入 jobs 邮箱）。
- 用户要按文件变化执行任务时，写 `agent.runner: builtin`，把任务要求放进 `prompt`；会调用设置页 LLM，带 Read/Glob/Grep/Write/Bash/PowerShell 工具循环。规则里选了钉钉渠道时，完成后立刻推送智能体最后一轮回复。
- 高级用法仍可用 `command` / `cursor_sdk`。
- 用户要推到钉钉群时，**不要**把 Webhook/SEC 写进规则 YAML。先写入设置里的 `dingtalk.channels`（见「钉钉推送」），规则只写 `notify.dingtalk: true` 或 `{channel: 渠道id}`。文件变化命中后每分钟汇总一次，不要写成即时 `notify.webhook`。同一规则若有内置智能体，任务完成后会立刻把最后一轮回复推到同一渠道。
- 用户说不监听、排除、忽略某类文件时，写反向规则：`exclude: true`，`then` 为空，`when.glob` 如 `**/*.log`。命中后该文件不会进入 events，也不会触发其它规则。默认仍记录全部文件（另有 `watch.ignore` 默认忽略 `.git` / `*.tmp` 等）。用户说不要默认监听全部、添加规则后才听指定文件时，写 `watch.record_all: false`：没有正向规则则不入账，有规则则只记录 glob/类型能对上的文件。
- 热更新时保留原来的 `watch.path` / `recursive`，除非用户明确要改监听目录。

## 流程

已有实例时先按「已有实例」读 `config.json`，不要从空 YAML 起步。全新配置则：

1. 编写 `watch.yaml`，填好 `watch.path` 和 `rules`。示例见 `examples/watch.yaml`。
2. `python scripts/filewatch_cli.py validate --config examples/watch.yaml` 检查语法。
3. `python scripts/filewatch_cli.py test-rule --config examples/watch.yaml --path <file> --type created` 确认规则能命中。带 `when.active` 的规则按**调用当时的本地时间**判断，时段外 `matched` 为空是正常结果。
4. 未运行则 `start --config examples/watch.yaml`；已运行则 `reload --config examples/watch.yaml --id <watch_id>`。不要 `start --path`。
5. 消费邮箱：
   - 原始文件系统事件：`wait --stream events`
   - 规则命中 / 通知 / 智能体结果：`wait --stream jobs`
6. 处理完后执行 `ack --stream <stream> --cursor <cursor>`。
7. 用户仍要监听时循环 `wait`。`timed_out: true` 且 `items` 为空是正常结果，不是错误。
8. 结束后执行 `python scripts/filewatch_cli.py stop --id <watch_id>`。

## 实测脚本

```bash
python scripts/test_watch_dir.py --path D:/data/inbox --pretty
```

会创建 `fw_probe_*` 文件（txt/md/json/py/tmp/.git），检查新建、修改、移动、删除、忽略规则和 notify job。全部通过才返回退出码 0。

## 命令

```bash
python scripts/filewatch_cli.py init --output watch.yaml
python scripts/filewatch_cli.py validate --config examples/watch.yaml
python scripts/filewatch_cli.py start --config examples/watch.yaml
python scripts/filewatch_cli.py reload --config examples/watch.yaml --id inbox
python scripts/filewatch_cli.py start --path D:/data/inbox --id inbox
python scripts/filewatch_cli.py start --path D:/data/inbox --id inbox --match-rules-only
python scripts/filewatch_cli.py start --config "%LOCALAPPDATA%/filewatch/inbox/config.json" --id inbox
python scripts/filewatch_cli.py status --id inbox
python scripts/filewatch_cli.py wait --id inbox --stream jobs --timeout 30
python scripts/filewatch_cli.py drain --id inbox --stream events
python scripts/filewatch_cli.py ack --id inbox --stream jobs --cursor 128
python scripts/filewatch_cli.py stop --id inbox
python scripts/filewatch_cli.py list
python scripts/filewatch_cli.py rename --id inbox --name 收件箱
python scripts/filewatch_cli.py serve --port 8765
```

`wait` 会阻塞到有数据或超时。优先用它，不要 sleep 再 drain。

`start --path` **只**用于 `list` 里还没有该路径的新目录。已有实例见下一节。

## 已有实例

网页和 CLI 共用状态目录。`list` / `status` 的 JSON 含 `watch_id`、`title`（显示名，默认文件夹名）、`path`、`running`、`record_all`、`home`、`rules`（仅规则名）。完整配置在 `home/config.json`（JSON，可直接当 `--config`）。`--id` 必须用 `list` 里的 `watch_id`，不要用配置里的 `name`（`name` 是可改的显示名；同名目录可能带哈希后缀）。

改任务显示名：

```bash
python scripts/filewatch_cli.py rename --id <watch_id> --name 新名称
```

空名称会恢复为文件夹名。`watch_id` 不变。网页列表和详情页的铅笔按钮同样可以改。

改规则（与网页「监听规则」同等）：

```text
1. list，按 path 找到实例
2. 读 home/config.json（不要 init 一份只含新规则的 YAML）
3. 把改动合并进 rules，其余字段原样保留
   钉钉凭证写入 settings.json 的 dingtalk.channels，规则只写 true 或 {channel: id}
4. 工作副本可写成 YAML 或继续用 JSON；validate --config <副本>
5. running → reload --config <副本> --id <watch_id>
   未运行 → start --config <副本> --id <watch_id>
```

重新拉起已停止的任务（与网页「开始监听」同等）：

```bash
python scripts/filewatch_cli.py start --config <home>/config.json --id <watch_id>
```

不要对已有路径再 `start --path`：未运行时会写成空规则并覆盖已保存配置。已在运行则 `start` 不会应用新配置，应 `reload`。

## 钉钉推送

凭证只放状态目录的 `settings.json`，禁止放进被监听路径，也禁止写进 `watch.yaml` / `config.json` 的规则。

文件：`%LOCALAPPDATA%/filewatch/settings.json`（或 `$FILEWATCH_HOME/settings.json`）。

用户给出钉钉 Webhook / SEC 时，由当前对话 Agent 写入设置，不要让用户去设置页手填（用户明确说自己填除外）：

```text
1. 读现有 settings.json；没有文件就当 {}
2. 原样保留 llm（不要清掉 API Key）
3. 合并 dingtalk.channels：追加新渠道，或按 id / name 更新已有项
4. 写回该文件
5. 规则 notify.dingtalk 只引用渠道：true（第一条）或 {channel: "<id>"}。有 builtin 任务要求时也可写在 agent.dingtalk，或沿用同规则 notify 的渠道。
```

渠道字段：

```json
{
  "llm": {"base_url": "...", "model": "...", "api_key": "...", "wire_api": "chat"},
  "dingtalk": {
    "channels": [
      {
        "id": "work",
        "name": "工作群",
        "webhook": "https://oapi.dingtalk.com/robot/send?access_token=TOKEN",
        "secret": "SECxxx",
        "interval_seconds": 60
      }
    ]
  }
}
```

`id` 用英文短横线（如 `work`），不要用中文当 id。`secret` 可空。`interval_seconds` 缺省 60。合并时不要丢掉其它已有渠道。

用户只说「推到钉钉」、没给地址：

- `settings.json` 里已有渠道 → 规则写 `dingtalk: true`，或用户点名的 `{channel: id}`
- 还没有渠道 → 打开设置页 `/settings`，或向用户要 Webhook 和 SEC；配好后再写规则。不要把 webhook 写进规则凑合

旧规则里的 `notify.dingtalk.webhook` / `secret` 仍能运行。写新规则或改旧规则时，把凭证迁到 `dingtalk.channels`，规则改成渠道引用。

## 网页

在本机打开任务面板。首页按监听目录列出任务，名称默认为文件夹名、可改；详情分「文件变化」、「监听规则」和「智能体」：

- 文件变化：该目录的新建 / 修改 / 删除 / 移动；可按文件名或路径搜索，并与类型、时间筛选一起用。内容未变的 `modified`（仅时间戳/属性、编辑器空保存等）不入列表。可读文本在安静 `line_diff_quiet_ms`（默认 30 秒，可在设置页改）后显示行级 `+N / −M`，可展开查看增减行；列表不保留「行级结算中…」，同路径未结算的中间修改会被后一条替换。添加目录时可关掉「默认监听全部文件变化」，之后也可在任务页切换；关掉后只记录命中正向规则的文件
- 监听规则：手动添加（任务要求非空即 builtin 智能体；也可添加反向规则排除某类文件；钉钉从下拉栏选设置页里的渠道；生效时间可填开始/结束和星期，都留空则一直生效），或用自然语言添加新规则（只追加，不改已有规则；调用 LLM；也可粘贴 YAML/JSON，不经模型）。打开规则编辑后，可在表单顶部用自然语言由 AI 填入该条，确认后再保存。已运行则热更新，未运行则写入配置等下次 start。选了钉钉且填写了任务要求时，智能体完成后立刻把最后一轮回复推到该群。
- 智能体：只列出填写了任务要求的规则；点进某条后，该规则的执行过程以 SSE 实时日志按轮次展示（system / user / agent / 工具命令，可展开）。工具日志仍写入 `home/agent-logs/<job_id>.jsonl`
- 设置：`/settings` 填写 `base_url` / `model` / API Key，并选择协议 `wire_api`（`chat` 走 `/chat/completions`，`responses` 走 `/responses`，`anthropic` 走 `/messages`）。接口地址旁可打开常见端点列表（国产 Chat Completions、Anthropic Messages、Responses）一键填入。钉钉群机器人（名称、Webhook、SEC），以及事件入账去抖、行级快照等待和最大文件。Key 和钉钉凭证写入 `%LOCALAPPDATA%/filewatch/settings.json`（或 `$FILEWATCH_HOME`），不要放进被监听目录。也可用环境变量 `FILEWATCH_LLM_API_KEY`、`FILEWATCH_LLM_BASE_URL`、`FILEWATCH_LLM_MODEL`、`FILEWATCH_LLM_WIRE_API`。规则里不要再写钉钉 webhook

用户要打开面板时：

1. 若只要打开已有面板、且 `http://127.0.0.1:8765/`（或指定端口）已可访问，直接把地址给用户。
2. 需要重新拉起时**后台**启动：同端口上的旧 `serve` 会被结束，只保留本次进程。读完第一行 JSON 就继续当前对话，不要把会话阻塞到 Ctrl+C：

```bash
python scripts/filewatch_cli.py serve --port 8765 --open
```

浏览器访问 JSON 里的 `url`（默认 `http://127.0.0.1:8765/`）。可同时添加多个目录；同一路径会复用已有任务。默认只绑定本机回环地址。加 `--open` 可自动打开浏览器。关掉浏览器不会停止已经在听的目录；不要为了关网页去 `stop` 守护进程。只要面板、目录稍后再定时，可以先不起具体目录。改前端源码在 `web/`，构建：`npm run build`（产物在 `scripts/filewatch/webui/`）。

`serve` 的 stdout 只打一行 JSON，随后进程保持运行直到被结束。日志走 stderr。再次 `serve` 同一端口会结束旧进程，JSON 里的 `replaced_pids` 是被替换的 PID。

## 规则

规则在守护进程内执行。命中后写入 job，并可能立刻启动智能体。这是推送路径；`wait` 是拉取路径。

```yaml
name: inbox
watch:
  path: D:/data/inbox
  recursive: true
  debounce_ms: 400
  line_diff_quiet_ms: 30000
  line_diff_max_bytes: 262144
  # record_all: false   # 仅记录命中正向规则的文件；省略或 true 则默认记录全部变化
  ignore: ["**/.git/**", "**/__pycache__/**", "**/*.tmp"]
rules:
  - name: new-markdown
    when:
      types: [created, modified]
      glob: "**/*.md"
      is_dir: false
      cooldown_seconds: 30
      # active:                     # 省略则一直生效
      #   start: "09:00"
      #   end: "18:00"
      #   days: [mon, tue, wed, thu, fri]
    then:
      - notify:
          title: "Markdown 有变化"
          message: "{{type}}: {{path}}"
          webhook: "https://example.invalid/hook"   # 可选，立即 POST JSON
          dingtalk: true                            # 使用设置页默认钉钉渠道；或 {channel: 渠道id}
      - agent:
          runner: builtin
          prompt: |
            工作区是监听根目录。对 docs 下所有 .md 按参考格式重写。
            本次触发：{{type}} {{path}}
          timeout_seconds: 600
          max_steps: 24
          dingtalk: true                            # 完成后立刻推送最后一轮回复；省略则沿用上面 notify 的渠道
  - name: skip-logs
    exclude: true
    when:
      glob: "**/*.log"
```

`when` 字段：`types`、`glob`（字符串或列表）、`regex`、`is_dir`、`min_size_bytes`、`cooldown_seconds`、`active`。

反向规则设 `exclude: true`，`then` 必须为空，且必须有 `glob` 或 `regex`。命中后不写入 events、不触发其它规则。省略 `types` 时排除全部事件类型。`watch.record_all` 省略或 `true` 时仍记录全部未排除的文件；设为 `false` 后只记录命中正向规则（glob / 类型 / is_dir）的文件，没有正向规则则不入账。`watch.ignore` 是更底层的忽略列表，三者独立。

`active` 按**本机本地时间**限制规则何时可命中。省略、`null` 或空对象表示一直生效。

```yaml
when:
  types: [created, modified]
  glob: "**/*.md"
  active:
    start: "09:00"          # 可选，缺省 00:00
    end: "18:00"            # 可选，缺省 24:00；早于 start 表示跨天，如 22:00–06:00
    days: [mon, tue, wed, thu, fri]  # 可选，缺省每天；也可用 1–7（周一=1）
```

也可写成 `active: "09:00-18:00"`（每天该时段）。`start` 与 `end` 不能相同；全天只限制星期时只写 `days`。`test-rule` 按调用当时的本地时间判断时段。

`then` 动作：

- `notify`：一律写入 `jobs` 流；可选 `webhook` 立即 POST JSON（不是钉钉）。钉钉用 `dingtalk: true` 或 `{channel: id}`，凭证在设置 `dingtalk.channels`，命中后按分钟汇总（无变化不发送）。规则内 webhook/secret 仅兼容旧配置。
- `agent.runner: builtin`（默认）：任务要求写在 `prompt`；调用设置页 LLM（`FILEWATCH_HOME/settings.json`），内置工具 Read / Glob / Grep / Write / Bash / PowerShell。工作流写入 `home/agent-logs/<job_id>.jsonl`，网页「智能体」页用 SSE 实时展示。可选 `max_steps`（默认 24）、`model`（覆盖设置中的模型）。规则选了钉钉渠道时（`agent.dingtalk` 或同规则的 `notify.dingtalk`），任务成功完成后立刻推送智能体最后一轮回复（不按分钟汇总）；推送失败不影响任务本身的 `ok` 状态。
- `agent.runner: command`：执行 argv。prompt 走 stdin，同时设置 `FILEWATCH_PROMPT` 和 `FILEWATCH_EVENT_JSON`。
- `agent.runner: cursor_sdk`：需要 `cursor-sdk` 和 `CURSOR_API_KEY`。会启动**一次新的**智能体 run，不会唤醒当前对话。

`runner` 缺省：有 `prompt` 且无 `command` → `builtin`；有 `command` → `command`。网页「任务要求」非空即提交 `builtin`。

模板变量：`{{path}}`、`{{filename}}`、`{{type}}`、`{{watch_id}}`、`{{ts}}`、`{{old_path}}`、`{{json}}`、`{{rule}}`。

递归匹配要用 `**/*.md`，不要只写 `*.md`（后者只匹配监听根目录下的文件名）。

## Agent 消费循环

```text
start --config watch.yaml
loop:
  result = wait --stream jobs --timeout 30
  if result.items:
      处理 items
      ack --stream jobs --cursor result.cursor
  elif 用户仍要求监听:
      continue
  else:
      break
stop
```

没有配置规则时，改为 `wait --stream events`。

`events` 流里，可读文本文件会附带 `line_changes`（行级增删）。事件仍按 `watch.debounce_ms`（默认 400ms）入账；若 `modified` 的内容与上次指纹或行级快照相同，则不写入 events、也不触发规则（操作系统仍可能因时间戳/属性发出 modified）。行级快照另等 `watch.line_diff_quiet_ms`（默认 30000ms / 30 秒）该文件无新事件后再结算，结果按 `event_id` 合并进读取。超过 `watch.line_diff_max_bytes`（默认 256KB）视为过大，`kind: skipped`。规则匹配仍按文件级，不读行内容。二进制 / 尚无基线时同样为 `skipped`。结算前可能是 `kind: pending`，网页列表不展示该状态，被后续同路径事件覆盖的未结算 `modified` 也不出现在列表中。入账去抖、快照等待和最大文件也可在设置页修改，保存后应用到已有任务。

先 `status` / `list`，已有同类 watcher 就复用，不要对同一路径再开一个守护进程。改规则先读 `home/config.json` 再 `reload`；未运行则 `start --config` 该配置。不要对已有路径 `start --path`。

## 打包

skill 目录里的 `web/` 是未构建源码。分发前在本 skill 根目录执行：

```bash
python scripts/pack_skill.py
```

Windows 也可双击 `pack.cmd`。脚本会 `npm install` + `npm run build`，然后打出 `dist/file-watch-<版本>.zip`（不含 `node_modules`）。把 zip 解压到 `.cursor/skills/` 得到 `file-watch/`。已构建过、只想重新打 zip 时加 `--skip-build`。不要前端源码时加 `--no-web-src`。
