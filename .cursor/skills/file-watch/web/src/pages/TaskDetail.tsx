import { useCallback, useEffect, useRef, useState } from "react"
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon, SearchIcon, XIcon } from "lucide-react"

import { TaskChrome } from "@/components/TaskChrome"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import {
  TYPE_LABEL,
  api,
  formatEventTime,
  relPath,
  typeBadgeClass,
  type FileEvent,
  type LineChanges,
  type WatcherInfo,
} from "@/lib/api"

const FILTERS = [
  { id: "all", label: "全部" },
  { id: "created", label: "新建" },
  { id: "modified", label: "修改" },
  { id: "deleted", label: "删除" },
  { id: "moved", label: "移动" },
]

const PAGE_SIZE = 100
const SKIP_REASON: Record<string, string> = {
  binary: "二进制，无行级变化",
  too_large: "文件过大，未做行级对比",
  unreadable: "无法读取，未做行级对比",
  no_baseline: "尚无基线，下次修改起计入行级变化",
}

function toFromIso(local: string) {
  return local ? `${local}:00+08:00` : ""
}

function toToIso(local: string) {
  return local ? `${local}:59.999+08:00` : ""
}

function lineSummary(lc: LineChanges | null | undefined) {
  if (!lc) return null
  if (lc.kind === "pending") return null
  if (lc.kind === "skipped") {
    return {
      label: SKIP_REASON[lc.reason || ""] || `已跳过（${lc.reason || "unknown"}）`,
      expandable: false,
    }
  }
  if (lc.kind === "text") {
    const added = lc.added ?? 0
    const removed = lc.removed ?? 0
    if (added === 0 && removed === 0) {
      return { label: "内容未变", expandable: false }
    }
    const trunc = lc.truncated ? "（已截断）" : ""
    return {
      label: `+${added} / −${removed}${trunc}`,
      expandable: Boolean(lc.changes && lc.changes.length),
    }
  }
  return null
}

function LineDiffPanel({ lc }: { lc: LineChanges }) {
  const rows = lc.changes || []
  if (!rows.length) return null
  return (
    <div className="mt-2 max-h-48 overflow-auto rounded-md border bg-muted/30 px-2 py-1.5 font-mono text-[11px] leading-5">
      {rows.map((row, index) => {
        const add = row.op === "add"
        return (
          <div
            key={`${row.op}-${row.line}-${index}`}
            className={
              add
                ? "whitespace-pre-wrap break-all text-emerald-700 dark:text-emerald-400"
                : "whitespace-pre-wrap break-all text-rose-700 dark:text-rose-400"
            }
          >
            <span className="mr-2 inline-block w-10 text-right text-muted-foreground">{row.line}</span>
            <span className="mr-1">{add ? "+" : "−"}</span>
            {row.text ?? ""}
          </div>
        )
      })}
    </div>
  )
}

