import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { TYPE_LABEL, type WatchRule } from "@/lib/api"

const TYPE_IDS = ["created", "modified", "deleted", "moved"] as const

function splitList(value: string) {
  return value
    .split(/[,，\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function RuleForm({
  initial,
  submitting,
  onSubmit,
  onCancel,
}: {
  initial: WatchRule
  submitting?: boolean
  onSubmit: (rule: WatchRule) => void
  onCancel: () => void
}) {
  const notify0 = initial.then?.find((item) => item.notify)?.notify
  const agent0 = initial.then?.find((item) => item.agent)?.agent
  const [name, setName] = useState(initial.name || "")
  const [enabled, setEnabled] = useState(initial.enabled !== false)
  const [types, setTypes] = useState<string[]>(initial.when?.types?.length ? initial.when.types : ["created", "modified"])
  const [glob, setGlob] = useState((initial.when?.glob || []).join(", "))
  const [regex, setRegex] = useState(initial.when?.regex || "")
  const [isDir, setIsDir] = useState(
    initial.when?.is_dir === true ? "dir" : initial.when?.is_dir === false ? "file" : "any",
  )
  const [cooldown, setCooldown] = useState(String(initial.when?.cooldown_seconds || 0))
  const [minSize, setMinSize] = useState(
    initial.when?.min_size_bytes != null ? String(initial.when.min_size_bytes) : "",
  )
  const [title, setTitle] = useState(notify0?.title || "文件有变化")
  const [message, setMessage] = useState(notify0?.message || "{{type}}: {{path}}")
  const [webhook, setWebhook] = useState(notify0?.webhook || "")
  const [mailbox, setMailbox] = useState(notify0?.mailbox !== false)
  const [dingWebhook, setDingWebhook] = useState(notify0?.dingtalk?.webhook || "")
  const [dingSecret, setDingSecret] = useState(notify0?.dingtalk?.secret || "")
  const [taskPrompt, setTaskPrompt] = useState(() => {
    if (!agent0) return ""
    if (agent0.runner === "command" || agent0.runner === "cursor_sdk") return ""
    return agent0.prompt || ""
  })

  const canSubmit = useMemo(() => types.length > 0, [types])

  function submit() {
    const then: WatchRule["then"] = [
      {
        notify: {
          title: title.trim() || "文件有变化",
          message: message.trim() || "{{type}}: {{path}}",
          webhook: webhook.trim() || null,
          mailbox,
          dingtalk: dingWebhook.trim()
            ? {
                webhook: dingWebhook.trim(),
                secret: dingSecret.trim() || null,
                interval_seconds: 60,
              }
            : null,
        },
      },
    ]
    const task = taskPrompt.trim()
    if (task) {
      then.push({
        agent: {
          runner: "builtin",
          prompt: task,
          command: null,
          timeout_seconds: 600,
          max_steps: 24,
        },
      })
    }
    const globList = splitList(glob)
    onSubmit({
      name: name.trim() || "rule",
      enabled,
      when: {
        types,
        glob: globList.length ? globList : ["**/*"],
        regex: regex.trim() || null,
        is_dir: isDir === "dir" ? true : isDir === "file" ? false : null,
        cooldown_seconds: Number(cooldown) || 0,
        min_size_bytes: minSize.trim() ? Number(minSize) : null,
      },
      then,
    })
  }

  return (
    <div className="grid gap-4">
      <div className="grid gap-1.5">
        <Label htmlFor="rule-name">规则名</Label>
        <Input id="rule-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="new-markdown" />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Switch checked={enabled} onCheckedChange={setEnabled} />
        启用
      </label>

      <div className="grid gap-1.5">
        <Label>事件类型</Label>
        <ToggleGroup
          type="multiple"
          variant="outline"
          size="sm"
          value={types}
          onValueChange={(value) => {
            if (value.length) setTypes(value)
          }}
          className="flex flex-wrap justify-start"
        >
          {TYPE_IDS.map((id) => (
            <ToggleGroupItem key={id} value={id}>
              {TYPE_LABEL[id] || id}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="rule-glob">Glob（逗号分隔，递归用 **/*.md）</Label>
        <Input
          id="rule-glob"
          value={glob}
          onChange={(event) => setGlob(event.target.value)}
          placeholder="**/*.md"
          className="font-mono"
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="rule-regex">正则（可选）</Label>
        <Input id="rule-regex" value={regex} onChange={(event) => setRegex(event.target.value)} className="font-mono" />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="grid gap-1.5">
          <Label>路径类型</Label>
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={isDir}
            onValueChange={(value) => {
              if (value) setIsDir(value)
            }}
          >
            <ToggleGroupItem value="any">任意</ToggleGroupItem>
            <ToggleGroupItem value="file">文件</ToggleGroupItem>
            <ToggleGroupItem value="dir">目录</ToggleGroupItem>
          </ToggleGroup>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="rule-cooldown">冷却（秒）</Label>
          <Input id="rule-cooldown" type="number" min={0} value={cooldown} onChange={(event) => setCooldown(event.target.value)} />
        </div>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="rule-minsize">最小字节（可选）</Label>
        <Input id="rule-minsize" type="number" min={0} value={minSize} onChange={(event) => setMinSize(event.target.value)} />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="rule-title">通知标题</Label>
        <Input id="rule-title" value={title} onChange={(event) => setTitle(event.target.value)} />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="rule-message">通知内容</Label>
        <Textarea id="rule-message" value={message} onChange={(event) => setMessage(event.target.value)} rows={2} />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="rule-webhook">Webhook（可选，立即 POST）</Label>
        <Input
          id="rule-webhook"
          value={webhook}
          onChange={(event) => setWebhook(event.target.value)}
          placeholder="https://"
          className="font-mono"
        />
      </div>
      <div className="grid gap-3 rounded-lg border p-3">
        <div className="text-sm font-medium">钉钉群（可选，按分钟汇总）</div>
        <div className="grid gap-1.5">
          <Label htmlFor="rule-ding-webhook">钉钉 Webhook</Label>
          <Input
            id="rule-ding-webhook"
            value={dingWebhook}
            onChange={(event) => setDingWebhook(event.target.value)}
            placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
            className="font-mono"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="rule-ding-secret">钉钉 SEC</Label>
          <Input
            id="rule-ding-secret"
            type="password"
            value={dingSecret}
            onChange={(event) => setDingSecret(event.target.value)}
            placeholder="SECxxxxxxxx"
            autoComplete="off"
            className="font-mono"
          />
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={mailbox} onCheckedChange={(checked) => setMailbox(!!checked)} />
        写入 jobs 邮箱
      </label>

      <div className="grid gap-1.5">
        <Label htmlFor="rule-task">任务要求（可选）</Label>
        <Textarea
          id="rule-task"
          value={taskPrompt}
          onChange={(event) => setTaskPrompt(event.target.value)}
          rows={4}
          placeholder={
            "填写后，规则命中时会启动内置智能体（调用设置页 LLM）。\n例如：对 docs 下所有 .md 按参考格式重写。本次触发：{{type}} {{path}}"
          }
        />
        <p className="text-xs text-muted-foreground">
          留空则只监听/通知；非空则 runner=builtin，可用 {"{{path}}"} {"{{filename}}"} {"{{type}}"} 等模板变量。
        </p>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="outline" type="button" onClick={onCancel}>
          取消
        </Button>
        <Button type="button" onClick={submit} disabled={!canSubmit || submitting}>
          保存规则
        </Button>
      </div>
    </div>
  )
}
