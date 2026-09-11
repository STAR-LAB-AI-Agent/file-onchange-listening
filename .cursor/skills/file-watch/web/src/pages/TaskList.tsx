import { useEffect, useState } from "react"
import { AlertCircleIcon, FolderOpenIcon, PlayIcon, Settings2Icon, SquareIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  TYPE_LABEL,
  api,
  navigate,
  relPath,
  typeBadgeClass,
  type WatcherInfo,
} from "@/lib/api"

export function TaskList() {
  const [path, setPath] = useState("")
  const [tasks, setTasks] = useState<WatcherInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [stoppingId, setStoppingId] = useState<string | null>(null)

  async function refresh() {
    const data = await api<{ watchers: WatcherInfo[] }>("/api/watchers")
    setTasks(data.watchers)
  }

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        await refresh()
        if (!cancelled) setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "无法加载任务")
      }
    }
    void load()
    const timer = window.setInterval(() => {
      void load()
    }, 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  async function startWatch() {
    const folder = path.trim()
    if (!folder) {
      setError("请输入要监听的文件夹路径")
      return
    }
    setStarting(true)
    setError(null)
    try {
      const data = await api<WatcherInfo>("/api/watchers/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: folder, recursive: true }),
      })
      if (!data.watch_id) throw new Error("未返回任务 id")
      setPath("")
      await refresh()
      navigate(`/tasks/${encodeURIComponent(data.watch_id)}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动失败")
    } finally {
      setStarting(false)
    }
  }

  async function stopWatch(watchId: string) {
    setStoppingId(watchId)
    try {
      await api(`/api/watchers/${encodeURIComponent(watchId)}/stop`, { method: "POST" })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止失败")
    } finally {
      setStoppingId(null)
    }
  }

  const runningCount = tasks.filter((item) => item.running).length

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1">
          <h1 className="font-heading text-2xl font-medium tracking-tight">监听任务</h1>
          <p className="text-sm text-muted-foreground">每个目录是一个任务。打开详情查看该目录的文件变化。</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate("/settings")}>
            <Settings2Icon data-icon="inline-start" />
            设置
          </Button>
          <Badge variant={runningCount ? "default" : "secondary"} className="w-fit gap-1.5">
            <span className={`size-1.5 rounded-full ${runningCount ? "bg-emerald-400" : "bg-muted-foreground"}`} />
            {runningCount ? `${runningCount} 个运行中` : "没有运行中的任务"}
          </Badge>
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>添加目录</CardTitle>
          <CardDescription>可同时监听多个文件夹。同一路径会复用已有任务。</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative min-w-0 flex-1">
              <FolderOpenIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={path}
                onChange={(event) => setPath(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void startWatch()
                }}
                placeholder="例如 D:\data\inbox"
                spellCheck={false}
                className="h-9 pl-8 font-mono"
              />
            </div>
            <Button onClick={() => void startWatch()} disabled={starting}>
              <PlayIcon data-icon="inline-start" />
              添加并监听
            </Button>
          </div>
          {error ? (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>无法完成操作</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader className="border-b">
          <CardTitle>任务列表</CardTitle>
          <CardDescription>{tasks.length} 个目录</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {tasks.length === 0 ? (
            <div className="px-4 py-16 text-center text-sm text-muted-foreground">
              还没有监听任务。在上方添加一个目录开始。
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>目录</TableHead>
                  <TableHead className="w-28">状态</TableHead>
                  <TableHead>最近变化</TableHead>
                  <TableHead className="w-52 text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tasks.map((task) => {
                  const last = task.last_event
                  return (
                    <TableRow
                      key={task.watch_id}
                      className="cursor-pointer"
                      onClick={() => navigate(`/tasks/${encodeURIComponent(task.watch_id || "")}`)}
                    >
                      <TableCell>
                        <div className="font-medium">{task.title || task.watch_id}</div>
                        <div className="font-mono text-xs break-all text-muted-foreground">{task.path}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={task.running ? "default" : "secondary"}>
                          {task.running ? "运行中" : "已停止"}
                        </Badge>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {task.event_count || 0} 条事件 · {task.rule_count || 0} 条规则
                        </div>
                      </TableCell>
                      <TableCell>
                        {last ? (
                          <div className="space-y-1">
                            <Badge variant="outline" className={typeBadgeClass(last.type || "")}>
                              {TYPE_LABEL[last.type || ""] || last.type}
                            </Badge>
                            <div className="font-mono text-xs break-all text-muted-foreground">
                              {relPath(last.path, task.path || undefined)}
                            </div>
                          </div>
                        ) : (
                          <span className="text-sm text-muted-foreground">暂无</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2" onClick={(event) => event.stopPropagation()}>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => navigate(`/tasks/${encodeURIComponent(task.watch_id || "")}`)}
                          >
                            详情
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => navigate(`/tasks/${encodeURIComponent(task.watch_id || "")}/rules`)}
                          >
                            规则
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={!task.running || stoppingId === task.watch_id}
                            onClick={() => void stopWatch(task.watch_id || "")}
                          >
                            <SquareIcon data-icon="inline-start" />
                            停止
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
