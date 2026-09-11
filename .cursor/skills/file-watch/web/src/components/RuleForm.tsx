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
  const [useAgent, setUseAgent] = useState(!!agent0)
  const [runner, setRunner] = useState(agent0?.runner || "command")
  const [command, setCommand] = useState((agent0?.command || []).join(" "))
  const [prompt, setPrompt] = useState(agent0?.prompt || "文件事件 {{type}}：{{path}}\n请处理该文件。")

  const canSubmit = useMemo(() => types.length > 0, [types])

  function submit() {
    const then: WatchRule["then"] = [
      {
        notify: {
          title: title.trim() || "文件有变化",
          message: message.trim() || "{{type}}: {{path}}",
          webhook: webhook.trim() || null,
          mailbox,
        },
      },
    ]
    if (useAgent) {
      const argv = command.trim() ? command.trim().split(/\s+/) : null
      then.push({
        agent: {
          runner: runner === "cursor_sdk" ? "cursor_sdk" : "command",
          prompt,
          command: runner === "command" ? argv : argv,
          timeout_seconds: 600,
        },
      })
    }
    const globList = splitList(glob)
    onSubmit({
      name: name.trim() || "rule",
      enabled,
      when: {
        types,
        glob: globList,
        regex: regex.trim() || null,
        is_dir: isDir === "any" ? null : isDir === "dir",
        min_size_bytes: minSize.trim() ? Number(minSize) : null,
        cooldown_seconds: Number(cooldown) || 0,
      },
      then,
    })
  }

  return (
    <div className="grid max-h-[70vh] gap-4 overflow-y-auto pr-1">
      <div className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
        <div className="grid gap-1.5">
          <Label htmlFor="rule-name">规则名</Label>
          <Input id="rule-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="new-markdown" />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={enabled} onCheckedChange={setEnabled} />
          启用
        </label>
      </div>

      <div className="grid gap-1.5">
        <Label>事件类型</Label>
        <div className="flex flex-wrap gap-3">
          {TYPE_IDS.map((id) => (
            <label key={id} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={types.includes(id)}
                onCheckedChange={(checked) => {
                  setTypes((prev) => {
                    if (checked) return TYPE_IDS.filter((item) => item === id || prev.includes(item))
                    return prev.filter((item) => item !== id)
                  })
                }}
              />
              {TYPE_LABEL[id]}
            </label>
          ))}
        </div>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="rule-glob">glob（逗号分隔，递归用 **/*.md）</Label>
        <Input
          id="rule-glob"
          value={glob}
          onChange={(event) => setGlob(event.target.value)}
          placeholder="**/*.md, **/*.txt"
          className="font-mono"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="grid gap-1.5">
          <Label>匹配对象</Label>
          <ToggleGroup type="single" variant="outline" size="sm" value={isDir} onValueChange={(value) => value && setIsDir(value)}>
            <ToggleGroupItem value="file">文件</ToggleGroupItem>
            <ToggleGroupItem value="dir">目录</ToggleGroupItem>
            <ToggleGroupItem value="any">不限</ToggleGroupItem>
          </ToggleGroup>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="rule-cooldown">冷却（秒）</Label>
          <Input id="rule-cooldown" type="number" min={0} value={cooldown} onChange={(event) => setCooldown(event.target.value)} />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="rule-size">最小字节（可选）</Label>
          <Input id="rule-size" type="number" min={0} value={minSize} onChange={(event) => setMinSize(event.target.value)} />
        </div>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="rule-regex">正则（可选）</Label>
        <Input id="rule-regex" value={regex} onChange={(event) => setRegex(event.target.value)} className="font-mono" />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor="rule-title">通知标题</Label>
          <Input id="rule-title" value={title} onChange={(event) => setTitle(event.target.value)} />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="rule-webhook">Webhook（可选）</Label>
          <Input id="rule-webhook" value={webhook} onChange={(event) => setWebhook(event.target.value)} placeholder="https://" />
        </div>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="rule-message">通知内容</Label>
        <Input id="rule-message" value={message} onChange={(event) => setMessage(event.target.value)} className="font-mono" />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={mailbox} onCheckedChange={(checked) => setMailbox(!!checked)} />
        写入 jobs 邮箱
      </label>

      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={useAgent} onCheckedChange={(checked) => setUseAgent(!!checked)} />
        同时启动智能体
      </label>
      {useAgent ? (
        <div className="grid gap-3 rounded-lg border p-3">
          <ToggleGroup type="single" variant="outline" size="sm" value={runner} onValueChange={(value) => {
            if (value === "command" || value === "cursor_sdk") setRunner(value)
          }}>
            <ToggleGroupItem value="command">command</ToggleGroupItem>
            <ToggleGroupItem value="cursor_sdk">cursor_sdk</ToggleGroupItem>
          </ToggleGroup>
          <div className="grid gap-1.5">
            <Label htmlFor="rule-command">命令（空格分隔 argv）</Label>
            <Input
              id="rule-command"
              value={command}
              onChange={(event) => setCommand(event.target.value)}
              placeholder="python scripts/echo_agent.py"
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="rule-prompt">Prompt</Label>
            <Textarea id="rule-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={3} />
          </div>
        </div>
      ) : null}

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
