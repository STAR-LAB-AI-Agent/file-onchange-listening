# CODEMAP

filewatch：按规则监听目录变化，发通知或启动智能体。实现全部在 Cursor skill 里，仓库根目录只放文档、测试和打包元数据。

对外入口：

```bash
python .cursor/skills/file-watch/scripts/filewatch_cli.py <子命令>
```

## 怎么读这份图

- **仓库根**负责开发（`pytest`、`pyproject.toml`）。
- **`.cursor/skills/file-watch/`** 是可拷贝安装的产品；CLI、守护进程、网页都在这里。
- 运行时状态在 `%LOCALAPPDATA%/filewatch`（或 `FILEWATCH_HOME`），不进 git、也不要放进被监听目录。

## 仓库总览

```text
file-onchange-listening/
├── pyproject.toml          # 包名 filewatch-agent；发现路径指向 skill/scripts
├── README.md               # 人类安装与工作流
├── CHANGELOG.md
├── CODEMAP.md              # 本文件
├── tests/                  # pytest；pythonpath = skill/scripts
└── .cursor/skills/file-watch/   # 唯一实现（随 skill 分发）
```

根目录没有 `src/`。不要把 CLI 挪回仓库根。

## Skill 树

```text
.cursor/skills/file-watch/
├── SKILL.md                 # Agent 调用协议（自然语言改规则、CLI 流程）
├── requirements.txt         # watchdog, PyYAML
├── pack.cmd / pack.sh       # npm run build → zip
├── examples/watch.yaml      # 示例配置与注释
├── scripts/
│   ├── filewatch_cli.py     # CLI 入口（不要改名为 filewatch.py）
│   ├── pack_skill.py        # 构建 web/ 后打 dist/file-watch-<版本>.zip
│   ├── test_watch_dir.py    # 真实目录实测
│   ├── echo_agent.py        # agent.runner=command 示例
│   └── filewatch/           # Python 实现包
└── web/                     # Vite + React + shadcn 源码
```

`npm run build` 把前端写到 `scripts/filewatch/webui/`，由 `serve` 静态托管。

## Python 包（`scripts/filewatch/`）

按调用链分层，不是按字母。

```text
filewatch/
├── __init__.py              # __version__
├── __main__.py              # python -m filewatch
├── cli.py                   # argparse；stdout 只输出 JSON
├── service.py               # 启停、热更新、改规则；CLI 与网页共用
├── process.py               # 守护进程 spawn / pid / 端口占用
├── runtime.py               # watchdog 观察者；去抖后入账并跑规则
├── store.py                 # 每实例邮箱：按日 events-*.jsonl / jobs-*.jsonl
├── rotate.py                # 按日切分、游标编码、保留天数、daemon 日志流
├── config.py                # YAML/JSON → Config；校验
├── models.py                # FileEvent、Rule、When、Notify/Agent 动作
├── matching.py              # 相对 posix glob（**/ 可为空前缀）
├── rules.py                 # RuleEngine：排除优先，再匹配正向规则
├── debounce.py              # 按路径合并事件，单线程到期刷新
├── linediff.py              # 文本快照 + 行级 +N/−M
├── frequent.py              # 短时间反复变化 → 排除候选
├── actions.py               # notify / builtin|command|cursor_sdk 智能体
├── templates.py             # {{path}} {{filename}} {{type}} …
├── paths.py                 # FILEWATCH_HOME、watch_id slug
├── settings.py              # settings.json：LLM Key、钉钉渠道、去抖、日志保留
├── llm.py                   # chat / responses / anthropic
├── responses_compat.py
├── anthropic_compat.py
├── dingtalk.py              # 群机器人；文件变化按分钟汇总
├── nl_rules.py              # 网页口语 → 规则 JSON（只追加或改当前条）
├── agent_logs.py            # 智能体 SSE 日志
├── web.py                   # ThreadingHTTPServer + /api/*
├── webui/                   # 构建产物（不要手改）
└── agent/                   # 内置智能体（runner: builtin）
    ├── loop.py              # LLM + 工具循环
    ├── registry.py          # 工具注册
    ├── types.py
    ├── logging.py
    ├── sandbox.py           # 限制在监听根目录；保护 FILEWATCH_HOME / skill
    └── tools/
        ├── read.py
        ├── write.py
        ├── glob_tool.py
        ├── grep.py
        ├── bash.py
        └── powershell.py
```

### 模块职责

| 文件 | 做什么 |
|------|--------|
| `cli.py` | `init` `validate` `start` `run` `stop` `status` `list` `rename` `wait` `drain` `ack` `reload` `test-rule` `serve` |
| `service.py` | 列任务、按路径复用实例、`reload`（`path`/`recursive` 变了返回 `needs_restart`）、口语规则、频繁文件排除 |
| `runtime.py` | 把 watchdog 事件滤成 created/modified/deleted/moved，去抖、行级结算、`record_all`、写邮箱、提交动作 |
| `store.py` | 按日 jsonl、游标、pid、reload 旗标、行级缓存、文本快照 |
| `rules.py` | `exclude: true` 命中则不入账、不触发其它规则；正向规则看 glob/类型/时段/冷却 |
| `actions.py` | 通知进 `jobs`；钉钉批量；builtin 走 `agent.loop` |
| `web.py` | 静态 `webui/` + JSON API；同一端口再次 `serve` 会结束旧进程 |

## 前端（`web/src/`）

Hash 无关，用 `history.pushState`。路由在 `lib/api.ts` 的 `parseAppRoute`。

