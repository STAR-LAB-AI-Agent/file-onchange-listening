import { useCallback, useEffect, useState } from "react"
import { PencilIcon, PlusIcon, SparklesIcon, Trash2Icon } from "lucide-react"

import { TaskChrome } from "@/components/TaskChrome"
import { RuleForm } from "@/components/RuleForm"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import {
  TYPE_LABEL,
  ApiError,
  api,
  blankRule,
  navigate,
  typeBadgeClass,
  type GeneratedRulesResponse,
  type LlmSettings,
  type WatchRule,
  type WatcherInfo,
} from "@/lib/api"

export function TaskRules({ watchId }: { watchId: string }) {
  const [info, setInfo] = useState<WatcherInfo | null>(null)
  const [rules, setRules] = useState<WatchRule[]>([])
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [saving, setSaving] = useState(false)
  const [nl, setNl] = useState("")
  const [mode, setMode] = useState("append")
  const [notes, setNotes] = useState<string[]>([])
  const [preview, setPreview] = useState<WatchRule[] | null>(null)
  const [editor, setEditor] = useState<{ index: number | null; rule: WatchRule } | null>(null)
  const [keySet, setKeySet] = useState<boolean | null>(null)

  const load = useCallback(async () => {
    const data = await api<WatcherInfo>(`/api/watchers/${encodeURIComponent(watchId)}/config`)
    setInfo(data)
    setRules(data.config?.rules || [])
  }, [watchId])

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "无法加载规则")
    })
  }, [load])

  useEffect(() => {
    void api<{ llm: LlmSettings }>("/api/settings")
      .then((data) => setKeySet(!!data.llm.api_key_set))
      .catch(() => setKeySet(null))
  }, [])

  async function persist(next: WatchRule[], message?: string) {
    setSaving(true)
    setError(null)
    try {
      const data = await api<WatcherInfo>(`/api/watchers/${encodeURIComponent(watchId)}/rules`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rules: next }),
      })
      setInfo(data)
      setRules(data.config?.rules || next)
      if (message) setNotes([data.message || message, ...(data.warnings || [])])
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

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
      await load()
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
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "停止失败")
    } finally {
      setStopping(false)
    }
  }

  async function generate(apply: boolean) {
    setSaving(true)
    setError(null)
    try {
      const data = await api<GeneratedRulesResponse>(`/api/watchers/${encodeURIComponent(watchId)}/rules/from-text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: nl, apply, mode }),
      })
      setNotes([...(data.notes || []), ...(data.warnings || []), data.message].filter(Boolean) as string[])
      if (apply) {
        setPreview(null)
        await load()
      } else {
        setPreview(data.rules || [])
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === "llm_not_configured") {
        setKeySet(false)
      }
      setError(err instanceof Error ? err.message : "生成失败")
    } finally {
      setSaving(false)
    }
  }

  function upsertRule(rule: WatchRule) {
    const next = [...rules]
    if (editor?.index == null) {
      if (next.some((item) => item.name === rule.name)) {
        setError(`规则名已存在：${rule.name}`)
        return
      }
      next.push(rule)
    } else {
      next[editor.index] = rule
    }
    setEditor(null)
    void persist(next, "规则已保存")
  }

  return (
    <TaskChrome
      watchId={watchId}
      info={info}
      page="rules"
      error={error}
      starting={starting}
      stopping={stopping}
      onStart={() => void startWatch()}
      onStop={() => void stopWatch()}
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SparklesIcon className="size-4" />
            自然语言生成
          </CardTitle>
          <CardDescription>
            口语由 LLM 转成规则，例如「新建或修改 markdown 时通知我，30 秒内不要重复」。也可直接粘贴 YAML/JSON，不调用模型。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {keySet === false ? (
            <Alert>
              <AlertTitle>尚未配置 LLM</AlertTitle>
              <AlertDescription>请先在设置页填写 API Key。粘贴 YAML 或 JSON 规则不受影响。</AlertDescription>
              <AlertAction>
                <Button size="xs" variant="outline" onClick={() => navigate("/settings")}>
                  去设置
                </Button>
              </AlertAction>
            </Alert>
          ) : null}
          <Textarea
            value={nl}
            onChange={(event) => setNl(event.target.value)}
            rows={4}
            placeholder="删除图片后发通知；再加一条：所有 txt 变化写入邮箱"
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="grid gap-1.5">
              <Label>写入方式</Label>
              <ToggleGroup type="single" variant="outline" size="sm" value={mode} onValueChange={(value) => value && setMode(value)}>
                <ToggleGroupItem value="append">追加</ToggleGroupItem>
                <ToggleGroupItem value="replace">替换全部</ToggleGroupItem>
              </ToggleGroup>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void generate(false)} disabled={saving || !nl.trim()}>
                生成预览
              </Button>
              <Button onClick={() => void generate(true)} disabled={saving || !nl.trim()}>
                生成并保存
              </Button>
            </div>
          </div>
          {notes.length ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {notes.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
          {preview?.length ? (
            <div className="rounded-lg border p-3 text-sm">
              <div className="mb-2 font-medium">将生成 {preview.length} 条规则</div>
              {preview.map((rule) => (
                <div key={rule.name} className="font-mono text-xs text-muted-foreground">
                  {rule.name} · {(rule.when?.types || []).join("/")} · {(rule.when?.glob || []).join(", ")}
                </div>
              ))}
              <Button
                className="mt-3"
                size="sm"
                onClick={() => void generate(true)}
                disabled={saving}
              >
                确认保存
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader className="border-b">
          <CardTitle>当前规则</CardTitle>
          <CardDescription>
            {rules.length} 条 · {info?.running ? "保存后热更新" : "未运行，保存到配置，下次启动生效"}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 p-4">
          <div>
            <Button size="sm" onClick={() => setEditor({ index: null, rule: blankRule() })}>
              <PlusIcon data-icon="inline-start" />
              手动添加
            </Button>
          </div>
          {rules.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">还没有规则。命中规则后会写入 jobs 邮箱。</div>
          ) : (
            <div className="flex flex-col gap-3">
              {rules.map((rule, index) => (
                <div key={`${rule.name}-${index}`} className="flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="font-medium">{rule.name}</div>
                      <Badge variant={rule.enabled === false ? "secondary" : "default"}>
                        {rule.enabled === false ? "停用" : "启用"}
                      </Badge>
                      {(rule.then || []).map((action, actionIndex) => (
                        <Badge key={actionIndex} variant="outline">
                          {action.notify ? "notify" : "agent"}
                        </Badge>
                      ))}
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
                      {rule.when?.regex ? ` · re ${rule.when.regex}` : ""}
                      {rule.when?.cooldown_seconds ? ` · 冷却 ${rule.when.cooldown_seconds}s` : ""}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="flex items-center gap-2 text-sm">
                      <Switch
                        checked={rule.enabled !== false}
                        onCheckedChange={(checked) => {
                          const next = rules.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, enabled: checked } : item,
                          )
                          void persist(next)
                        }}
                      />
                      启用
                    </label>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setEditor({ index, rule })}
                    >
                      <PencilIcon data-icon="inline-start" />
                      编辑
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        if (window.confirm(`删除规则 ${rule.name}？`)) {
                          void persist(rules.filter((_, itemIndex) => itemIndex !== index))
                        }
                      }}
                    >
                      <Trash2Icon data-icon="inline-start" />
                      删除
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!editor} onOpenChange={(open) => !open && setEditor(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editor?.index == null ? "添加规则" : "编辑规则"}</DialogTitle>
            <DialogDescription>条件写在 when，动作默认 notify。模板可用 {"{{path}}"} {"{{type}}"} {"{{filename}}"}。</DialogDescription>
          </DialogHeader>
          {editor ? (
            <RuleForm
              key={`${editor.index}-${editor.rule.name}`}
              initial={editor.rule}
              submitting={saving}
              onSubmit={upsertRule}
              onCancel={() => setEditor(null)}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </TaskChrome>
  )
}
