import { useCallback, useEffect, useRef, useState } from "react"
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react"

import { LiveLogPanel } from "@/components/LiveLogPanel"
import { TaskChrome } from "@/components/TaskChrome"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  agentPrompt,
  api,
  formatActive,
  formatEventTime,
  hasAgentPrompt,
  navigate,
  relPath,
  TYPE_LABEL,
  typeBadgeClass,
  type AgentLogEvent,
  type AgentLogJob,
  type AgentLogPage,
  type AgentLogStat,
  type WatcherInfo,
} from "@/lib/api"

const LOG_PAGE = 100

function runStatusLabel(stat?: AgentLogStat | null, fallbackRunning?: boolean | null) {
  if (stat?.running || fallbackRunning) return "运行中"
  if (stat?.last_status === "ok") return "已完成"
  if (stat?.last_status && stat.last_status !== "unknown") return "失败"
  if ((stat?.run_count || 0) > 0) return "已执行"
  return "尚未执行"
}

export function TaskAgent({ watchId, ruleName }: { watchId: string; ruleName?: string }) {
  const [info, setInfo] = useState<WatcherInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)

  const loadWatcher = useCallback(async () => {
    const data = await api<WatcherInfo>(`/api/watchers/${encodeURIComponent(watchId)}/config`)
    setInfo(data)
    return data
  }, [watchId])

  useEffect(() => {
    let cancelled = false
    void loadWatcher().catch((err: unknown) => {
      if (!cancelled) setError(err instanceof Error ? err.message : "无法加载任务")
    })
    return () => {
      cancelled = true
    }
  }, [loadWatcher])

  async function startWatch() {
    if (!info?.path) return
    setStarting(true)
    setError(null)
    try {
      await api("/api/watchers/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: info.path, recursive: true }),
      })
      await loadWatcher()
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动失败")
    } finally {
      setStarting(false)
    }
  }

  async function stopWatch() {
    setStopping(true)
    try {
      await api(`/api/watchers/${encodeURIComponent(watchId)}/stop`, { method: "POST" })
      await loadWatcher()
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止失败")
    } finally {
      setStopping(false)
    }
  }

  return (
    <TaskChrome
      watchId={watchId}
      info={info}
      page="agent"
      error={error}
      starting={starting}
      stopping={stopping}
      onStart={() => void startWatch()}
      onStop={() => void stopWatch()}
      onRenamed={(data) => setInfo((current) => ({ ...current, ...data }))}
      onRenameError={setError}
    >
      {ruleName ? (
        <AgentLogDetail
          watchId={watchId}
          ruleName={ruleName}
          info={info}
          onError={setError}
        />
      ) : (
        <AgentRuleList watchId={watchId} info={info} onError={setError} />
      )}
    </TaskChrome>
  )
}