```text
web/src/
├── main.tsx / App.tsx
├── index.css
├── lib/
│   ├── api.ts               # 类型、fetch、路由、规则空白模板
│   ├── llmEndpoints.ts      # 常见国产 / 官方接口地址
│   └── utils.ts
├── pages/
│   ├── TaskList.tsx         # /  按目录列任务、添加、启停
│   ├── TaskDetail.tsx       # /t/:id  文件变化 + 频繁排除候选
│   ├── TaskRules.tsx        # /t/:id/rules  手动 / 口语追加规则
│   ├── TaskAgent.tsx        # /t/:id/agent  按规则看智能体日志
│   └── Settings.tsx         # /settings  LLM、钉钉、去抖与行级参数
└── components/
    ├── RuleForm.tsx         # 正向 / 排除；可 AI 填入当前条
    ├── FrequentExcludePanel.tsx
    ├── LiveLogPanel.tsx     # SSE
    ├── TaskChrome.tsx       # 任务页顶栏
    ├── WatchTitle.tsx
    └── ui/                  # shadcn
```

构建输出：`scripts/filewatch/webui/`（`vite.config.ts` 的 `build.outDir`）。

## 运行时数据流

```text
被监听目录
    │  watchdog
    ▼
WatchRuntime          忽略 glob、去抖、行级快照
    │
    ├─ record_all / 正向规则？ → events-YYYY-MM-DD.jsonl（文件变化）
    └─ RuleEngine 命中正向规则 → ActionRunner
           ├─ notify → jobs-YYYY-MM-DD.jsonl；钉钉按分钟汇总
           └─ agent
                ├─ builtin → agent/loop.py + 设置页 LLM
                ├─ command → 外部进程
                └─ cursor_sdk

CLI wait/drain/ack 与网页 /api/watchers/:id/events
都读同一套 WatchStore。
```

热更新：写 `reload.flag` + 新 `config.json`；守护进程在 `run` 里应用。不能热更新的只有 `watch.path` 和 `recursive`。

## HTTP API

`serve` 默认 `http://127.0.0.1:8765/`。非 `/api/` 的路径回退 `index.html`。

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/health` | 探活 |
| GET/PUT | `/api/settings` | 读/写设置（Key 不回明文） |
| POST | `/api/settings/test` | 测 LLM |
| POST | `/api/settings/dingtalk/test` | 测钉钉 |
| GET | `/api/watchers` | 任务列表 |
| POST | `/api/watchers/start` | 添加并启动目录 |
| GET | `/api/watchers/:id` | 任务摘要 |
| GET | `/api/watchers/:id/config` | 当前配置 |
| GET | `/api/watchers/:id/events` | 分页文件变化 + 频繁候选 |
| POST | `/api/watchers/:id/stop` | 停止 |
| POST | `/api/watchers/:id/rename` | 改显示名 |
| PUT | `/api/watchers/:id/watch` | `record_all` 等 watch 选项 |
| PUT | `/api/watchers/:id/rules` | 保存规则列表 |
| POST | `/api/watchers/:id/rules/from-text` | 口语追加（LLM） |
| POST | `/api/watchers/:id/rules/:n/from-text` | AI 编辑第 n 条 |
| POST | `/api/watchers/:id/exclude-paths` | 勾选路径合成一条排除规则 |
| GET | `/api/watchers/:id/agent-logs` | 智能体日志 |
| GET | `/api/watchers/:id/agent-logs/stream` | SSE |

## 状态目录

默认 Windows：`%LOCALAPPDATA%/filewatch`。

```text
FILEWATCH_HOME/
├── settings.json            # LLM、钉钉渠道、全局去抖/行级上限、logs.keep_days
└── watchers/<watch_id>/
    ├── config.json          # 该任务生效配置
    ├── daemon.pid / daemon-YYYY-MM-DD.log / stop.flag
    ├── events-YYYY-MM-DD.jsonl / jobs-YYYY-MM-DD.jsonl / cursors.json
    ├── reload.flag / reload.status.json / pending.json
    ├── line_changes.json
    ├── text-snapshots/
    └── agent-logs/
```

凭证只放 `settings.json`。规则 YAML 里的钉钉只引用渠道 id，不写 webhook。

## 测试对照

`tests/` 文件名大致对应模块：

| 测试 | 覆盖 |
|------|------|
| `test_cli.py` | JSON 子命令 |
| `test_service.py` `test_reload.py` `test_process.py` | 启停、热更新、进程 |
| `test_runtime.py` `test_debounce.py` `test_matching.py` `test_rules.py` | 监听与匹配 |
| `test_store.py` `test_rotate.py` `test_linediff.py` `test_frequent.py` | 邮箱、按日切分、行级、频繁排除 |
| `test_actions.py` `test_templates.py` `test_dingtalk.py` | 动作与推送 |
| `test_nl_rules.py` `test_settings.py` `test_llm_wire.py` | 口语规则与 LLM 协议 |
| `test_web.py` | HTTP API |
| `test_agent_loop.py` `test_agent_tools.py` `test_builtin_runtime.py` `test_agent_logs.py` | 内置智能体 |
| `test_pack_skill.py` `test_watch_dir_script.py` | 打包与实测脚本 |

改监听 / 规则 / CLI 后跑 `pytest`。真目录再跑 `scripts/test_watch_dir.py`。

## 建议阅读顺序

1. `SKILL.md` — Agent 该怎么调 CLI。
2. `cli.py` → `service.py` → `runtime.py` — 启停到入账。
3. `rules.py` + `matching.py` — glob 与排除。
4. `actions.py` → `agent/loop.py` — 通知与内置智能体。
5. `web.py` + `web/src/pages/` — 面板。
6. `paths.py` + `store.py` + `settings.py` — 状态落盘位置。
