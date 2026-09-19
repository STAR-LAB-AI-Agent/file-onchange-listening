import { useEffect, useLayoutEffect, useMemo, useRef, useState, type MutableRefObject, type WheelEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { AgentLogEvent } from "@/lib/api"

const REVEAL_LIMIT = 100

type Props = {
  events: AgentLogEvent[]
  minHeight?: number
  autoScroll?: boolean
  hasOlder?: boolean
  loadingOlder?: boolean
  onLoadOlder?: () => void
  atTopRef?: MutableRefObject<boolean>
  session?: number
  sessionCount?: number
  onSessionChange?: (session: number | null) => void
  running?: boolean | null
  emptyHint?: string
}

function LogLine({ ev }: { ev: AgentLogEvent }) {
  const [expanded, setExpanded] = useState(false)
  const k = ev.kind
  let body = ""
  let collapsible = false
  let tag = k

  if (k === "agent" || k === "reasoning") {
    collapsible = true
    body = ev.text || ""
    if (!body.trim()) return null
  } else if (k === "cmd") {
    collapsible = true
    tag = ev.tool || "cmd"
    body =
      "$ " +
      (ev.command || "") +
      (ev.output ? "\n" + ev.output : "") +
      (ev.exit_code != null ? `\n[exit ${ev.exit_code}]` : "")
  } else if (k === "tool_exec_error") {
    collapsible = true
    tag = ev.tool || "tool_exec_error"
    body =
      (ev.command ? `$ ${ev.command}\n` : "") +
      (ev.text || ev.output || "工具执行失败") +
      (ev.traceback ? `\n${ev.traceback}` : "")
  } else if (k === "tokens") {
    const cached = Number(ev.cached) || 0
    body =
      `tokens: ${ev.total ?? 0} (in ${ev.input ?? 0} / out ${ev.output_tokens ?? 0}` +
      (cached > 0 ? ` / cache ${cached}` : "") +
      ")"
  } else if (k === "error") {
    body = ev.text || ""
  } else if (k === "system") {
    tag = ev.source || "system"
    body = ev.text || ""
  } else {
    body = ev.text || JSON.stringify(ev)
  }

  const shown =
    expanded ? body : k === "cmd" || k === "tool_exec_error" ? `$ ${ev.command || ""}` : body
  const hidden =
    k === "cmd" || k === "tool_exec_error"
      ? (ev.output || ev.text ? String(ev.output || ev.text).split("\n").length : 0) +
        (ev.exit_code != null ? 1 : 0)
      : Math.max(0, body.split("\n").length - 1)
  const tagClass =
    "fw-tag " +
    (k === "system" && ev.source === "user"
      ? "user"
      : k === "cmd"
        ? "cmd"
        : k === "tool_exec_error"
          ? "error"
          : k)
  const label = ev.role || ""

  return (
    <div className={"fw-log-line" + (collapsible ? " collapsible" + (expanded ? " expanded" : "") : "")}>
      {ev.ts ? <span className="fw-log-ts">{ev.ts}</span> : null}
      <span className={tagClass} onClick={collapsible ? () => setExpanded((x) => !x) : undefined}>
        {tag}
      </span>
      {label ? <span className="fw-log-phase">{label}</span> : null}
      <span
        className={
          "fw-log-body" +
          (k === "cmd" || k === "tool_exec_error" ? " cmd-text" : "") +
          (k === "error" || k === "tool_exec_error" ? " error-text" : "")
        }
        onClick={collapsible && !expanded ? () => setExpanded(true) : undefined}
      >
        {shown}
      </span>
      {collapsible ? (
        <>
          {!expanded && hidden > 0 ? <span className="fw-line-hint">隐藏 {hidden} 行</span> : null}
          <span className="fw-caret" onClick={() => setExpanded((x) => !x)}>
            {expanded ? "▾" : "▸"}
          </span>
        </>
      ) : null}
    </div>
  )
}

function windowSlice(
  list: AgentLogEvent[],
  limit: number,
  following: boolean,
  headSeq?: number,
): AgentLogEvent[] {
  if (list.length <= limit) return list
  if (following || headSeq == null) return list.slice(-limit)
  const i = list.findIndex((e) => e.seq === headSeq)
  if (i <= 0) return list.slice(0, limit)
  return list.slice(i, i + limit)
}

export function LiveLogPanel({
  events,
  minHeight = 360,
  autoScroll = true,
  hasOlder = false,
  loadingOlder = false,
  onLoadOlder,
  atTopRef,
  session = 1,
  sessionCount = 1,
  onSessionChange,
  running = null,
  emptyHint = "暂无智能体日志。规则填写任务要求后，命中文件变化即会在这里显示工作流。",
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const atBottomRef = useRef(true)
  const prevFirstSeq = useRef<number | undefined>(undefined)
  const prevLastSeq = useRef<number | undefined>(undefined)
  const prevHeight = useRef(0)
  const savedScrollTop = useRef(0)
  const ignoreScrollRef = useRef(false)
  const lastUserLoadAt = useRef(0)
  const [following, setFollowing] = useState(true)
  const [headSeq, setHeadSeq] = useState<number | undefined>(undefined)
  const [showJump, setShowJump] = useState(false)
  const [draft, setDraft] = useState(String(session))
  const [editing, setEditing] = useState(false)
  const skipBlurCommit = useRef(false)

  const visible = useMemo(
    () => windowSlice(events, REVEAL_LIMIT, following, headSeq),
    [events, following, headSeq],
  )
  const moreHidden = events.length > visible.length || hasOlder

  useLayoutEffect(() => {
    prevFirstSeq.current = undefined
    prevLastSeq.current = undefined
    prevHeight.current = 0
    atBottomRef.current = true
    if (atTopRef) atTopRef.current = false
    setFollowing(true)
    setHeadSeq(undefined)
  }, [session, atTopRef])

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const firstSeq = visible[0]?.seq
    const lastSeq = visible[visible.length - 1]?.seq
    const prepended =
      prevFirstSeq.current != null &&
      firstSeq != null &&
      firstSeq < prevFirstSeq.current &&
      lastSeq === prevLastSeq.current
    ignoreScrollRef.current = true
    if (prepended) {
      const delta = el.scrollHeight - prevHeight.current
      if (following || atBottomRef.current) {
        el.scrollTop = el.scrollHeight
      } else {
        el.scrollTop = savedScrollTop.current + delta
      }
    } else if (autoScroll && (following || atBottomRef.current)) {
      el.scrollTop = el.scrollHeight
    }
    prevFirstSeq.current = firstSeq
    prevLastSeq.current = lastSeq
    prevHeight.current = el.scrollHeight
    const timer = window.setTimeout(() => {
      ignoreScrollRef.current = false
    }, 80)
    return () => window.clearTimeout(timer)
  }, [visible, autoScroll, following])

  useEffect(() => {
    if (!editing) setDraft(String(session))
  }, [session, editing])

  const requestOlder = () => {
    if (!hasOlder || loadingOlder || following) return
    const now = Date.now()
    if (now - lastUserLoadAt.current < 400) return
    lastUserLoadAt.current = now
    onLoadOlder?.()
  }

  const onWheel = (e: WheelEvent<HTMLDivElement>) => {
    const el = ref.current
    if (!el || ignoreScrollRef.current) return
    if (e.deltaY >= 0) {
      if (atTopRef) atTopRef.current = false
      return
    }
    if (following) return
    if (el.scrollTop > 1) return
    if (el.scrollHeight <= el.clientHeight + 8) return
    if (atTopRef) atTopRef.current = true
    requestOlder()
  }

  const onScroll = () => {
    const el = ref.current
    if (!el || ignoreScrollRef.current) return
    const top = el.scrollTop
    savedScrollTop.current = top
    const atBottom = el.scrollHeight - top - el.clientHeight < 40
    atBottomRef.current = atBottom
    if (atBottom) {
      setFollowing(true)
      setHeadSeq(undefined)
      if (atTopRef) atTopRef.current = false
    } else {
      setFollowing((was) => {
        if (was) setHeadSeq(visible[0]?.seq)
        return false
      })
      if (atTopRef) atTopRef.current = top <= 1
    }
    setShowJump(!atBottom)
  }

  const jumpToBottom = () => {
    const el = ref.current
    if (!el) return
    el.scrollTop = el.scrollHeight
    atBottomRef.current = true
    setFollowing(true)
    setHeadSeq(undefined)
    if (atTopRef) atTopRef.current = false
    setShowJump(false)
  }

  const isLatest = session >= sessionCount
  const isLive = isLatest && running !== false
  const sessionStatus = isLive ? "运行中" : isLatest ? "已结束" : "历史"
  const goSession = (n: number) => {
    if (n < 1 || n > sessionCount) return
    onSessionChange?.(n >= sessionCount ? null : n)
  }

  const commitDraft = () => {
    setEditing(false)
    const n = parseInt(draft, 10)
    if (!Number.isFinite(n)) {
      setDraft(String(session))
      return
    }
    const clamped = Math.min(sessionCount, Math.max(1, Math.trunc(n)))
    setDraft(String(clamped))
    if (clamped !== session) goSession(clamped)
  }

  return (
    <div className="fw-task-log" data-log-window="100">
      <div className="fw-log-bar">
        <span className="fw-log-bar-label">实时日志</span>
        <span className="fw-log-pager">
          <Button
            type="button"
            variant="outline"
            size="icon-xs"
            className="fw-log-pager-btn"
            disabled={session <= 1}
            aria-label="上一轮"
            onClick={() => goSession(session - 1)}
          >
            ‹
          </Button>
          <span className={"fw-log-pager-status" + (isLive ? " live" : "")}>
            第
            <Input
              className="fw-log-pager-input"
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              aria-label="跳到指定轮次"
              value={draft}
              size={Math.max(2, String(sessionCount).length)}
              onFocus={(e) => {
                setEditing(true)
                e.currentTarget.select()
              }}
              onChange={(e) => setDraft(e.target.value.replace(/\D/g, ""))}
              onBlur={() => {
                if (skipBlurCommit.current) {
                  skipBlurCommit.current = false
                  setEditing(false)
                  return
                }
                commitDraft()
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  skipBlurCommit.current = true
                  commitDraft()
                  e.currentTarget.blur()
                } else if (e.key === "Escape") {
                  skipBlurCommit.current = true
                  setDraft(String(session))
                  setEditing(false)
                  e.currentTarget.blur()
                }
              }}
            />
            / {sessionCount} 轮 · {sessionStatus}
          </span>
          <Button
            type="button"
            variant="outline"
            size="icon-xs"
            className="fw-log-pager-btn"
            disabled={session >= sessionCount}
            aria-label="下一轮"
            onClick={() => goSession(session + 1)}
          >
            ›
          </Button>
        </span>
        <span className="fw-log-count">
          最近 {visible.length} 条
          {moreHidden ? " · 上滑加载更早" : ""}
          {loadingOlder ? " · 加载中…" : ""}
        </span>
      </div>
      <div className="fw-log-wrap">
        <div
          ref={ref}
          className="fw-log"
          onScroll={onScroll}
          onWheel={onWheel}
          style={{ minHeight, maxHeight: Math.max(minHeight, 560) }}
        >
          {visible.length === 0 ? (
            <div className="fw-log-empty">{emptyHint}</div>
          ) : (
            visible.map((ev, i) => (
              <LogLine key={ev.seq != null ? `s${ev.seq}` : `${ev.ts || i}-${ev.kind}-${i}`} ev={ev} />
            ))
          )}
        </div>
        {showJump ? (
          <Button type="button" variant="outline" size="sm" className="fw-jump-btn" onClick={jumpToBottom}>
            跳到最新
          </Button>
        ) : null}
      </div>
    </div>
  )
}
