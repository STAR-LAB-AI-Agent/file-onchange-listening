import { useEffect, useState } from "react"

import { parseAppRoute } from "@/lib/api"
import { SettingsPage } from "@/pages/Settings"
import { TaskDetail } from "@/pages/TaskDetail"
import { TaskList } from "@/pages/TaskList"
import { TaskRules } from "@/pages/TaskRules"

export default function App() {
  const [pathname, setPathname] = useState(window.location.pathname)

  useEffect(() => {
    const onPop = () => setPathname(window.location.pathname)
    window.addEventListener("popstate", onPop)
    return () => window.removeEventListener("popstate", onPop)
  }, [])

  const route = parseAppRoute(pathname)

  return (
    <div className="min-h-svh bg-background">
      {route.kind === "settings" ? (
        <SettingsPage />
      ) : route.kind === "task" ? (
        route.page === "rules" ? (
          <TaskRules watchId={route.watchId} />
        ) : (
          <TaskDetail watchId={route.watchId} />
        )
      ) : (
        <TaskList />
      )}
    </div>
  )
}
