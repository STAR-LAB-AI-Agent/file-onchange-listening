---
name: file-watch
description: >-
  监听指定文件夹的新建、修改、删除、移动事件，按预设规则发送通知或启动智能体任务。
  在用户用自然语言制定或修改监听规则、要求监听目录、等待新文件、启停 filewatch，
  打开事件网页，或按文件变化条件触发任务时使用。把口语写成 YAML，validate 校验后再 reload 热更新。
---

# 文件监听

版本 **2.0.0**。

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
     （保留其 watch.path / recursive / debounce_ms / ignore 和全部旧规则）
   - 没有 → 再 init 或新建 watch.yaml
2. 把自然语言合并进这份配置的 rules（追加则留旧规则；用户说替换才清空）
3. python scripts/filewatch_cli.py validate --config <这份文件>
4. ok: false → 根据 message 改配置，再 validate，不要 reload / start
5. list / status
   - 未运行 → start --config <这份文件> --id <watch_id>
   - 已运行 → reload --config <这份文件> --id <watch_id>
6. 向用户确认已生效的规则名
```

对已有路径**禁止** `start --path`：那会用空规则覆盖 `config.json`。热更新只换规则、忽略列表和去抖间隔。`watch.path` 或 `recursive` 变了会返回 `needs_restart`：先 `stop`，再 `start --config` 同一份配置。已在运行时不要再 `start`（不会应用新配置）。

写规则时：

- 递归匹配用 `**/*.md`，不要只写 `*.md`。
- `when.types` 只能是 `created` / `modified` / `deleted` / `moved`。
- `then` 每项只能是 `notify` 或 `agent` 之一。
- 模板变量只能用 `{{path}}` `{{filename}}` `{{type}}` `{{watch_id}}` `{{ts}}` `{{old_path}}` `{{json}}` `{{rule}}`。
- 用户没说启动智能体/任务要求时，默认只写 `notify`（写入 jobs 邮箱）。
- 用户要按文件变化执行任务时，写 `agent.runner: builtin`，把任务要求放进 `prompt`；会调用设置页 LLM，带 Read/Glob/Grep/Write/Bash/PowerShell 工具循环。
- 高级用法仍可用 `command` / `cursor_sdk`。
- 用户要推到钉钉群时，在 `notify.dingtalk` 填写 `webhook` 和 `secret`（SEC 加签）。命中后每分钟汇总一次，不要写成即时 webhook。
- 热更新时保留原来的 `watch.path` / `recursive`，除非用户明确要改监听目录。

## 流程

已有实例时先按「已有实例」读 `config.json`，不要从空 YAML 起步。全新配置则：

1. 编写 `watch.yaml`，填好 `watch.path` 和 `rules`。示例见 `examples/watch.yaml`。
2. `python scripts/filewatch_cli.py validate --config examples/watch.yaml` 检查语法。
3. `python scripts/filewatch_cli.py test-rule --config examples/watch.yaml --path <file> --type created` 确认规则能命中。
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
python scripts/filewatch_cli.py start --config "%LOCALAPPDATA%/filewatch/inbox/config.json" --id inbox
python scripts/filewatch_cli.py status --id inbox
python scripts/filewatch_cli.py wait --id inbox --stream jobs --timeout 30
python scripts/filewatch_cli.py drain --id inbox --stream events
python scripts/filewatch_cli.py ack --id inbox --stream jobs --cursor 128
python scripts/filewatch_cli.py stop --id inbox
python scripts/filewatch_cli.py list
python scripts/filewatch_cli.py serve --port 8765
```

`wait` 会阻塞到有数据或超时。优先用它，不要 sleep 再 drain。

`start --path` **只**用于 `list` 里还没有该路径的新目录。已有实例见下一节。

## 已有实例

网页和 CLI 共用状态目录。`list` / `status` 的 JSON 含 `watch_id`、`path`、`running`、`home`、`rules`（仅规则名）。完整配置在 `home/config.json`（JSON，可直接当 `--config`）。`--id` 必须用 `list` 里的 `watch_id`，不要用配置里的 `name`（同名目录可能带哈希后缀）。

改规则（与网页「监听规则」同等）：

```text
1. list，按 path 找到实例
2. 读 home/config.json（不要 init 一份只含新规则的 YAML）
3. 把改动合并进 rules，其余字段原样保留
4. 工作副本可写成 YAML 或继续用 JSON；validate --config <副本>
5. running → reload --config <副本> --id <watch_id>
   未运行 → start --config <副本> --id <watch_id>
```

重新拉起已停止的任务（与网页「开始监听」同等）：

```bash
python scripts/filewatch_cli.py start --config <home>/config.json --id <watch_id>
```

不要对已有路径再 `start --path`：未运行时会写成空规则并覆盖已保存配置。已在运行则 `start` 不会应用新配置，应 `reload`。

## 网页

在本机打开任务面板。首页按监听目录列出任务；详情分「文件变化」和「监听规则」：

- 文件变化：该目录的新建 / 修改 / 删除 / 移动
- 监听规则：手动添加（任务要求非空即 builtin 智能体），或用自然语言生成（调用 LLM；也可粘贴 YAML/JSON，不经模型）。已运行则热更新，未运行则写入配置等下次 start
- 设置：`/settings` 填写兼容 OpenAI 的 `base_url` / `model` / API Key。Key 写入 `%LOCALAPPDATA%/filewatch/settings.json`（或 `$FILEWATCH_HOME`），不要放进被监听目录。也可用环境变量 `FILEWATCH_LLM_API_KEY`、`FILEWATCH_LLM_BASE_URL`、`FILEWATCH_LLM_MODEL`

用户要打开面板时：

1. 若 `http://127.0.0.1:8765/`（或指定端口）已可访问，直接把地址给用户，不要再起一个 `serve`。
2. 否则**后台**启动，读完第一行 JSON 就继续当前对话，不要把会话阻塞到 Ctrl+C：

```bash
python scripts/filewatch_cli.py serve --port 8765 --open
```

浏览器访问 JSON 里的 `url`（默认 `http://127.0.0.1:8765/`）。可同时添加多个目录；同一路径会复用已有任务。默认只绑定本机回环地址。加 `--open` 可自动打开浏览器。关掉浏览器不会停止已经在听的目录；不要为了关网页去 `stop` 守护进程。只要面板、目录稍后再定时，可以先不起具体目录。改前端源码在 `web/`，构建：`npm run build`（产物在 `scripts/filewatch/webui/`）。

`serve` 的 stdout 只打一行 JSON，随后进程保持运行直到被结束。日志走 stderr。

## 规则

规则在守护进程内执行。命中后写入 job，并可能立刻启动智能体。这是推送路径；`wait` 是拉取路径。

```yaml
name: inbox
watch:
  path: D:/data/inbox
  recursive: true
  debounce_ms: 400
  ignore: ["**/.git/**", "**/__pycache__/**", "**/*.tmp"]
