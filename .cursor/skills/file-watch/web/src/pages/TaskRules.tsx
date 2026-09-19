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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import {
  TYPE_LABEL,
  ApiError,
  api,
  blankRule,
  formatActive,
  navigate,
  typeBadgeClass,
  type AppSettings,
  type DingTalkChannel,
  type GeneratedRulesResponse,
  type WatchRule,
  type WatcherInfo,
  hasDingtalk,
} from "@/lib/api"

export function TaskRules({ watchId }: { watchId: string }) {
  const [info, setInfo] = useState<WatcherInfo | null>(null)
  const [rules, setRules] = useState<WatchRule[]>([])
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [saving, setSaving] = useState(false)
  const [nl, setNl] = useState("")
  const [aiEdit, setAiEdit] = useState("")
  const [aiNotes, setAiNotes] = useState<string[]>([])
  const [notes, setNotes] = useState<string[]>([])
  const [preview, setPreview] = useState<WatchRule[] | null>(null)
  const [editor, setEditor] = useState<{ index: number | null; rule: WatchRule; rev: number } | null>(null)
  const [keySet, setKeySet] = useState<boolean | null>(null)
  const [channels, setChannels] = useState<DingTalkChannel[]>([])

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
    void api<AppSettings>("/api/settings")
      .then((data) => {
        setKeySet(!!data.llm.api_key_set)
        setChannels(data.dingtalk?.channels || [])
      })
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
        body: JSON.stringify({ text: nl, apply }),
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

  function openEditor(index: number | null, rule: WatchRule) {
    setAiEdit("")
    setAiNotes([])
    setEditor({ index, rule, rev: 0 })
  }

  async function applyAiEdit() {
    if (!editor) return
    const text = aiEdit.trim()
    if (!text) return
    setSaving(true)
    setError(null)
    try {
      const path =
        editor.index == null
          ? `/api/watchers/${encodeURIComponent(watchId)}/rules/from-text`
          : `/api/watchers/${encodeURIComponent(watchId)}/rules/${editor.index}/from-text`
      const data = await api<GeneratedRulesResponse>(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, apply: false }),
      })
      const nextRule = editor.index == null ? data.rules?.[0] || data.rule : data.rule || data.rules?.[0]
      if (!nextRule) {
        setError("没有生成规则")
        return
      }
      setEditor({ index: editor.index, rule: nextRule, rev: editor.rev + 1 })
      setAiNotes([...(data.notes || []), ...(data.warnings || [])].filter(Boolean) as string[])
      setAiEdit("")
    } catch (err) {
      if (err instanceof ApiError && err.code === "llm_not_configured") {
        setKeySet(false)
      }
      setError(err instanceof Error ? err.message : "编辑失败")
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
      onRenamed={(data) => setInfo((current) => ({ ...current, ...data }))}
      onRenameError={setError}
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SparklesIcon className="size-4" />
            自然语言添加规则
          </CardTitle>
          <CardDescription>
            口语由 LLM 转成新规则并追加，不会改已有规则。例如「新建或修改 markdown 时通知我，30 秒内不要重复」，或「不要监听 log 文件」。修改某条请点「编辑」，在表单顶部用「AI编辑」。也可直接粘贴 YAML/JSON，不调用模型。
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
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={() => void generate(false)} disabled={saving || !nl.trim()}>
              生成预览
            </Button>
            <Button onClick={() => void generate(true)} disabled={saving || !nl.trim()}>
              生成并保存
            </Button>
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
                  {rule.name} · {rule.exclude ? "排除" : (rule.when?.types || []).join("/")} · {(rule.when?.glob || []).join(", ")}
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
            <Button size="sm" onClick={() => openEditor(null, blankRule())}>
              <PlusIcon data-icon="inline-start" />
              手动添加
            </Button>
          </div>
          {rules.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              {info?.record_all === false
                ? "还没有规则。当前只记录命中正向规则的文件，添加规则后才会出现文件变化。"
                : "还没有规则。默认会记录全部文件变化。手动添加时可切换为排除规则以停止监听某类文件；正向规则命中后写入 jobs 邮箱。"}
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {rules.map((rule, index) => {
                const activeLabel = formatActive(rule.when?.active)
                return (
                <div key={`${rule.name}-${index}`} className="flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="font-medium">{rule.name}</div>
                      <Badge variant={rule.enabled === false ? "secondary" : "default"}>
                        {rule.enabled === false ? "停用" : "启用"}
                      </Badge>
                      {rule.exclude ? (
                        <Badge variant="outline" className="border-rose-300 text-rose-700 dark:border-rose-800 dark:text-rose-400">
                          排除
                        </Badge>
                      ) : (
                        (rule.then || []).map((action, actionIndex) => (
                          <Badge key={actionIndex} variant="outline">
                            {action.notify ? "通知" : "agent"}
                          </Badge>
                        ))
                      )}
                      {rule.exclude ? null : (rule.then || []).some((action) => hasDingtalk(action.notify)) ? (
                        <Badge variant="outline">钉钉</Badge>
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
                      {rule.when?.regex ? ` · re ${rule.when.regex}` : ""}
                      {rule.when?.cooldown_seconds ? ` · 冷却 ${rule.when.cooldown_seconds}s` : ""}
                      {activeLabel ? ` · ${activeLabel}` : ""}
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
                      onClick={() => openEditor(index, rule)}
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
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={!!editor}
        onOpenChange={(open) => {
          if (!open) {
            setEditor(null)
            setAiEdit("")
            setAiNotes([])
          }
        }}
      >
        <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden sm:max-w-2xl">
          <DialogHeader className="shrink-0">
            <DialogTitle>{editor?.index == null ? "添加规则" : "编辑规则"}</DialogTitle>
            <DialogDescription>
              各输入框下方有说明和示例。可在「规则类型」里切换通知/任务或排除监听。模板可用 {"{{path}} {{type}} {{filename}}"}。
            </DialogDescription>
          </DialogHeader>
          {editor ? (
            <>
              <div className="shrink-0 grid gap-1.5 border-b pb-3">
                <Label htmlFor="rule-ai-edit">AI编辑</Label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Input
                    id="rule-ai-edit"
                    value={aiEdit}
                    onChange={(event) => setAiEdit(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                        event.preventDefault()
                        void applyAiEdit()
                      }
                    }}
                    placeholder="用自然语言改这条规则，例如：改成只匹配 markdown，冷却 30 秒"
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    className="shrink-0"
                    onClick={() => void applyAiEdit()}
                    disabled={saving || !aiEdit.trim()}
                  >
                    <SparklesIcon data-icon="inline-start" />
                    应用
                  </Button>
                </div>
                {error ? <p className="text-sm text-destructive">{error}</p> : null}
                {keySet === false ? (
                  <p className="text-xs text-muted-foreground">
                    请先在设置页填写 API Key。粘贴 YAML 或 JSON 不受影响。
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    应用后会填入下方表单，确认无误再点保存。也可粘贴 YAML/JSON。
                  </p>
                )}
                {aiNotes.length ? (
                  <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                    {aiNotes.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <div className="min-h-0 overflow-y-auto pr-1">
                <RuleForm
                  key={`${editor.index}-${editor.rev}`}
                  initial={editor.rule}
                  channels={channels}
                  submitting={saving}
                  onSubmit={upsertRule}
                  onCancel={() => setEditor(null)}
                />
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </TaskChrome>
  )
}
