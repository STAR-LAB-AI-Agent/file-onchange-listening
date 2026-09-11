# 更新日志

本文件记录面向用户的变更。初始版本 **1.0.0**；小修改每次 +0.0.1；其余情况由用户指定版本。

## 1.0.0 - 2026-09-11

首个正式版本。

- 用 watchdog 监听目录的新建、修改、删除、移动。
- 以 Cursor skill + `scripts/filewatch_cli.py` 对外提供 CLI，skill 目录可单独拷贝安装。
- YAML 规则命中后写入 jobs 邮箱、可选 webhook，或用 `command` / `cursor_sdk` 启动智能体。
- 支持 `start` / `stop` / `wait` / `drain` / `ack`；stdout 为 JSON。
- 按路径去抖合并事件；忽略 `.git`、`*.tmp` 等默认模式。
- 附带 `scripts/test_watch_dir.py` 实测脚本。
- 文档改为中文。