export function TaskDetail({ watchId }: { watchId: string }) {
  const [info, setInfo] = useState<WatcherInfo | null>(null)
  const [events, setEvents] = useState<FileEvent[]>([])
  const [filter, setFilter] = useState("all")
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [tsFrom, setTsFrom] = useState("")
  const [tsTo, setTsTo] = useState("")
  const [pathQuery, setPathQuery] = useState("")
  const [pathSearch, setPathSearch] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const cursorRef = useRef(0)

  useEffect(() => {
    const next = pathQuery.trim()
    const timer = window.setTimeout(() => {
      setPathSearch((current) => {
        if (current === next) return current
        setPage(1)
        return next
      })
    }, 250)
    return () => window.clearTimeout(timer)
  }, [pathQuery])

  const loadPage = useCallback(async () => {
    const params = new URLSearchParams()
    params.set("page", String(page))
    params.set("page_size", String(PAGE_SIZE))
    if (filter !== "all") params.set("type", filter)
    if (pathSearch) params.set("q", pathSearch)
    if (tsFrom) params.set("ts_from", toFromIso(tsFrom))
    if (tsTo) params.set("ts_to", toToIso(tsTo))
    return api<WatcherInfo>(`/api/watchers/${encodeURIComponent(watchId)}/events?${params.toString()}`)
  }, [filter, page, pathSearch, tsFrom, tsTo, watchId])

  const applyPage = useCallback(
    (data: WatcherInfo) => {
      cursorRef.current = data.cursor || cursorRef.current
      setEvents(data.items || [])
      setInfo(data)
      setPages(data.pages || 1)
      setTotal(data.total || 0)
      if (data.page && data.page !== page) setPage(data.page)
    },
    [page],
  )

  useEffect(() => {
    let cancelled = false
    setEvents([])
    setInfo(null)
    void loadPage()
      .then((data) => {
        if (!cancelled) applyPage(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "无法加载任务")
      })
    const timer = window.setInterval(async () => {
      try {
        const live = await api<WatcherInfo>(
          `/api/watchers/${encodeURIComponent(watchId)}/events?since=${cursorRef.current}&limit=100`,
        )
        if (cancelled) return
        if (live.cursor) cursorRef.current = live.cursor
        setInfo(live)
        // Refresh page 1 so settled line_changes (sidecar) appear without a new event.
        if (page === 1 || (live.items && live.items.length)) {
          const data = await loadPage()
          if (!cancelled) applyPage(data)
        }
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "轮询失败")
      }
    }, 800)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [applyPage, loadPage, page, watchId])

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
      applyPage(await loadPage())
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
      applyPage(await loadPage())
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止失败")
    } finally {
      setStopping(false)
    }
  }

  const watchPath = info?.path || undefined
  const hasRange = Boolean(tsFrom || tsTo)
  const hasFilters = hasRange || filter !== "all" || Boolean(pathSearch)
  const emptyHint = hasFilters
    ? "没有符合筛选条件的文件变化。"
    : info?.record_all === false
      ? info.rule_count
        ? "当前只记录命中规则的文件，还没有符合规则的变化。"
        : "当前只记录命中规则的文件。请先到「监听规则」添加规则。"
      : "这个任务还没有文件变化。"

  return (
    <TaskChrome
      watchId={watchId}
      info={info}
      page="events"
      error={error}
      starting={starting}
      stopping={stopping}
      onStart={() => void startWatch()}
      onStop={() => void stopWatch()}
      onRenamed={(data) => setInfo((current) => ({ ...current, ...data }))}
      onRenameError={setError}
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
            <div className="grid gap-1">
              <Label htmlFor="event-path">搜索文件</Label>
              <div className="relative">
                <SearchIcon className="pointer-events-none absolute top-1/2 left-2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="event-path"
                  type="text"
                  value={pathQuery}
                  onChange={(event) => setPathQuery(event.target.value)}
                  placeholder="文件名或路径"
                  className="w-full pr-8 pl-8 sm:w-64"
                  autoComplete="off"
                  onKeyDown={(event) => {
                    if (event.key !== "Enter") return
                    event.preventDefault()
                    const next = pathQuery.trim()
                    setPathSearch(next)
                    setPage(1)
                  }}
                />
                {pathQuery ? (
                  <button
                    type="button"
                    className="absolute top-1/2 right-1.5 inline-flex size-5 -translate-y-1/2 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground"
                    aria-label="清除搜索"
                    onClick={() => {
                      setPathQuery("")
                      setPathSearch("")
                      setPage(1)
                    }}
                  >
                    <XIcon className="size-3.5" />
                  </button>
                ) : null}
              </div>
            </div>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={filter}
              onValueChange={(value) => {
                if (value) {
                  setFilter(value)
                  setPage(1)
                }
              }}
              spacing={0}
            >
              {FILTERS.map((item) => (
                <ToggleGroupItem key={item.id} value={item.id}>
                  {item.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div className="grid gap-1">
              <Label htmlFor="event-from">从（东八区）</Label>
              <Input
                id="event-from"
                type="datetime-local"
                value={tsFrom}
                onChange={(event) => {
                  setTsFrom(event.target.value)
                  setPage(1)
                }}
                className="w-[13.5rem]"
              />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="event-to">到（东八区）</Label>
              <Input
                id="event-to"
                type="datetime-local"
                value={tsTo}
                onChange={(event) => {
                  setTsTo(event.target.value)
                  setPage(1)
                }}
                className="w-[13.5rem]"
              />
            </div>
            <Button
              variant="outline"
              size="sm"
              type="button"
              disabled={!hasRange}
              onClick={() => {
                setTsFrom("")
                setTsTo("")
                setPage(1)
              }}
            >
              清除时间
            </Button>
          </div>
        </div>
      </div>

      <Card size="sm">
        <CardHeader className="border-b">
          <CardTitle>文件变化</CardTitle>
          <CardDescription>
            仅显示此目录下的事件 · 共 {total} 条 · 第 {page} / {pages} 页 · 每页 {PAGE_SIZE} 条
          </CardDescription>
          <CardAction>
            <Badge variant="outline">{filter === "all" ? "全部类型" : TYPE_LABEL[filter]}</Badge>
          </CardAction>
        </CardHeader>
        <CardContent className="p-0">
          {events.length === 0 ? (
            <div className="px-4 py-16 text-center text-sm text-muted-foreground">{emptyHint}</div>
          ) : (
            <ScrollArea className="h-[min(28rem,60vh)]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-48">时间（东八区）</TableHead>
                    <TableHead className="w-24">类型</TableHead>
                    <TableHead>路径</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {events.map((item, index) => {
                    const type = item.type || ""
                    const eventKey = item.id || `${item.ts}-${item.path}-${index}`
                    const summary = lineSummary(item.line_changes)
                    const open = Boolean(expanded[eventKey])
                    return (
                      <TableRow key={eventKey}>
                        <TableCell className="align-top font-mono text-xs text-muted-foreground">
                          {formatEventTime(item.ts)}
                        </TableCell>
                        <TableCell className="align-top">
                          <Badge variant="outline" className={typeBadgeClass(type)}>
                            {TYPE_LABEL[type] || type}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs break-all whitespace-normal">
                          <div>{relPath(item.path, watchPath)}</div>
                          {item.old_path ? (
                            <div className="text-muted-foreground">从 {relPath(item.old_path, watchPath)}</div>
                          ) : null}
                          {item.is_dir ? <div className="text-muted-foreground">目录</div> : null}
                          {summary ? (
                            <div className="mt-1">
                              {summary.expandable ? (
                                <button
                                  type="button"
                                  className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
                                  onClick={() =>
                                    setExpanded((current) => ({
                                      ...current,
                                      [eventKey]: !current[eventKey],
                                    }))
                                  }
                                >
                                  <ChevronDownIcon
                                    className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`}
                                  />
                                  <span
                                    className={
                                      item.line_changes?.kind === "text"
                                        ? "text-emerald-700 dark:text-emerald-400"
                                        : undefined
                                    }
                                  >
                                    {summary.label}
                                  </span>
                                </button>
                              ) : (
                                <span className="text-[11px] text-muted-foreground">{summary.label}</span>
                              )}
                              {open && item.line_changes?.kind === "text" ? (
                                <LineDiffPanel lc={item.line_changes} />
                              ) : null}
                            </div>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </ScrollArea>
          )}
          <div className="flex flex-col gap-2 border-t px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-xs text-muted-foreground">
              {total
                ? `显示第 ${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, total)} 条`
                : "没有可显示的事件"}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                type="button"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                <ChevronLeftIcon data-icon="inline-start" />
                上一页
              </Button>
              <Button
                variant="outline"
                size="sm"
                type="button"
                disabled={page >= pages}
                onClick={() => setPage((current) => current + 1)}
              >
                下一页
                <ChevronRightIcon data-icon="inline-end" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </TaskChrome>
  )
}
