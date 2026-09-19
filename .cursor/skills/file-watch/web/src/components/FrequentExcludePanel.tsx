import { useEffect, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { FrequentFile } from "@/lib/api"

type Props = {
  items: FrequentFile[]
  saving?: boolean
  onExclude: (paths: string[]) => void
  onDismiss: () => void
}

export function FrequentExcludePanel({ items, saving = false, onExclude, onDismiss }: Props) {
  const keys = useMemo(
    () => items.map((item) => item.path).filter((path): path is string => Boolean(path)),
    [items],
  )
  const identity = keys.slice().sort().join("\n")
  const [selected, setSelected] = useState<Set<string>>(() => new Set(keys))

  useEffect(() => {
    setSelected(new Set(identity ? identity.split("\n") : []))
  }, [identity])

  const selectedCount = keys.filter((path) => selected.has(path)).length
  const allSelected = keys.length > 0 && selectedCount === keys.length
  const someSelected = selectedCount > 0 && !allSelected
  const windowSeconds = items[0]?.window_seconds || 45

  function toggle(path: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current)
      if (checked) next.add(path)
      else next.delete(path)
      return next
    })
  }

  function toggleAll(checked: boolean) {
    setSelected(checked ? new Set(keys) : new Set())
  }

  return (
    <Card size="sm">
      <CardHeader className="border-b">
        <CardTitle>频繁变化候选</CardTitle>
        <CardDescription>
          {windowSeconds} 秒内反复出现，容易刷屏。可全选或勾选多个，加入同一条排除规则。
        </CardDescription>
        <CardAction>
          <span className="text-xs text-muted-foreground">
            已选 {selectedCount} / {keys.length}
          </span>
        </CardAction>
      </CardHeader>
      <CardContent className="p-0">
        <div className="max-h-56 overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">
                  <Checkbox
                    checked={allSelected ? true : someSelected ? "indeterminate" : false}
                    onCheckedChange={(checked) => toggleAll(checked === true)}
                    aria-label="全选"
                  />
                </TableHead>
                <TableHead>路径</TableHead>
                <TableHead className="w-24 text-right">次数</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => {
                const path = item.path
                if (!path) return null
                const label = item.rel || path
                return (
                  <TableRow key={path}>
                    <TableCell>
                      <Checkbox
                        checked={selected.has(path)}
                        onCheckedChange={(checked) => toggle(path, checked === true)}
                        aria-label={label}
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs break-all whitespace-normal">{label}</TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {item.count ?? 0}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>
      <CardFooter className="justify-end gap-2">
        <Button type="button" variant="outline" size="sm" disabled={saving} onClick={onDismiss}>
          暂不处理
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={saving || selectedCount === 0}
          onClick={() => onExclude(keys.filter((path) => selected.has(path)))}
        >
          {saving ? "正在加入…" : "加入排除规则"}
        </Button>
      </CardFooter>
    </Card>
  )
}
