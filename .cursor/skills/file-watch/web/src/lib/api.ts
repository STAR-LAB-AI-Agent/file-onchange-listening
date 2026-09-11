export type FileEvent = {
  id?: string
  ts?: string
  type?: string
  path?: string
  old_path?: string
  is_dir?: boolean
}

export type NotifyAction = {
  title?: string
  message?: string
  webhook?: string | null
  mailbox?: boolean
}

export type AgentAction = {
  runner?: "command" | "cursor_sdk"
  prompt?: string
  command?: string[] | null
  cwd?: string | null
  timeout_seconds?: number
  model?: string | null
}

export type RuleThen = {
  notify?: NotifyAction
  agent?: AgentAction
}

export type RuleWhen = {
  types?: string[]
  glob?: string[]
  regex?: string | null
  is_dir?: boolean | null
  min_size_bytes?: number | null
  cooldown_seconds?: number
}

export type WatchRule = {
  name: string
  enabled?: boolean
  when?: RuleWhen
  then?: RuleThen[]
}

export type WatchConfig = {
  name?: string
  rules?: WatchRule[]
  watch?: {
    path?: string
    recursive?: boolean
    debounce_ms?: number
    ignore?: string[]
  }
}

export type WatcherInfo = {
  ok?: boolean
  watch_id?: string
  title?: string
  running?: boolean
  path?: string | null
  event_count?: number
  rule_count?: number
  rules?: string[]
  last_event?: FileEvent | null
  items?: FileEvent[]
  cursor?: number
  message?: string
  config?: WatchConfig
  notes?: string[]
  warnings?: string[]
  merged_rules?: WatchRule[]
  generated?: WatchRule[]
  mode?: string
}

export type GeneratedRulesResponse = Omit<WatcherInfo, "rules"> & {
  rules?: WatchRule[]
  merged_rules?: WatchRule[]
  generated?: WatchRule[]
}

export const TYPE_LABEL: Record<string, string> = {
  created: "新建",
  modified: "修改",
  deleted: "删除",
  moved: "移动",
}

export function blankRule(): WatchRule {
  return {
    name: "",
    enabled: true,
    when: {
      types: ["created", "modified"],
      glob: ["**/*"],
      regex: null,
      is_dir: false,
      min_size_bytes: null,
      cooldown_seconds: 0,
    },
    then: [
      {
        notify: {
          title: "文件有变化",
          message: "{{type}}: {{path}}",
          webhook: "",
          mailbox: true,
        },
      },
    ],
  }
}

export function relPath(path: string | undefined, root: string | undefined) {
  if (!path) return ""
  if (!root) return path
  const norm = (value: string) => value.replace(/\\/g, "/").replace(/\/+$/, "")
  const a = norm(path)
  const b = norm(root)
  if (a.toLowerCase().startsWith(`${b.toLowerCase()}/`)) return a.slice(b.length + 1)
  if (a.toLowerCase() === b.toLowerCase()) return "."
  return path
}

export function typeBadgeClass(type: string) {
  switch (type) {
    case "created":
      return "border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
    case "modified":
      return "border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-400"
    case "deleted":
      return "border-transparent bg-rose-500/15 text-rose-700 dark:text-rose-400"
    case "moved":
      return "border-transparent bg-violet-500/15 text-violet-700 dark:text-violet-400"
    default:
      return ""
  }
}

export class ApiError extends Error {
  readonly code?: string

  constructor(message: string, code?: string) {
    super(message)
    this.name = "ApiError"
    this.code = code
  }
}

export async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)
  const data = (await response.json()) as T & { ok?: boolean; message?: string; error?: string }
  if (!response.ok || data.ok === false) {
    throw new ApiError(data.message || `请求失败 ${response.status}`, data.error)
  }
  return data
}

export function navigate(to: string) {
  window.history.pushState({}, "", to)
  window.dispatchEvent(new PopStateEvent("popstate"))
}

export type TaskPage = "events" | "rules"

export type AppRoute =
  | { kind: "list" }
  | { kind: "settings" }
  | { kind: "task"; watchId: string; page: TaskPage }

export function parseTaskRoute(pathname: string): { watchId: string; page: TaskPage } | null {
  const match = pathname.match(/^\/tasks\/([^/]+)(?:\/(rules))?\/?$/)
  if (!match) return null
  return {
    watchId: decodeURIComponent(match[1]),
    page: match[2] === "rules" ? "rules" : "events",
  }
}

export function parseAppRoute(pathname: string): AppRoute {
  const clean = pathname.replace(/\/+$/, "") || "/"
  if (clean === "/settings") return { kind: "settings" }
  const task = parseTaskRoute(pathname)
  if (task) return { kind: "task", watchId: task.watchId, page: task.page }
  return { kind: "list" }
}

export type LlmSettings = {
  base_url?: string
  model?: string
  api_key_set?: boolean
  api_key_masked?: string
}

