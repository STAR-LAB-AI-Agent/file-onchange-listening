import { useEffect, useMemo, useState } from "react"
import { cn } from "cn"
import { CheckIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import {
  TYPE_LABEL,
  WEEKDAY_IDS,
  WEEKDAY_LABEL,
  api,
  dingtalkSelection,
  navigate,
  normalizeActive,
  type AppSettings,
  type DingTalkChannel,
  type WatchRule,
} from "@/lib/api"

const TYPE_IDS = ["created", "modified", "deleted", "moved"] as const

const EVENT_TYPE_ON_CLASS: Record<(typeof TYPE_IDS)[number], string> = {
  created:
    "data-[state=on]:border-emerald-600 data-[state=on]:bg-emerald-600 data-[state=on]:text-white data-[state=on]:hover:border-emerald-600 data-[state=on]:hover:bg-emerald-600 data-[state=on]:hover:text-white dark:data-[state=on]:border-emerald-500 dark:data-[state=on]:bg-emerald-500 dark:data-[state=on]:hover:border-emerald-500 dark:data-[state=on]:hover:bg-emerald-500",
  modified:
    "data-[state=on]:border-amber-700 data-[state=on]:bg-amber-700 data-[state=on]:text-white data-[state=on]:hover:border-amber-700 data-[state=on]:hover:bg-amber-700 data-[state=on]:hover:text-white dark:data-[state=on]:border-amber-500 dark:data-[state=on]:bg-amber-500 dark:data-[state=on]:hover:border-amber-500 dark:data-[state=on]:hover:bg-amber-500",
  deleted:
    "data-[state=on]:border-rose-600 data-[state=on]:bg-rose-600 data-[state=on]:text-white data-[state=on]:hover:border-rose-600 data-[state=on]:hover:bg-rose-600 data-[state=on]:hover:text-white dark:data-[state=on]:border-rose-500 dark:data-[state=on]:bg-rose-500 dark:data-[state=on]:hover:border-rose-500 dark:data-[state=on]:hover:bg-rose-500",
  moved:
    "data-[state=on]:border-violet-600 data-[state=on]:bg-violet-600 data-[state=on]:text-white data-[state=on]:hover:border-violet-600 data-[state=on]:hover:bg-violet-600 data-[state=on]:hover:text-white dark:data-[state=on]:border-violet-500 dark:data-[state=on]:bg-violet-500 dark:data-[state=on]:hover:border-violet-500 dark:data-[state=on]:hover:bg-violet-500",
}

function splitList(value: string) {
  return value
    .split(/[,，\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function FieldHint({ children }: { children: React.ReactNode }) {
  return <p className="text-xs leading-relaxed text-muted-foreground">{children}</p>
}

export function RuleForm({
  initial,
  channels: channelsProp,
  submitting,
  onSubmit,
  onCancel,
}: {
  initial: WatchRule
  channels?: DingTalkChannel[]
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
  const initialActive = normalizeActive(initial.when?.active)
  const [activeStart, setActiveStart] = useState(initialActive?.start || "")
  const [activeEnd, setActiveEnd] = useState(initialActive?.end === "24:00" ? "" : initialActive?.end || "")
  const [activeDays, setActiveDays] = useState<string[]>(initialActive?.days || [])
  const [title, setTitle] = useState(notify0?.title || "文件有变化")
  const [message, setMessage] = useState(notify0?.message || "{{type}}: {{path}}")
  const [webhook, setWebhook] = useState(notify0?.webhook || "")
  const [mailbox, setMailbox] = useState(notify0?.mailbox !== false)
  const [channels, setChannels] = useState<DingTalkChannel[]>(channelsProp || [])
  const [dingChannel, setDingChannel] = useState(() => dingtalkSelection(notify0?.dingtalk))
  const legacyDing =
    notify0?.dingtalk && typeof notify0.dingtalk === "object"
      ? {
          webhook: notify0.dingtalk.webhook || "",
          secret: notify0.dingtalk.secret || "",
          interval_seconds: notify0.dingtalk.interval_seconds || 60,
        }
      : null
  const [taskPrompt, setTaskPrompt] = useState(() => {
    if (!agent0) return ""
    if (agent0.runner === "command" || agent0.runner === "cursor_sdk") return ""
    return agent0.prompt || ""
  })

  const canSubmit = useMemo(() => types.length > 0, [types])

  useEffect(() => {
    function apply(next: DingTalkChannel[]) {
      setChannels(next)
      setDingChannel((current) => {
        if (current === "*" && next[0]?.id) return next[0].id
        return current
      })
    }
    if (channelsProp && channelsProp.length) {
      apply(channelsProp)
      return
    }
    void api<AppSettings>("/api/settings")
      .then((data) => apply(data.dingtalk?.channels || []))
      .catch(() => setChannels([]))
  }, [channelsProp])

  function submit() {
    const then: WatchRule["then"] = [
      {
        notify: {
          title: title.trim() || "文件有变化",
          message: message.trim() || "{{type}}: {{path}}",
          webhook: webhook.trim() || null,
          mailbox,
          dingtalk:
            dingChannel === "__legacy__" && legacyDing?.webhook
              ? {
                  webhook: legacyDing.webhook,
                  secret: legacyDing.secret || null,
                  interval_seconds: legacyDing.interval_seconds || 60,
                }
              : dingChannel === "*"
                ? true
                : dingChannel
                  ? { channel: dingChannel }
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
    const days = activeDays.length === 7 ? [] : activeDays
    const active =
      !activeStart && !activeEnd && days.length === 0
        ? null
        : {
            start: activeStart || null,
            end: activeEnd || null,
            days,
          }
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
        active,
      },
      then,
    })
  }

  return (
    <div className="grid gap-4">
      <div className="grid gap-1.5">
        <Label htmlFor="rule-name">规则名</Label>
        <Input id="rule-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="new-markdown" />
        <FieldHint>同一任务内不要重名，仅用于列表识别。例：new-markdown、docs-rewrite</FieldHint>
      </div>
      <div className="grid gap-1.5">
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={enabled} onCheckedChange={setEnabled} />
          启用
        </label>
        <FieldHint>关闭后规则仍保存在配置中，但不会命中。</FieldHint>
      </div>

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
            <ToggleGroupItem
              key={id}
              value={id}
              className={cn(
                "min-w-16 gap-1 border border-input bg-background px-3 font-normal text-muted-foreground shadow-none",
                "hover:bg-muted hover:text-foreground",
                "data-[state=on]:font-medium data-[state=on]:shadow-sm",
                EVENT_TYPE_ON_CLASS[id],
              )}
            >
              {types.includes(id) ? <CheckIcon className="size-3.5" /> : null}
              {TYPE_LABEL[id] || id}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <FieldHint>至少选一项。监听保存文档时一般选「新建」和「修改」。</FieldHint>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="rule-glob">Glob</Label>
        <Input
          id="rule-glob"
          value={glob}
          onChange={(event) => setGlob(event.target.value)}
          placeholder="**/*.md, docs/**/*.txt"
          className="font-mono"
        />
        <FieldHint>
          相对监听根目录匹配，多项用逗号分隔。只写 *.md 不会进子目录。例：{"**/*.md"} 匹配全部 markdown。
        </FieldHint>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="rule-regex">正则（可选）</Label>
        <Input
          id="rule-regex"
          value={regex}
          onChange={(event) => setRegex(event.target.value)}
          placeholder={"^docs/.*\\.md$"}
          className="font-mono"
        />
        <FieldHint>对相对路径再过滤，需同时满足 glob。留空则不过滤。例：{"^notes/.*\\.md$"}</FieldHint>
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
          <FieldHint>「文件」忽略文件夹事件；「目录」只匹配文件夹。</FieldHint>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="rule-cooldown">冷却（秒）</Label>
          <Input
            id="rule-cooldown"
            type="number"
            min={0}
            value={cooldown}
            onChange={(event) => setCooldown(event.target.value)}
            placeholder="30"
          />
          <FieldHint>同一路径在间隔内重复变化只触发一次。0 表示不限制。例：30</FieldHint>
        </div>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="rule-minsize">最小字节（可选）</Label>
        <Input
          id="rule-minsize"
          type="number"
          min={0}
          value={minSize}
          onChange={(event) => setMinSize(event.target.value)}
          placeholder="1024"
        />
        <FieldHint>小于该大小的文件不命中，留空不限制。例：1024 表示忽略 1KB 以下文件。</FieldHint>
      </div>

      <div className="grid gap-1.5">
        <Label>生效时间</Label>
        <div className="grid grid-cols-2 gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="rule-active-start" className="text-xs font-normal text-muted-foreground">
              开始
            </Label>
            <Input
              id="rule-active-start"
              type="time"
              value={activeStart}
              onChange={(event) => setActiveStart(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="rule-active-end" className="text-xs font-normal text-muted-foreground">
              结束
            </Label>
            <Input
              id="rule-active-end"
              type="time"
              value={activeEnd}
              onChange={(event) => setActiveEnd(event.target.value)}
            />
          </div>
        </div>
        <ToggleGroup
          type="multiple"
          variant="outline"
          size="sm"
          value={activeDays}
          onValueChange={setActiveDays}
          className="flex flex-wrap justify-start"
        >
          {WEEKDAY_IDS.map((id) => (
            <ToggleGroupItem key={id} value={id} className="min-w-8 px-2 font-normal">
              {WEEKDAY_LABEL[id]}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <FieldHint>
          按本机本地时间。起止和星期都留空则一直生效。结束早于开始表示跨天，例如 22:00–06:00。不选星期表示每天。
        </FieldHint>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="rule-title">通知标题</Label>
        <Input
          id="rule-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Markdown 有变化"
        />
        <FieldHint>jobs / 推送里显示的标题，可用模板变量。例：Markdown 有变化</FieldHint>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="rule-message">通知内容</Label>
        <Textarea
          id="rule-message"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={2}
          placeholder={"{{type}}: {{path}}"}
          className="font-mono"
        />
        <FieldHint>
          可用 {"{{path}}"} {"{{filename}}"} {"{{type}}"} {"{{watch_id}}"} {"{{ts}}"} {"{{old_path}}"}。例：
          {"{{type}}: {{path}}"}
        </FieldHint>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="rule-webhook">Webhook（可选）</Label>
        <Input
          id="rule-webhook"
          value={webhook}
          onChange={(event) => setWebhook(event.target.value)}
          placeholder="https://example.com/hook"
          className="font-mono"
        />
        <FieldHint>命中后立刻 POST 一条 JSON。钉钉请用下方渠道。例：https://example.com/hook</FieldHint>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="rule-dingtalk">钉钉群</Label>
        <NativeSelect
          id="rule-dingtalk"
          value={dingChannel}
          onChange={(event) => setDingChannel(event.target.value)}
        >
          <option value="">不推送</option>
          {channels.map((channel) => (
            <option key={channel.id} value={channel.id}>
              {channel.name || channel.id}
            </option>
          ))}
          {dingChannel === "*" ? <option value="*">默认渠道</option> : null}
          {dingChannel === "__legacy__" ? <option value="__legacy__">规则内配置（请改选设置中的机器人）</option> : null}
        </NativeSelect>
        {channels.length === 0 ? (
          <FieldHint>
            命中后按分钟汇总推送，无变化不发送。请先到{" "}
            <button type="button" className="underline" onClick={() => navigate("/settings")}>
              设置
            </button>{" "}
            添加机器人，再从这里选择。
          </FieldHint>
        ) : (
          <FieldHint>命中后按分钟汇总推到所选机器人，无变化不发送。选「不推送」则只走通知/任务。</FieldHint>
        )}
      </div>
      <div className="grid gap-1.5">
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={mailbox} onCheckedChange={(checked) => setMailbox(!!checked)} />
          写入 jobs 邮箱
        </label>
        <FieldHint>勾选后命中记录写入 jobs 流，可用 wait --stream jobs 消费。</FieldHint>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="rule-task">任务要求（可选）</Label>
        <Textarea
          id="rule-task"
          value={taskPrompt}
          onChange={(event) => setTaskPrompt(event.target.value)}
          rows={4}
          placeholder={"工作区是监听根目录。对 docs 下所有 .md 按参考格式重写。本次触发：{{type}} {{path}}"}
        />
        <FieldHint>
          留空则只通知；填写后会启动内置智能体（调用设置页 LLM）。例：对 docs 下所有 .md 按参考格式重写。本次触发：
          {"{{type}} {{path}}"}
        </FieldHint>
      </div>

      <div className="flex w-full justify-end gap-2 border-t pt-3">
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