function AgentRuleList({
  watchId,
  info,
  onError,
}: {
  watchId: string
  info: WatcherInfo | null
  onError: (message: string | null) => void
}) {
  const [stats, setStats] = useState<AgentLogStat[]>([])
  const [statsReady, setStatsReady] = useState(false)
  const rules = (info?.config?.rules || []).filter(hasAgentPrompt)
  const byRule = new Map(stats.map((item) => [item.rule || "", item]))

  const loadStats = useCallback(async () => {
    const data = await api<AgentLogPage>(
      `/api/watchers/${encodeURIComponent(watchId)}/agent-logs?summary=1`,
    )
    setStats(data.stats || [])
    setStatsReady(true)
  }, [watchId])

  useEffect(() => {
    let cancelled = false
    void loadStats()
      .then(() => {
        if (!cancelled) onError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) onError(err instanceof Error ? err.message : "无法加载智能体日志")
      })
    const timer = window.setInterval(() => {
      void loadStats().catch(() => undefined)
    }, 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [loadStats, onError])

  return (
    <Card size="sm">
      <CardHeader className="border-b">
        <CardTitle>智能体规则</CardTitle>
        <CardDescription>
          只列出填写了任务要求的规则。点进去查看该规则的实时执行轮次。
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {rules.length === 0 ? (
          <div className="px-4 py-16 text-center text-sm text-muted-foreground">
            还没有填写任务要求的规则。请到「监听规则」添加任务要求后，再回这里看执行日志。
          </div>
        ) : (
          <div className="divide-y">
            {rules.map((rule, index) => {
              const stat = byRule.get(rule.name)
              const prompt = agentPrompt(rule)
              const activeLabel = formatActive(rule.when?.active)
              return (
                <button
                  key={`${rule.name}-${index}`}
                  type="button"
                  className="flex w-full flex-col gap-2 px-4 py-3 text-left hover:bg-muted/50 sm:flex-row sm:items-center sm:justify-between"
                  onClick={() =>
                    navigate(`/tasks/${encodeURIComponent(watchId)}/agent/${encodeURIComponent(rule.name)}`)
                  }
                >
                  <div className="min-w-0 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{rule.name}</span>
                      {statsReady ? (
                        <Badge variant={stat?.running ? "default" : "secondary"}>
                          {runStatusLabel(stat)}
                        </Badge>
                      ) : null}
                      {stat?.run_count ? (
                        <Badge variant="outline">{stat.run_count} 轮</Badge>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {(rule.when?.types || []).map((type) => (
                        <Badge key={type} variant="outline" className={typeBadgeClass(type)}>
                          {TYPE_LABEL[type] || type}
                        </Badge>
                      ))}
                    </div>
                    <div className="font-mono text-xs break-all text-muted-foreground">
                      {(rule.when?.glob || []).join(", ") || "匹配全部路径"}
                      {activeLabel ? ` · ${activeLabel}` : ""}
                    </div>
                    {prompt ? (
                      <div className="line-clamp-2 text-xs text-muted-foreground">{prompt}</div>
                    ) : null}
                    {stat?.last_path ? (
                      <div className="font-mono text-[11px] text-muted-foreground">
                        最近 {relPath(stat.last_path, info?.path || undefined)}
                        {stat.last_ts ? ` · ${formatEventTime(stat.last_ts)}` : ""}
                      </div>
                    ) : null}
                  </div>
                  <ChevronRightIcon className="mt-1 size-4 shrink-0 text-muted-foreground" />
                </button>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function AgentLogDetail({
  watchId,
  ruleName,
  info,
  onError,
}: {
  watchId: string
  ruleName: string
  info: WatcherInfo | null
  onError: (message: string | null) => void
}) {
  const [events, setEvents] = useState<AgentLogEvent[]>([])
  const [job, setJob] = useState<AgentLogJob | null>(null)
  const [hasOlder, setHasOlder] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [streamFrom, setStreamFrom] = useState<number | null>(null)
  const [logSession, setLogSession] = useState<number | null>(null)
  const [displaySession, setDisplaySession] = useState(1)
  const [sessionCount, setSessionCount] = useState(1)
  const [running, setRunning] = useState<boolean | null>(null)
  const oldestRef = useRef(0)
  const fileEndRef = useRef(0)
  const loadingOlderRef = useRef(false)
  const atTopRef = useRef(false)
  const followLiveRef = useRef(true)
  const displaySessionRef = useRef(1)
  const sessionCountRef = useRef(1)
  const rule = (info?.config?.rules || []).find((item) => item.name === ruleName)
  const prompt = agentPrompt(rule)

  useEffect(() => {
    fileEndRef.current = 0
    oldestRef.current = 0
    followLiveRef.current = true
    displaySessionRef.current = 1
    sessionCountRef.current = 1
    setStreamFrom(null)
    setEvents([])
    setJob(null)
    setHasOlder(false)
    setLogSession(null)
    setDisplaySession(1)
    setSessionCount(1)
    setRunning(null)
  }, [watchId, ruleName])

  useEffect(() => {
    let alive = true
    oldestRef.current = 0
    setHasOlder(false)
    setEvents([])
    const params = new URLSearchParams({ tail: "1", limit: String(LOG_PAGE), rule: ruleName })
    if (logSession != null) params.set("session", String(logSession))
    void api<AgentLogPage>(`/api/watchers/${encodeURIComponent(watchId)}/agent-logs?${params.toString()}`)
      .then((data) => {
        if (!alive) return
        setEvents(data.events || [])
        setJob(data.job || null)
        oldestRef.current = data.oldest || 0
        setHasOlder(Boolean(data.has_older))
        fileEndRef.current = data.file_end || 0
        setStreamFrom(data.file_end ?? 0)
        const count = data.session_count || 0
        const sess = data.session || 1
        sessionCountRef.current = Math.max(1, count)
        displaySessionRef.current = sess
        setSessionCount(sessionCountRef.current)
        setDisplaySession(sess)
        setRunning(Boolean(data.running))
        onError(null)
      })
      .catch((err: unknown) => {
        if (!alive) return
        onError(err instanceof Error ? err.message : "无法加载智能体日志")
      })
    return () => {
      alive = false
    }
  }, [watchId, ruleName, logSession, onError])

  useEffect(() => {
    if (streamFrom == null) return
    let mounted = true
    let source: EventSource | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let backoffMs = 800

    const connect = () => {
      source?.close()
      const from = Math.max(fileEndRef.current, streamFrom)
      const params = new URLSearchParams({ from_offset: String(from), rule: ruleName })
      if (logSession != null) params.set("session", String(logSession))
      source = new EventSource(`/api/watchers/${encodeURIComponent(watchId)}/agent-logs/stream?${params.toString()}`)
      source.onmessage = (event) => {
        if (!mounted) return
        backoffMs = 800
        let data: Record<string, unknown>
        try {
          data = JSON.parse(event.data)
        } catch {
          return
        }
        if (data.type === "status") {
          const nextRunning = typeof data.running === "boolean" ? data.running : undefined
          const nextCount = typeof data.session_count === "number" ? data.session_count : undefined
          const nextSession = typeof data.session === "number" ? data.session : undefined
          if (nextRunning != null) setRunning(nextRunning)
          if (nextCount != null) {
            sessionCountRef.current = Math.max(1, nextCount)
            setSessionCount(sessionCountRef.current)
          }
          if (nextSession != null && followLiveRef.current && logSession == null) {
            if (nextSession !== displaySessionRef.current) {
              displaySessionRef.current = nextSession
              setDisplaySession(nextSession)
              oldestRef.current = 0
              fileEndRef.current = 0
              setEvents([])
              setHasOlder(false)
            }
          }
          return
        }
        if (data.type === "event" || data.kind) {
          const { type: _t, ...ev } = data
          if (!ev.kind) return
          const seq = typeof ev.seq === "number" ? ev.seq : undefined
          if (seq != null) fileEndRef.current = Math.max(fileEndRef.current, seq + 1)
          const evSession = typeof ev.session === "number" ? ev.session : undefined
          const started = evSession != null && evSession > sessionCountRef.current
          if (started) {
            const next = evSession
            sessionCountRef.current = Math.max(sessionCountRef.current, next)
            setSessionCount(sessionCountRef.current)
            if (followLiveRef.current) {
              displaySessionRef.current = next
              setDisplaySession(next)
              oldestRef.current = seq ?? 0
              setHasOlder(false)
              setEvents([ev as AgentLogEvent])
              setRunning(true)
              return
            }
          }
          if (evSession != null && evSession !== displaySessionRef.current) return
          if (seq != null && oldestRef.current > 0 && seq < oldestRef.current) return
          setEvents((prev) => {
            if (seq != null && prev.some((x) => x.seq === seq)) return prev
            return [...prev, ev as AgentLogEvent]
          })
        }
      }
      source.onerror = () => {
        source?.close()
        if (mounted) scheduleReconnect()
      }
    }

    const scheduleReconnect = () => {
      if (!mounted || reconnectTimer) return
      const wait = backoffMs
      backoffMs = Math.min(Math.round(backoffMs * 1.8), 8000)
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        if (mounted) connect()
      }, wait)
    }

    const start = window.setTimeout(connect, 0)
    return () => {
      mounted = false
      window.clearTimeout(start)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      source?.close()
    }
  }, [watchId, ruleName, streamFrom, logSession])

  const loadOlder = () => {
    if (loadingOlderRef.current || !hasOlder) return
    loadingOlderRef.current = true
    setLoadingOlder(true)
    const before = oldestRef.current
    const params = new URLSearchParams({
      before: String(before),
      limit: String(LOG_PAGE),
      rule: ruleName,
      session: String(logSession ?? displaySession),
    })
    void api<AgentLogPage>(`/api/watchers/${encodeURIComponent(watchId)}/agent-logs?${params.toString()}`)
      .then((data) => {
        if (!atTopRef.current) return
        setEvents((prev) => {
          const seen = new Set(prev.map((e) => e.seq).filter((x): x is number => x != null))
          const older = (data.events || []).filter((e) => e.seq == null || !seen.has(e.seq))
          return [...older, ...prev]
        })
        oldestRef.current = data.oldest || oldestRef.current
        setHasOlder(Boolean(data.has_older))
      })
      .catch(() => undefined)
      .finally(() => {
        loadingOlderRef.current = false
        setLoadingOlder(false)
      })
  }

  const jobPath = relPath(job?.path || undefined, info?.path || undefined)
  const jobTime = formatEventTime(job?.ts || undefined)

  return (
    <Card size="sm">
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/tasks/${encodeURIComponent(watchId)}/agent`)}
          >
            <ChevronLeftIcon data-icon="inline-start" />
            返回规则
          </Button>
        </div>
        <CardTitle>{ruleName}</CardTitle>
        <CardDescription>
          该规则的内置智能体执行轮次。最新一轮会通过 SSE 实时追加。
        </CardDescription>
        {prompt ? <p className="col-span-full text-xs text-muted-foreground">{prompt}</p> : null}
        {job ? (
          <div className="col-span-full flex flex-wrap items-center gap-2 pt-1 text-xs text-muted-foreground">
            {job.status && job.status !== "unknown" ? (
              <Badge variant={job.status === "running" || running ? "default" : "secondary"}>
                {running || job.status === "running" ? "运行中" : job.status === "ok" ? "已完成" : "失败"}
              </Badge>
            ) : null}
            {jobPath ? <span className="font-mono">{jobPath}</span> : null}
            {jobTime ? <span>{jobTime}</span> : null}
          </div>
        ) : null}
      </CardHeader>
      <CardContent className="pt-4">
        <LiveLogPanel
          events={events}
          hasOlder={hasOlder}
          loadingOlder={loadingOlder}
          onLoadOlder={loadOlder}
          atTopRef={atTopRef}
          session={displaySession}
          sessionCount={Math.max(1, sessionCount)}
          running={sessionCount === 0 ? false : running}
          emptyHint="该规则还没有执行记录。命中文件变化后会在这里显示工作流。"
          onSessionChange={(next) => {
            followLiveRef.current = next == null
            setLogSession(next)
          }}
        />
      </CardContent>
    </Card>
  )
}
