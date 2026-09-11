import { useEffect, useState } from "react"
import { ArrowLeftIcon, Settings2Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, navigate, type LlmSettings } from "@/lib/api"

export function SettingsPage() {
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1")
  const [model, setModel] = useState("gpt-4o-mini")
  const [apiKey, setApiKey] = useState("")
  const [masked, setMasked] = useState("")
  const [keySet, setKeySet] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function load() {
    const data = await api<{ llm: LlmSettings }>("/api/settings")
    setBaseUrl(data.llm.base_url || "https://api.openai.com/v1")
    setModel(data.llm.model || "gpt-4o-mini")
    setKeySet(!!data.llm.api_key_set)
    setMasked(data.llm.api_key_masked || "")
    setApiKey("")
  }

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "无法加载设置")
    })
  }, [])

  async function save(test: boolean) {
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      const data = await api<{ llm: LlmSettings; message?: string }>("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          llm: {
            base_url: baseUrl.trim(),
            model: model.trim(),
            api_key: apiKey,
          },
        }),
      })
      setKeySet(!!data.llm.api_key_set)
      setMasked(data.llm.api_key_masked || "")
      setApiKey("")
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
      await api("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ llm: { clear_api_key: true } }),
      })
      setKeySet(false)
      setMasked("")
      setApiKey("")
      setMessage("已清除 API Key")
    } catch (err) {
      setError(err instanceof Error ? err.message : "清除失败")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="font-heading flex items-center gap-2 text-2xl font-medium tracking-tight">
            <Settings2Icon className="size-5" />
            设置
          </h1>
          <p className="text-sm text-muted-foreground">自然语言生成规则会调用兼容 OpenAI 的 Chat Completions。Key 保存在本机状态目录，不会写入被监听的文件夹。</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => navigate("/")}>
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
          <CardDescription>填写 API Key 后，即可在任务的「监听规则」页用口语生成规则。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="base-url">接口地址（OpenAI 兼容）</Label>
            <Input
              id="base-url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://api.openai.com/v1"
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="model">模型</Label>
            <Input id="model" value={model} onChange={(event) => setModel(event.target.value)} placeholder="gpt-4o-mini" />
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
            <Button onClick={() => void save(false)} disabled={saving}>
              保存
            </Button>
            <Button variant="outline" onClick={() => void save(true)} disabled={saving}>
              保存并测试连接
            </Button>
            <Button variant="ghost" onClick={() => void clearKey()} disabled={saving || !keySet}>
              清除 Key
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
