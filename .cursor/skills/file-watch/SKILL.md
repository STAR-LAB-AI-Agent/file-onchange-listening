---
name: file-watch
description: >-
  监听指定文件夹的新建、修改、删除、移动事件，按预设规则发送通知或启动智能体任务。
  在用户用自然语言制定或修改监听规则、要求监听目录、等待新文件、启停 filewatch，
  打开事件网页，或按文件变化条件触发任务时使用。把口语写成 YAML，validate 校验后再 reload 热更新。
---

# 文件监听

版本 **1.1.0**。

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

用户用口语描述监听条件时，**由当前对话 Agent 写成 YAML**，不要让用户手写，也不要现场生成 watcher。

流程固定为：

```text
1. 把自然语言落到 watch.yaml 的 rules（可改已有文件，不要另起一套）
2. python scripts/filewatch_cli.py validate --config watch.yaml
3. ok: false → 根据 message 改 YAML，再 validate，不要 reload
4. list / status
   - 未运行 → start --config watch.yaml
   - 已运行 → reload --config watch.yaml [--id <watch_id>]
5. 向用户确认已生效的规则名
```

热更新只换规则、忽略列表和去抖间隔。`watch.path` 或 `recursive` 变了会返回 `needs_restart`：先 `stop` 再 `start`。已在运行时不要再 `start`（不会应用新配置）。

写规则时：

- 递归匹配用 `**/*.md`，不要只写 `*.md`。
- `when.types` 只能是 `created` / `modified` / `deleted` / `moved`。
- `then` 每项只能是 `notify` 或 `agent` 之一。
- 模板变量只能用 `{{path}}` `{{filename}}` `{{type}}` `{{watch_id}}` `{{ts}}` `{{old_path}}` `{{json}}` `{{rule}}`。
- 用户没说启动智能体时，默认只写 `notify`（写入 jobs 邮箱）。
- 热更新时保留原来的 `watch.path` / `recursive`，除非用户明确要改监听目录。

## 流程

1. 编写或修改 `watch.yaml`，填好 `watch.path` 和 `rules`。示例见 `examples/watch.yaml`。
2. `python scripts/filewatch_cli.py validate --config examples/watch.yaml` 检查语法。
3. `python scripts/filewatch_cli.py test-rule --config examples/watch.yaml --path <file> --type created` 确认规则能命中。
4. 未运行则 `start --config examples/watch.yaml`；已运行则 `reload --config examples/watch.yaml`。
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
python scripts/filewatch_cli.py status --id inbox
python scripts/filewatch_cli.py wait --id inbox --stream jobs --timeout 30
python scripts/filewatch_cli.py drain --id inbox --stream events
python scripts/filewatch_cli.py ack --id inbox --stream jobs --cursor 128
python scripts/filewatch_cli.py stop --id inbox
python scripts/filewatch_cli.py list
python scripts/filewatch_cli.py serve --port 8765
```

`wait` 会阻塞到有数据或超时。优先用它，不要 sleep 再 drain。

## 网页

在本机打开任务面板。首页按监听目录列出任务；详情分「文件变化」和「监听规则」：

- 文件变化：该目录的新建 / 修改 / 删除 / 移动
- 监听规则：手动添加，或用自然语言生成（调用 LLM；也可粘贴 YAML/JSON，不经模型）。已运行则热更新，未运行则写入配置等下次 start
- 设置：`/settings` 填写兼容 OpenAI 的 `base_url` / `model` / API Key。Key 写入 `%LOCALAPPDATA%/filewatch/settings.json`（或 `$FILEWATCH_HOME`），不要放进被监听目录。也可用环境变量 `FILEWATCH_LLM_API_KEY`、`FILEWATCH_LLM_BASE_URL`、`FILEWATCH_LLM_MODEL`

```bash
python scripts/filewatch_cli.py serve --port 8765
```

浏览器访问 JSON 里的 `url`（默认 `http://127.0.0.1:8765/`）。可同时添加多个目录；同一路径会复用已有任务。默认只绑定本机回环地址。加 `--open` 可自动打开浏览器。改前端源码在 `web/`，构建：`npm run build`（产物在 `scripts/filewatch/webui/`）。

`serve` 启动时 stdout 仍只打一行 JSON，随后进程占用前台直到 Ctrl+C。日志走 stderr。

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
          webhook: "https://example.invalid/hook"   # 可选
      - agent:
          runner: command
          command: ["python", "scripts/echo_agent.py"]
          prompt: |
            文件事件 {{type}}：{{path}}
            请处理该文件。
          timeout_seconds: 600
```

`when` 字段：`types`、`glob`（字符串或列表）、`regex`、`is_dir`、`min_size_bytes`、`cooldown_seconds`。

`then` 动作：

- `notify`：一律写入 `jobs` 流；可选 `webhook` POST。
- `agent.runner: command`：执行 argv。prompt 走 stdin，同时设置 `FILEWATCH_PROMPT` 和 `FILEWATCH_EVENT_JSON`。
- `agent.runner: cursor_sdk`：需要 `cursor-sdk` 和 `CURSOR_API_KEY`。会启动**一次新的**智能体 run，不会唤醒当前对话。

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

先 `status` / `list`，已有同类 watcher 就复用，不要对同一路径再开一个守护进程。改规则用 `reload`，不要再 `start`。

## 打包

skill 目录里的 `web/` 是未构建源码。分发前在本 skill 根目录执行：

```bash
python scripts/pack_skill.py
```

Windows 也可双击 `pack.cmd`。脚本会 `npm install` + `npm run build`，然后打出 `dist/file-watch-<版本>.zip`（不含 `node_modules`）。把 zip 解压到 `.cursor/skills/` 得到 `file-watch/`。已构建过、只想重新打 zip 时加 `--skip-build`。不要前端源码时加 `--no-web-src`。
