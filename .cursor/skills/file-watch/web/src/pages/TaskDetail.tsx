import { useCallback, useEffect, useRef, useState } from "react"
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react"

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

function toFromIso(local: string) {
  return local ? `${local}:00+08:00` : ""
}

function toToIso(local: string) {
  return local ? `${local}:59.999+08:00` : ""
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
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const cursorRef = useRef(0)

  const loadPage = useCallback(async () => {
    const params = new URLSearchParams()
    params.set("page", String(page))
    params.set("page_size", String(PAGE_SIZE))
    if (filter !== "all") params.set("type", filter)
    if (tsFrom) params.set("ts_from", toFromIso(tsFrom))
    if (tsTo) params.set("ts_to", toToIso(tsTo))
    return api<WatcherInfo>(`/api/watchers/${encodeURIComponent(watchId)}/events?${params.toString()}`)
  }, [filter, page, tsFrom, tsTo, watchId])

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
        if (live.items && live.items.length && page === 1) {
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
  const emptyHint = hasRange || filter !== "all" ? "没有符合筛选条件的文件变化。" : "这个任务还没有文件变化。"

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
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
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
                    return (
                      <TableRow key={item.id || `${item.ts}-${item.path}-${index}`}>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {formatEventTime(item.ts)}
                        </TableCell>
                        <TableCell>
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
