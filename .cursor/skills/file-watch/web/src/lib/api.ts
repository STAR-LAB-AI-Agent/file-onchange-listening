export type LineChangeRow = {
  op: "add" | "del" | string
  line: number
  text?: string
}

export type LineChanges = {
  kind?: "text" | "skipped" | "pending" | string
  encoding?: string
  added?: number
  removed?: number
  truncated?: boolean
  reason?: string
  changes?: LineChangeRow[]
}

export type FileEvent = {
  id?: string
  ts?: string
  type?: string
  path?: string
  old_path?: string
  is_dir?: boolean
  line_changes?: LineChanges | null
}

export type DingTalkAction = {
  channel?: string | null
  webhook?: string | null
  secret?: string | null
  interval_seconds?: number
}

export type NotifyAction = {
  title?: string
  message?: string
  webhook?: string | null
  mailbox?: boolean
  dingtalk?: DingTalkAction | string | boolean | null
}

export type AgentAction = {
  runner?: "command" | "cursor_sdk" | "builtin"
  prompt?: string
  command?: string[] | null
  cwd?: string | null
  timeout_seconds?: number
  model?: string | null
  max_steps?: number
}

export type RuleThen = {
  notify?: NotifyAction
  agent?: AgentAction
}

export type RuleActive = {
  start?: string | null
  end?: string | null
  days?: string[]
}

export type RuleWhen = {
  types?: string[]
  glob?: string[]
  regex?: string | null
  is_dir?: boolean | null
  min_size_bytes?: number | null
  cooldown_seconds?: number
  active?: RuleActive | string | null
}

export type WatchRule = {
  name: string
  enabled?: boolean
  exclude?: boolean
  when?: RuleWhen
  then?: RuleThen[]
}

export type WatchConfig = {
  name?: string
  rules?: WatchRule[]
  watch?: {
    path?: string
    recursive?: boolean
    record_all?: boolean
    debounce_ms?: number
    line_diff_quiet_ms?: number
    line_diff_max_bytes?: number
    ignore?: string[]
  }
}

export type WatcherInfo = {
  ok?: boolean
  watch_id?: string
  title?: string
  running?: boolean
  path?: string | null
  recursive?: boolean
  record_all?: boolean
  event_count?: number
  rule_count?: number
  rules?: string[]
  last_event?: FileEvent | null
  items?: FileEvent[]
  cursor?: number
  page?: number
  page_size?: number
  pages?: number
  total?: number
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
  index?: number
  rule?: WatchRule
}

export const TYPE_LABEL: Record<string, string> = {
  created: "新建",
  modified: "修改",
  deleted: "删除",
  moved: "移动",
}

export const WEEKDAY_IDS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const

export const WEEKDAY_LABEL: Record<(typeof WEEKDAY_IDS)[number], string> = {
  mon: "一",
  tue: "二",
  wed: "三",
  thu: "四",
  fri: "五",
  sat: "六",
  sun: "日",
}

function timeInputValue(value?: string | null): string {
  if (!value) return ""
  const match = value.trim().match(/^(\d{1,2}):([0-5]\d)/)
  if (!match) return ""
  return `${match[1].padStart(2, "0")}:${match[2]}`
}

export function normalizeActive(raw: RuleWhen["active"] | undefined): RuleActive | null {
  if (raw == null || raw === "") return null
  if (typeof raw === "string") {
    const parts = raw.split("-")
    if (parts.length < 2) return null
    const start = timeInputValue(parts[0])
    const end = timeInputValue(parts.slice(1).join("-")) || (parts[1]?.trim() === "24:00" ? "24:00" : "")
    if (!start && !end) return null
    return { start: start || null, end: end || null, days: [] }
  }
  const start = timeInputValue(raw.start)
  const end = raw.end?.trim() === "24:00" ? "24:00" : timeInputValue(raw.end)
  const days = (raw.days || []).filter((day): day is (typeof WEEKDAY_IDS)[number] =>
    (WEEKDAY_IDS as readonly string[]).includes(day),
  )
  if (!start && !end && days.length === 0) return null
  return { start: start || null, end: end || null, days }
}

export function formatActive(raw: RuleWhen["active"] | undefined): string {
  const active = normalizeActive(raw)
  if (!active) return ""
  const selected = new Set(active.days || [])
  const dayText =
    selected.size === 0 || selected.size === 7
      ? ""
      : WEEKDAY_IDS.filter((day) => selected.has(day))
          .map((day) => `周${WEEKDAY_LABEL[day]}`)
          .join("、")
  const hasTime = Boolean(active.start || active.end)
  const timeText = hasTime ? `${active.start || "00:00"}–${active.end || "24:00"}` : "全天"
  if (dayText && hasTime) return `${dayText} ${timeText}`
  return dayText || timeText
}

