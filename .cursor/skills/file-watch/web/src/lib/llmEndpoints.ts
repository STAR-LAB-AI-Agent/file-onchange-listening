import type { LlmWireApi } from "@/lib/api"

export type LlmEndpointHint = {
  name: string
  endpoint: string
  models: string
  note: string
}

export const CHAT_ENDPOINT_HINTS: LlmEndpointHint[] = [
  {
    name: "智谱 BigModel",
    endpoint: "https://open.bigmodel.cn/api/paas/v4",
    models: "glm-5.3, glm-4-plus, glm-4-air",
    note: "GLM Coding Plan 使用 https://open.bigmodel.cn/api/coding/paas/v4。",
  },
  {
    name: "DeepSeek",
    endpoint: "https://api.deepseek.com",
    models: "deepseek-chat, deepseek-reasoner",
    note: "官方 OpenAI 兼容接口。",
  },
  {
    name: "阿里云百炼 DashScope",
    endpoint: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: "qwen-plus, qwen-max, qwen-turbo",
    note: "使用 OpenAI 兼容模式。",
  },
  {
    name: "月之暗面 Kimi",
    endpoint: "https://api.moonshot.cn/v1",
    models: "kimi-k3, kimi-k2.5, moonshot-v1-32k",
    note: "官方 OpenAI 兼容接口。",
  },
  {
    name: "火山方舟 Doubao",
    endpoint: "https://ark.cn-beijing.volces.com/api/v3",
    models: "doubao-seed-1-6, doubao-1-5-pro-32k",
    note: "模型名通常填方舟模型或推理接入点 ID。",
  },
  {
    name: "腾讯混元",
    endpoint: "https://api.hunyuan.cloud.tencent.com/v1",
    models: "hunyuan-turbos-latest, hunyuan-lite",
    note: "官方 OpenAI 兼容接口。",
  },
  {
    name: "MiniMax",
    endpoint: "https://api.minimax.chat/v1",
    models: "abab6.5s-chat, MiniMax-Text-01",
    note: "官方 OpenAI 兼容接口。",
  },
  {
    name: "百川智能",
    endpoint: "https://api.baichuan-ai.com/v1",
    models: "Baichuan4, Baichuan3-Turbo",
    note: "官方 OpenAI 兼容接口。",
  },
  {
    name: "零一万物",
    endpoint: "https://api.lingyiwanwu.com/v1",
    models: "yi-lightning, yi-large",
    note: "官方 OpenAI 兼容接口。",
  },
  {
    name: "阶跃星辰 StepFun",
    endpoint: "https://api.stepfun.com/v1",
    models: "step-2-16k, step-1-8k",
    note: "官方 OpenAI 兼容接口。",
  },
  {
    name: "讯飞星火",
    endpoint: "https://spark-api-open.xf-yun.com/v1",
    models: "generalv3.5, 4.0Ultra",
    note: "OpenAI 兼容入口，具体模型名以控制台为准。",
  },
  {
    name: "硅基流动 SiliconFlow",
    endpoint: "https://api.siliconflow.cn/v1",
    models: "Qwen/Qwen2.5-72B-Instruct, deepseek-ai/DeepSeek-V3",
    note: "聚合平台，模型名通常带组织前缀。",
  },
  {
    name: "魔搭 ModelScope",
    endpoint: "https://api-inference.modelscope.cn/v1",
    models: "Qwen/Qwen2.5-72B-Instruct",
    note: "模型名以 ModelScope 控制台 / API 文档为准。",
  },
]

export const ANTHROPIC_ENDPOINT_HINTS: LlmEndpointHint[] = [
  {
    name: "Anthropic 官方 Claude",
    endpoint: "https://api.anthropic.com/v1",
    models: "claude-sonnet-4-5, claude-opus-4-1",
    note: "官方 Anthropic Messages 接口。本项目会追加 /messages。",
  },
  {
    name: "智谱 BigModel Anthropic",
    endpoint: "https://open.bigmodel.cn/api/anthropic/v1",
    models: "glm-5.1, glm-4.5, glm-4.5-air",
    note: "本项目会追加 /messages；如官方文档写 /api/anthropic，这里保留 /v1。",
  },
  {
    name: "Kimi Anthropic",
    endpoint: "https://api.moonshot.cn/anthropic/v1",
    models: "kimi-k3, kimi-k2-0711-preview, kimi-latest",
    note: "本项目会追加 /messages。Claude Code 文档中的 /anthropic 在这里写成 /anthropic/v1。",
  },
  {
    name: "Kimi Coding Plan",
    endpoint: "https://api.kimi.com/coding/v1",
    models: "kimi-k3, kimi-k2.5, kimi-k2-0711-preview",
    note: "订阅制 Coding Key 与通用平台 Key 可能不通用，请按 Kimi 控制台说明选择。",
  },
  {
    name: "阿里云百炼 DashScope",
    endpoint: "https://dashscope.aliyuncs.com/apps/anthropic/v1",
    models: "qwen-max, qwen-plus, qwen-coder-plus",
    note: "本项目会追加 /messages；如使用业务空间专属域名，将主机替换为 {WorkspaceId}.cn-beijing.maas.aliyuncs.com。",
  },
  {
    name: "OpenModel 聚合",
    endpoint: "https://api.openmodel.ai/v1",
    models: "kimi-k2.5, qwen3-max, deepseek-v4-flash, MiniMax-M2.5",
    note: "聚合平台，模型名以平台文档和账号权限为准。",
  },
]

export const RESPONSES_ENDPOINT_HINTS: LlmEndpointHint[] = [
  {
    name: "OpenAI 官方",
    endpoint: "https://api.openai.com/v1",
    models: "gpt-5, gpt-4.1, o4-mini",
    note: "本项目会追加 /responses。",
  },
  {
    name: "OpenRouter",
    endpoint: "https://openrouter.ai/api/v1",
    models: "openai/gpt-5, openai/gpt-4.1",
    note: "需该模型支持 Responses；本项目会追加 /responses。",
  },
]

export function endpointHintsFor(wire: LlmWireApi): LlmEndpointHint[] {
  if (wire === "anthropic") return ANTHROPIC_ENDPOINT_HINTS
  if (wire === "responses") return RESPONSES_ENDPOINT_HINTS
  return CHAT_ENDPOINT_HINTS
}

export function endpointHelpTitle(wire: LlmWireApi): string {
  if (wire === "anthropic") return "常见 Anthropic Messages 端点"
  if (wire === "responses") return "常见 OpenAI Responses 端点"
  return "常见国产模型通用端点"
}

export function endpointHelpDescription(wire: LlmWireApi): string {
  if (wire === "anthropic") {
    return "点「填入」写入接口地址，并带上第一个示例模型。本项目会在地址后追加 /messages。"
  }
  if (wire === "responses") {
    return "点「填入」写入接口地址，并带上第一个示例模型。本项目会在地址后追加 /responses。"
  }
  return "点「填入」写入接口地址，并带上第一个示例模型。本项目会在地址后追加 /chat/completions。各厂商可能调整模型名，最终以官方控制台为准。"
}

export function endpointCatalogButton(wire: LlmWireApi): string {
  if (wire === "anthropic") return "Anthropic 端点"
  if (wire === "responses") return "Responses 端点"
  return "国产模型端点"
}

export function firstExampleModel(models: string): string {
  return models.split(",")[0]?.trim() || ""
}
