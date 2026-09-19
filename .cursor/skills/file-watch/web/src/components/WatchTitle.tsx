import { useEffect, useRef, useState } from "react"
import { CheckIcon, PencilIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api, defaultTaskTitle, type WatcherInfo } from "@/lib/api"

export function WatchTitle({
  watchId,
  title,
  path,
  heading = false,
  onRenamed,
  onError,
}: {
  watchId: string
  title?: string | null
  path?: string | null
  heading?: boolean
  onRenamed?: (info: WatcherInfo) => void
  onError?: (message: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState("")
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const placeholder = defaultTaskTitle(path, watchId)
  const label = title || placeholder || watchId

  useEffect(() => {
    if (editing) inputRef.current?.select()
  }, [editing])

  async function save() {
    setSaving(true)
    try {
      const data = await api<WatcherInfo>(`/api/watchers/${encodeURIComponent(watchId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: draft.trim() }),
      })
      onRenamed?.(data)
      setEditing(false)
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "无法修改名称")
    } finally {
      setSaving(false)
    }
  }

  if (!watchId) {
    return heading ? (
      <h1 className="font-heading text-2xl font-medium tracking-tight">{label}</h1>
    ) : (
      <div className="font-medium">{label}</div>
    )
  }

  if (editing) {
    return (
      <div className="flex min-w-0 items-center gap-1" onClick={(event) => event.stopPropagation()}>
        <Input
          ref={inputRef}
          value={draft}
          placeholder={placeholder}
          disabled={saving}
          aria-label="任务名称"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault()
              event.stopPropagation()
              void save()
            }
            if (event.key === "Escape") {
              event.preventDefault()
              setEditing(false)
            }
          }}
          className={heading ? "h-9 max-w-sm text-base font-medium" : "h-8 max-w-[14rem]"}
        />
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          disabled={saving}
          aria-label="保存名称"
          onClick={(event) => {
            event.stopPropagation()
            void save()
          }}
        >
          <CheckIcon />
        </Button>
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          disabled={saving}
          aria-label="取消"
          onClick={(event) => {
            event.stopPropagation()
            setEditing(false)
          }}
        >
          <XIcon />
        </Button>
      </div>
    )
  }

  return (
    <div className="flex min-w-0 items-center gap-1">
      {heading ? (
        <h1 className="font-heading min-w-0 text-2xl font-medium tracking-tight">{label}</h1>
      ) : (
        <div className="min-w-0 font-medium">{label}</div>
      )}
      <Button
        type="button"
        size="icon-xs"
        variant="ghost"
        className="text-muted-foreground"
        aria-label="修改任务名称"
        onClick={(event) => {
          event.stopPropagation()
          setDraft(label)
          setEditing(true)
        }}
      >
        <PencilIcon />
      </Button>
    </div>
  )
}
