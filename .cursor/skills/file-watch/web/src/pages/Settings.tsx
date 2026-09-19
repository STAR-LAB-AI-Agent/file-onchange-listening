import { useEffect, useRef, useState } from "react"
import { ArrowLeftIcon, PlusIcon, Settings2Icon, Trash2Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { api, navigate, type AppSettings, type DingTalkChannel, type LlmWireApi } from "@/lib/api"
import {
  endpointCatalogButton,
  endpointHelpDescription,
  endpointHelpTitle,
  endpointHintsFor,
  firstExampleModel,
  type LlmEndpointHint,
} from "@/lib/llmEndpoints"

const DEFAULT_DEBOUNCE_MS = 400
const DEFAULT_LINE_DIFF_QUIET_MS = 30_000
const DEFAULT_LINE_DIFF_MAX_BYTES = 256 * 1024
const OPENAI_DEFAULT_URL = "https://api.openai.com/v1"
const ANTHROPIC_DEFAULT_URL = "https://api.anthropic.com/v1"

function parseWireApi(value: string | undefined): LlmWireApi {
  if (value === "responses" || value === "anthropic" || value === "chat") return value
  return "chat"
}

function wireApiLabel(wire: LlmWireApi): string {
  if (wire === "anthropic") return "Anthropic Messages"
  if (wire === "responses") return "OpenAI Responses"
  return "OpenAI Chat Completions"
}

function defaultBaseUrl(wire: LlmWireApi): string {
  return wire === "anthropic" ? ANTHROPIC_DEFAULT_URL : OPENAI_DEFAULT_URL
}

function defaultModel(wire: LlmWireApi): string {
  if (wire === "anthropic") return "claude-sonnet-4-5"
  if (wire === "responses") return "gpt-4.1"
  return "gpt-4o-mini"
}

function wireApiHint(wire: LlmWireApi): string {
  if (wire === "anthropic") {
    return "请求会 POST 到接口地址后的 /messages：system 单独发送，工具为 tool_use / tool_result。"
  }
  if (wire === "responses") {
    return "请求会 POST 到接口地址后的 /responses：system 进 instructions，工具为 function / function_call_output。"
  }
  return "请求会 POST 到接口地址后的 /chat/completions（兼容 OpenAI 的对话接口）。"
}

type ChannelDraft = {
  key: string
  id: string
  name: string
  webhook: string
  secret: string
  secret_set: boolean
  secret_masked: string
  interval_seconds: string
}

function toDraft(channel: DingTalkChannel, index: number): ChannelDraft {
  return {
    key: channel.id || `new-${index}`,
    id: channel.id || "",
    name: channel.name || "",
    webhook: channel.webhook || "",
    secret: "",
    secret_set: !!channel.secret_set,
    secret_masked: channel.secret_masked || "",
    interval_seconds: String(channel.interval_seconds ?? 60),
  }
}

function blankChannel(): ChannelDraft {
  return {
    key: `new-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    id: "",
    name: "",
    webhook: "",
    secret: "",
    secret_set: false,
    secret_masked: "",
    interval_seconds: "60",
  }
}

export function SettingsPage() {
  const [wireApi, setWireApi] = useState<LlmWireApi>("chat")
  const [baseUrl, setBaseUrl] = useState(OPENAI_DEFAULT_URL)
  const [model, setModel] = useState("gpt-4o-mini")
  const [apiKey, setApiKey] = useState("")
  const [masked, setMasked] = useState("")
  const [keySet, setKeySet] = useState(false)
  const [channels, setChannels] = useState<ChannelDraft[]>([])
  const [debounceMs, setDebounceMs] = useState(String(DEFAULT_DEBOUNCE_MS))
  const [lineDiffQuietSeconds, setLineDiffQuietSeconds] = useState(String(DEFAULT_LINE_DIFF_QUIET_MS / 1000))
  const [lineDiffMaxKb, setLineDiffMaxKb] = useState(String(DEFAULT_LINE_DIFF_MAX_BYTES / 1024))
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [testingKey, setTestingKey] = useState<string | null>(null)
  const [endpointHelpOpen, setEndpointHelpOpen] = useState(false)
  const [dingReady, setDingReady] = useState(false)
  const channelsRef = useRef(channels)
  channelsRef.current = channels
  const loadGen = useRef(0)
  const dingDirty = useRef(false)

  function applyWatch(data: AppSettings) {
    const debounce = data.watch?.debounce_ms
    const quiet = data.watch?.line_diff_quiet_ms
    const maxBytes = data.watch?.line_diff_max_bytes
    setDebounceMs(String(debounce ?? DEFAULT_DEBOUNCE_MS))
    setLineDiffQuietSeconds(String((quiet ?? DEFAULT_LINE_DIFF_QUIET_MS) / 1000))
    setLineDiffMaxKb(String((maxBytes ?? DEFAULT_LINE_DIFF_MAX_BYTES) / 1024))
  }

  function applyLlm(data: AppSettings) {
    const wire = parseWireApi(data.llm.wire_api)
    setWireApi(wire)
    setBaseUrl(data.llm.base_url || defaultBaseUrl(wire))
    setModel(data.llm.model || defaultModel(wire))
    setKeySet(!!data.llm.api_key_set)
    setMasked(data.llm.api_key_masked || "")
    setApiKey("")
  }

  function changeWireApi(next: LlmWireApi) {
    const prevUrl = defaultBaseUrl(wireApi)
    const nextUrl = defaultBaseUrl(next)
    if (!baseUrl.trim() || baseUrl.trim().replace(/\/+$/, "") === prevUrl) {
      setBaseUrl(nextUrl)
    }
    const prevModel = defaultModel(wireApi)
    if (!model.trim() || model.trim() === prevModel) {
      setModel(defaultModel(next))
    }
    setWireApi(next)
  }

  function fillEndpoint(item: LlmEndpointHint) {
    setBaseUrl(item.endpoint)
    const example = firstExampleModel(item.models)
    if (example) setModel(example)
    setEndpointHelpOpen(false)
  }

  function applyDingtalk(data: AppSettings, force = false) {
    const incoming = data.dingtalk?.channels
    if (!Array.isArray(incoming)) {
      if (!force && dingDirty.current) return
      if (!force) setChannels([])
      return
    }
    if (!force && dingDirty.current) return
    setChannels(incoming.map(toDraft))
  }

  useEffect(() => {
    const gen = ++loadGen.current
    void api<AppSettings>("/api/settings")
      .then((data) => {
        if (gen !== loadGen.current) return
        applyLlm(data)
        applyDingtalk(data)
        applyWatch(data)
        setDingReady(true)
      })
      .catch((err: unknown) => {
        if (gen !== loadGen.current) return
        setError(err instanceof Error ? err.message : "无法加载设置")
        setDingReady(true)
      })
  }, [])

  async function saveLlm(test: boolean) {
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      const data = await api<AppSettings & { message?: string }>("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          llm: {
            wire_api: wireApi,
            base_url: baseUrl.trim(),
            model: model.trim(),
            api_key: apiKey,
          },
        }),
      })
      applyLlm(data)
      if (test) {
        const ping = await api<{ message?: string }>("/api/settings/test", { method: "POST" })
        setMessage(ping.message || "LLM 连接正常")
      } else {
        setMessage(data.message || "设置已保存")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  async function clearKey() {
    setSaving(true)
    setError(null)
    try {
      const data = await api<AppSettings>("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ llm: { clear_api_key: true } }),
      })
      applyLlm(data)
      setMessage("已清除 API Key")
    } catch (err) {
      setError(err instanceof Error ? err.message : "清除失败")
    } finally {
      setSaving(false)
    }
  }

  async function saveDingtalk() {
    setSaving(true)
    setError(null)
    setMessage(null)
    loadGen.current += 1
    const snapshot = channelsRef.current
    try {
      const data = await api<AppSettings & { message?: string }>("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dingtalk: {
            channels: snapshot.map((item) => ({
              id: item.id || undefined,
              name: item.name.trim() || "钉钉群",
              webhook: item.webhook.trim(),
              secret: item.secret,
              interval_seconds: Number(item.interval_seconds) || 60,
            })),
          },
        }),
      })
      const saved = data.dingtalk?.channels
      if (snapshot.length > 0 && (!Array.isArray(saved) || saved.length === 0)) {
        setError("钉钉设置已提交，但响应里没有渠道。请刷新后检查，避免本地草稿被清空。")
        return
      }
      dingDirty.current = false
      applyDingtalk(data, true)
      setMessage(data.message || "钉钉设置已保存")
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  async function testDingtalk(channel: ChannelDraft) {
    const webhook = channel.webhook.trim()
    if (!webhook) {
      setError("请先填写钉钉 Webhook")
      setMessage(null)
      return
    }
    setTestingKey(channel.key)
    setError(null)
    setMessage(null)
    try {
      const ping = await api<{ message?: string }>("/api/settings/dingtalk/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: channel.id || undefined,
          name: channel.name.trim() || "钉钉群",
          webhook,
          secret: channel.secret,
        }),
      })
      setMessage(ping.message || "已发送测试消息")
    } catch (err) {
      setError(err instanceof Error ? err.message : "测试发送失败")
    } finally {
      setTestingKey(null)
    }
  }

  async function saveWatch() {
    const debounce = Number(debounceMs)
    const quietSeconds = Number(lineDiffQuietSeconds)
    if (!Number.isFinite(debounce) || debounce < 0 || !Number.isInteger(debounce)) {
      setError("事件入账间隔必须是大于等于 0 的整数毫秒")
      return
    }
    if (!Number.isFinite(quietSeconds) || quietSeconds < 0) {
      setError("行级快照等待必须大于等于 0 秒")
      return
    }
    const maxKb = Number(lineDiffMaxKb)
    if (!Number.isFinite(maxKb) || maxKb < 1 || !Number.isInteger(maxKb)) {
      setError("行级快照最大文件必须是大于等于 1 的整数 KB")
      return
    }
    const quietMs = Math.round(quietSeconds * 1000)
    const maxBytes = maxKb * 1024
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      const data = await api<AppSettings & { message?: string; applied_watchers?: unknown[] }>("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          watch: {
            debounce_ms: debounce,
            line_diff_quiet_ms: quietMs,
            line_diff_max_bytes: maxBytes,
          },
        }),
      })
      applyWatch(data)
      const applied = Array.isArray(data.applied_watchers) ? data.applied_watchers.length : 0
      setMessage(applied > 0 ? `监听时机已保存，已应用到 ${applied} 个任务` : data.message || "监听时机已保存")
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  function updateChannel(key: string, patch: Partial<ChannelDraft>) {
    dingDirty.current = true
    setChannels((current) => current.map((item) => (item.key === key ? { ...item, ...patch } : item)))
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="font-heading flex items-center gap-2 text-2xl font-medium tracking-tight">
            <Settings2Icon className="size-5" />
            设置
          </h1>
          <p className="text-sm text-muted-foreground">
            LLM 用于自然语言添加和编辑规则；钉钉机器人供规则下拉选择。事件入账、行级快照等待和最大文件也可在此调整。凭证保存在本机状态目录，不会写入被监听的文件夹。
          </p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => navigate("/")}>
          <ArrowLeftIcon data-icon="inline-start" />
          返回列表
        </Button>
      </header>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>无法完成操作</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {message ? (
        <Alert>
          <AlertTitle>已更新</AlertTitle>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>LLM</CardTitle>
          <CardDescription>填写 API Key 后，即可在任务的「监听规则」页用口语生成规则。按服务商选择协议。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="wire-api">接口协议</Label>
            <Select
              value={wireApi}
              onValueChange={(value) => {
                if (value === "chat" || value === "responses" || value === "anthropic") {
                  changeWireApi(value)
                }
              }}
            >
              <SelectTrigger id="wire-api">
                <SelectValue>{wireApiLabel(wireApi)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="chat">OpenAI Chat Completions</SelectItem>
                <SelectItem value="responses">OpenAI Responses</SelectItem>
                <SelectItem value="anthropic">Anthropic Messages</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs leading-relaxed text-muted-foreground">{wireApiHint(wireApi)}</p>
          </div>
          <div className="grid gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="base-url">接口地址</Label>
              <Button type="button" variant="ghost" size="sm" onClick={() => setEndpointHelpOpen(true)}>
                {endpointCatalogButton(wireApi)}
              </Button>
            </div>
            <Input
              id="base-url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={defaultBaseUrl(wireApi)}
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="model">模型</Label>
            <Input
              id="model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder={defaultModel(wireApi)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="api-key">API Key</Label>
            <Input
              id="api-key"
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={keySet ? `已保存 ${masked}，留空则不修改` : "sk-..."}
              autoComplete="off"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => void saveLlm(false)} disabled={saving}>
              保存
            </Button>
            <Button type="button" variant="outline" onClick={() => void saveLlm(true)} disabled={saving}>
              保存并测试连接
            </Button>
            <Button type="button" variant="ghost" onClick={() => void clearKey()} disabled={saving || !keySet}>
              清除 Key
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>监听时机</CardTitle>
          <CardDescription>
            事件入账：同一文件连续变化时，安静这么久再记一条。行级快照：入账后再等这么久才计算增减行；超过最大文件则跳过行级对比。保存后写入本机设置，并应用到已有任务。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="debounce-ms">事件入账（毫秒）</Label>
            <Input
              id="debounce-ms"
              type="number"
              min={0}
              step={1}
              value={debounceMs}
              onChange={(event) => setDebounceMs(event.target.value)}
              placeholder={String(DEFAULT_DEBOUNCE_MS)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="line-diff-quiet">行级快照（秒）</Label>
            <Input
              id="line-diff-quiet"
              type="number"
              min={0}
              step={0.1}
              value={lineDiffQuietSeconds}
              onChange={(event) => setLineDiffQuietSeconds(event.target.value)}
              placeholder={String(DEFAULT_LINE_DIFF_QUIET_MS / 1000)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="line-diff-max">行级快照最大文件（KB）</Label>
            <Input
              id="line-diff-max"
              type="number"
              min={1}
              step={1}
              value={lineDiffMaxKb}
              onChange={(event) => setLineDiffMaxKb(event.target.value)}
              placeholder={String(DEFAULT_LINE_DIFF_MAX_BYTES / 1024)}
            />
          </div>
          <div>
            <Button type="button" onClick={() => void saveWatch()} disabled={saving}>
              保存监听时机
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>钉钉推送</CardTitle>
          <CardDescription>
            在这里填写群机器人 Webhook 和 SEC。添加规则时只需从下拉栏选择要推送到哪个群。可用「发送测试」立刻往该群推一条消息，不必等文件变化。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {channels.length === 0 ? (
            <p className="text-sm text-muted-foreground">还没有钉钉机器人。添加后即可在规则里选择。</p>
          ) : (
            channels.map((channel, index) => (
              <div key={channel.key} className="grid gap-3 rounded-lg border p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm font-medium">机器人 {index + 1}</div>
                  <div className="flex flex-wrap items-center justify-end gap-1">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!dingReady || saving || testingKey !== null || !channel.webhook.trim()}
                      onClick={() => void testDingtalk(channel)}
                    >
                      {testingKey === channel.key ? "发送中…" : "发送测试"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={saving || testingKey !== null}
                      onClick={() => {
                        dingDirty.current = true
                        setChannels((current) => current.filter((item) => item.key !== channel.key))
                      }}
                    >
                      <Trash2Icon data-icon="inline-start" />
                      删除
                    </Button>
                  </div>
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor={`ding-name-${channel.key}`}>名称</Label>
                  <Input
                    id={`ding-name-${channel.key}`}
                    value={channel.name}
                    onChange={(event) => updateChannel(channel.key, { name: event.target.value })}
                    placeholder="工作群"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor={`ding-webhook-${channel.key}`}>Webhook</Label>
                  <Input
                    id={`ding-webhook-${channel.key}`}
                    value={channel.webhook}
                    onChange={(event) => updateChannel(channel.key, { webhook: event.target.value })}
                    placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
                    className="font-mono"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor={`ding-secret-${channel.key}`}>SEC 加签</Label>
                  <Input
                    id={`ding-secret-${channel.key}`}
                    type="password"
                    value={channel.secret}
                    onChange={(event) => updateChannel(channel.key, { secret: event.target.value })}
                    placeholder={channel.secret_set ? `已保存 ${channel.secret_masked}，留空则不修改` : "SECxxxxxxxx"}
                    autoComplete="off"
                    className="font-mono"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor={`ding-interval-${channel.key}`}>汇总间隔（秒）</Label>
                  <Input
                    id={`ding-interval-${channel.key}`}
                    type="number"
                    min={1}
                    value={channel.interval_seconds}
                    onChange={(event) => updateChannel(channel.key, { interval_seconds: event.target.value })}
                  />
                </div>
              </div>
            ))
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!dingReady || saving}
              onClick={() => {
                dingDirty.current = true
                setChannels((current) => [...current, blankChannel()])
              }}
            >
              <PlusIcon data-icon="inline-start" />
              添加机器人
            </Button>
            <Button type="button" onClick={() => void saveDingtalk()} disabled={!dingReady || saving}>
              保存钉钉设置
            </Button>
          </div>
        </CardContent>
      </Card>

      <Dialog open={endpointHelpOpen} onOpenChange={setEndpointHelpOpen}>
        <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden sm:max-w-2xl">
          <DialogHeader className="shrink-0">
            <DialogTitle>{endpointHelpTitle(wireApi)}</DialogTitle>
            <DialogDescription>{endpointHelpDescription(wireApi)}</DialogDescription>
          </DialogHeader>
          <div className="min-h-0 space-y-2 overflow-y-auto pr-1">
            {endpointHintsFor(wireApi).map((item) => (
              <div key={item.name} className="grid gap-2 rounded-lg border p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 space-y-1">
                    <div className="text-sm font-medium">{item.name}</div>
                    <div className="break-all font-mono text-xs text-muted-foreground">{item.endpoint}</div>
                  </div>
                  <Button type="button" variant="outline" size="sm" onClick={() => fillEndpoint(item)}>
                    填入
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">模型示例：{item.models}</p>
                <p className="text-xs text-muted-foreground">{item.note}</p>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