export function blankRule(exclude = false): WatchRule {
  if (exclude) {
    return {
      name: "",
      enabled: true,
      exclude: true,
      when: {
        types: ["created", "modified", "deleted", "moved"],
        glob: [],
        regex: null,
        is_dir: false,
        min_size_bytes: null,
        cooldown_seconds: 0,
        active: null,
      },
      then: [],
    }
  }
  return {
    name: "",
    enabled: true,
    exclude: false,
    when: {
      types: ["created", "modified"],
      glob: ["**/*"],
      regex: null,
      is_dir: false,
      min_size_bytes: null,
      cooldown_seconds: 0,
      active: null,
    },
    then: [
      {
        notify: {
          title: "文件有变化",
          message: "{{type}}: {{path}}",
          webhook: "",
          mailbox: true,
          dingtalk: null,
        },
      },
    ],
  }
}

const CST_FORMAT = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
})

export function formatEventTime(ts: string | undefined) {
  if (!ts) return ""
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return ts
  return CST_FORMAT.format(date)
}

export function defaultTaskTitle(path?: string | null, fallback = "") {
  if (!path) return fallback
  const trimmed = path.replace(/[\\/]+$/, "")
  const parts = trimmed.split(/[/\\]/)
  return parts[parts.length - 1] || fallback
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

export type TaskPage = "events" | "rules" | "agent"

export type AgentLogEvent = {
  kind: string
  seq?: number
  session?: number
  job_id?: string
  ts?: string
  text?: string | null
  source?: string
  command?: string
  output?: string
  exit_code?: number
  tool?: string
  role?: string
  traceback?: string
  duration_ms?: number
  input?: number
  output_tokens?: number
  cached?: number
  total?: number
  session_start?: boolean
}

export type AgentLogJob = {
  job_id?: string
  session?: number
  status?: string
  rule?: string | null
  path?: string | null
  type?: string | null
  ts?: string | null
}

export type AgentLogStat = {
  rule?: string
  run_count?: number
  running?: boolean
  last_status?: string | null
  last_ts?: string | null
  last_path?: string | null
}

export type AgentLogPage = {
  ok?: boolean
  events?: AgentLogEvent[]
  session?: number
  session_count?: number
  job?: AgentLogJob | null
  running?: boolean
  offset?: number
  oldest?: number
  has_older?: boolean
  total?: number
  file_end?: number
  watch_id?: string
  rule?: string | null
  stats?: AgentLogStat[]
}

export type TaskRoute = { watchId: string; page: TaskPage; ruleName?: string }

export type AppRoute =
  | { kind: "list" }
  | { kind: "settings" }
  | { kind: "task"; watchId: string; page: TaskPage; ruleName?: string }

export function parseTaskRoute(pathname: string): TaskRoute | null {
  const agent = pathname.match(/^\/tasks\/([^/]+)\/agent(?:\/([^/]+))?\/?$/)
  if (agent) {
    return {
      watchId: decodeURIComponent(agent[1]),
      page: "agent",
      ruleName: agent[2] ? decodeURIComponent(agent[2]) : undefined,
    }
  }
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
  if (task) return { kind: "task", watchId: task.watchId, page: task.page, ruleName: task.ruleName }
  return { kind: "list" }
}

export function agentPrompt(rule: WatchRule | null | undefined): string {
  if (!rule || rule.exclude) return ""
  for (const action of rule.then || []) {
    const prompt = action.agent?.prompt?.trim()
    if (prompt) return prompt
  }
  return ""
}

export function hasAgentPrompt(rule: WatchRule | null | undefined): boolean {
  return Boolean(agentPrompt(rule))
}

export type LlmWireApi = "chat" | "responses" | "anthropic"

export type LlmSettings = {
  base_url?: string
  model?: string
  wire_api?: LlmWireApi
  api_key_set?: boolean
  api_key_masked?: string
}

export type DingTalkChannel = {
  id: string
  name: string
  webhook?: string
  secret_set?: boolean
  secret_masked?: string
  interval_seconds?: number
}

export type WatchTimingSettings = {
  debounce_ms?: number
  line_diff_quiet_ms?: number
  line_diff_max_bytes?: number
}

export type AppSettings = {
  llm: LlmSettings
  dingtalk?: { channels?: DingTalkChannel[] }
  watch?: WatchTimingSettings
}

export function dingtalkSelection(ding: NotifyAction["dingtalk"] | undefined): string {
  if (ding == null || ding === false) return ""
  if (ding === true) return "*"
  if (typeof ding === "string") {
    const text = ding.trim()
    if (!text || text === "false") return ""
    if (text === "true" || text === "default" || text === "*") return "*"
    return text
  }
  if (ding.webhook) return "__legacy__"
  if (ding.channel) return ding.channel
  return ""
}

export function hasDingtalk(notify?: NotifyAction | null): boolean {
  return dingtalkSelection(notify?.dingtalk) !== ""
}

