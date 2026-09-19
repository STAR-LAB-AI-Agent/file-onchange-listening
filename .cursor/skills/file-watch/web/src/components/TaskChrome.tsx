import type { ReactNode } from "react"
import { useState } from "react"
import { AlertCircleIcon, ArrowLeftIcon, PlayIcon, Settings2Icon, SquareIcon } from "lucide-react"

import { WatchTitle } from "@/components/WatchTitle"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, navigate, type TaskPage, type WatcherInfo } from "@/lib/api"

export function TaskChrome({
  watchId,
  info,
  page,
  error,
  starting,
  stopping,
  onStart,
  onStop,
  onRenamed,
  onRenameError,
  children,
}: {
  watchId: string
  info: WatcherInfo | null
  page: TaskPage
  error?: string | null
  starting?: boolean
  stopping?: boolean
  onStart: () => void
  onStop: () => void
  onRenamed?: (info: WatcherInfo) => void
  onRenameError?: (message: string) => void
  children: ReactNode
}) {
  const running = !!info?.running
  const base = `/tasks/${encodeURIComponent(watchId)}`
  const recordAll = info?.record_all !== false
  const [savingWatch, setSavingWatch] = useState(false)

  async function setRecordAll(next: boolean) {
    setSavingWatch(true)
    try {
      const data = await api<WatcherInfo>(`/api/watchers/${encodeURIComponent(watchId)}/watch`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_all: next }),
      })
      onRenamed?.(data)
    } catch (err) {
      onRenameError?.(err instanceof Error ? err.message : "无法更新监听范围")
    } finally {
      setSavingWatch(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-8">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink
              href="/"
              onClick={(event) => {
                event.preventDefault()
                navigate("/")
              }}
            >
              监听任务
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{info?.title || watchId}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <WatchTitle
            watchId={watchId}
            title={info?.title}
            path={info?.path}
            heading
            onRenamed={onRenamed}
            onError={onRenameError}
          />
          <p className="font-mono text-sm break-all text-muted-foreground">{info?.path || "正在加载目录…"}</p>
          {info ? (
            <label className="flex max-w-xl items-start gap-2 pt-1 text-sm">
              <Switch
                className="mt-0.5"
                checked={recordAll}
                disabled={savingWatch}
                onCheckedChange={(checked) => void setRecordAll(checked)}
              />
              <span>
                <span className="font-medium">默认监听全部文件变化</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {recordAll
                    ? "除忽略和排除规则外，目录下的变化都会记入文件变化列表。"
                    : "仅记录命中正向规则的文件。没有规则时不会出现任何变化。"}
                </span>
              </span>
            </label>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={running ? "default" : "secondary"} className="gap-1.5">
            <span className={`size-1.5 rounded-full ${running ? "bg-emerald-400" : "bg-muted-foreground"}`} />
            {running ? "实时监听中" : "已停止"}
          </Badge>
          {info && !recordAll ? (
            <Badge variant="outline">仅规则命中</Badge>
          ) : null}
          <Button variant="outline" size="sm" onClick={() => navigate("/settings")}>
            <Settings2Icon data-icon="inline-start" />
            设置
          </Button>
          <Button variant="outline" size="sm" onClick={() => navigate("/")}>
            <ArrowLeftIcon data-icon="inline-start" />
            返回列表
          </Button>
          {running ? (
            <Button variant="outline" size="sm" onClick={onStop} disabled={stopping}>
              <SquareIcon data-icon="inline-start" />
              停止
            </Button>
          ) : (
            <Button size="sm" onClick={onStart} disabled={starting || !info?.path}>
              <PlayIcon data-icon="inline-start" />
              开始监听
            </Button>
          )}
        </div>
      </header>

      <Tabs
        value={page}
        onValueChange={(value) => navigate(value === "rules" ? `${base}/rules` : base)}
      >
        <TabsList>
          <TabsTrigger value="events">文件变化</TabsTrigger>
          <TabsTrigger value="rules">监听规则</TabsTrigger>
        </TabsList>
      </Tabs>

      {error ? (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>无法完成操作</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {children}
    </div>
  )
}
