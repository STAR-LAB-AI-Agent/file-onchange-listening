import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Trash2Icon } from "lucide-react"

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

export function TaskDetail({ watchId }: { watchId: string }) {
  const [info, setInfo] = useState<WatcherInfo | null>(null)
  const [events, setEvents] = useState<FileEvent[]>([])
  const [filter, setFilter] = useState("all")
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const cursorRef = useRef(0)

  const visible = useMemo(
    () => events.filter((item) => filter === "all" || item.type === filter),
    [events, filter],
  )

  const loadLatest = useCallback(async () => {
    const data = await api<WatcherInfo>(
      `/api/watchers/${encodeURIComponent(watchId)}/events?tail=1&limit=200`,
    )
    cursorRef.current = data.cursor || 0
    setEvents((data.items || []).slice().reverse())
    setInfo(data)
  }, [watchId])

  useEffect(() => {
    let cancelled = false
    setEvents([])
    setInfo(null)
    cursorRef.current = 0
    void loadLatest().catch((err: unknown) => {
      if (!cancelled) setError(err instanceof Error ? err.message : "无法加载任务")
    })
    const timer = window.setInterval(async () => {
      try {
        const data = await api<WatcherInfo>(
          `/api/watchers/${encodeURIComponent(watchId)}/events?since=${cursorRef.current}&limit=100`,
        )
        if (data.items && data.items.length) {
          cursorRef.current = data.cursor || cursorRef.current
          setEvents((prev) => data.items!.slice().reverse().concat(prev).slice(0, 500))
        }
        setInfo(data)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "轮询失败")
      }
    }, 800)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [loadLatest, watchId])

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
      await loadLatest()
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
      await loadLatest()
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止失败")
    } finally {
      setStopping(false)
    }
  }

  const watchPath = info?.path || undefined

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
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={filter}
          onValueChange={(value) => {
            if (value) setFilter(value)
          }}
          spacing={0}
        >
          {FILTERS.map((item) => (
            <ToggleGroupItem key={item.id} value={item.id}>
              {item.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <Button variant="ghost" size="sm" onClick={() => setEvents([])}>
          <Trash2Icon data-icon="inline-start" />
          清空视图
        </Button>
      </div>

      <Card size="sm">
        <CardHeader className="border-b">
          <CardTitle>文件变化</CardTitle>
          <CardDescription>仅显示此目录下的事件 · {visible.length} 条</CardDescription>
          <CardAction>
            <Badge variant="outline">{filter === "all" ? "全部类型" : TYPE_LABEL[filter]}</Badge>
          </CardAction>
        </CardHeader>
        <CardContent className="p-0">
          {visible.length === 0 ? (
            <div className="px-4 py-16 text-center text-sm text-muted-foreground">
              这个任务还没有文件变化。
            </div>
          ) : (
            <ScrollArea className="h-[min(28rem,60vh)]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-48">时间</TableHead>
                    <TableHead className="w-24">类型</TableHead>
                    <TableHead>路径</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visible.map((item, index) => {
                    const type = item.type || ""
                    return (
                      <TableRow key={item.id || `${item.ts}-${item.path}-${index}`}>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {item.ts || ""}
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
        </CardContent>
      </Card>
    </TaskChrome>
  )
}