rules:
  - name: new-markdown
    when:
      types: [created, modified]
      glob: "**/*.md"
      is_dir: false
      cooldown_seconds: 30
    then:
      - notify:
          title: "Markdown 有变化"
          message: "{{type}}: {{path}}"
          webhook: "https://example.invalid/hook"   # 可选，立即 POST JSON
          dingtalk:                                 # 可选，每分钟汇总推送到钉钉群
            webhook: "https://oapi.dingtalk.com/robot/send?access_token=TOKEN"
            secret: "SECxxx"
            interval_seconds: 60
      - agent:
          runner: builtin
          prompt: |
            工作区是监听根目录。对 docs 下所有 .md 按参考格式重写。
            本次触发：{{type}} {{path}}
          timeout_seconds: 600
          max_steps: 24
```

`when` 字段：`types`、`glob`（字符串或列表）、`regex`、`is_dir`、`min_size_bytes`、`cooldown_seconds`。

`then` 动作：

- `notify`：一律写入 `jobs` 流；可选 `webhook` 立即 POST JSON。可选 `dingtalk` 把命中事件按分钟汇总推到钉钉群（Webhook + SEC 加签；无变化不发送）。
- `agent.runner: builtin`（默认）：任务要求写在 `prompt`；调用设置页 LLM（`FILEWATCH_HOME/settings.json`），内置工具 Read / Glob / Grep / Write / Bash / PowerShell。工具日志在 `home/agent-logs/<job_id>.jsonl`。可选 `max_steps`（默认 24）、`model`（覆盖设置中的模型）。
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

先 `status` / `list`，已有同类 watcher 就复用，不要对同一路径再开一个守护进程。改规则先读 `home/config.json` 再 `reload`；未运行则 `start --config` 该配置。不要对已有路径 `start --path`。

## 打包

skill 目录里的 `web/` 是未构建源码。分发前在本 skill 根目录执行：

```bash
python scripts/pack_skill.py
```

Windows 也可双击 `pack.cmd`。脚本会 `npm install` + `npm run build`，然后打出 `dist/file-watch-<版本>.zip`（不含 `node_modules`）。把 zip 解压到 `.cursor/skills/` 得到 `file-watch/`。已构建过、只想重新打 zip 时加 `--skip-build`。不要前端源码时加 `--no-web-src`。
