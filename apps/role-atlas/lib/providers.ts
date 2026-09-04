export const PROVIDER_SESSION_KEY = "role-atlas.provider-config.v1";

export const providerIds = ["mimo", "deepseek"] as const;
export type ProviderId = (typeof providerIds)[number];

export type ProviderDefinition = {
  id: ProviderId;
  name: string;
  description: string;
  baseUrl: string;
  docsUrl: string;
  models: Array<{ id: string; label: string; note: string }>;
  defaultModel: string;
};

export const PROVIDERS: Record<ProviderId, ProviderDefinition> = {
  mimo: {
    id: "mimo",
    name: "Xiaomi MiMo",
    description: "长上下文、结构化输出与函数工具；适合作为主分析模型。",
    baseUrl: "https://api.xiaomimimo.com/v1",
    docsUrl: "https://mimo.mi.com/docs/en-US/api/chat/openai-api",
    defaultModel: "mimo-v2.5",
    models: [
      { id: "mimo-v2.5", label: "MiMo V2.5", note: "全模态与通用岗位分析" },
      { id: "mimo-v2.5-pro", label: "MiMo V2.5 Pro", note: "复杂推理与深度分析" },
    ],
  },
  deepseek: {
    id: "deepseek",
    name: "DeepSeek",
    description: "高并发、低成本；适合作为快速对话与补充分析模型。",
    baseUrl: "https://api.deepseek.com",
    docsUrl: "https://api-docs.deepseek.com/",
    defaultModel: "deepseek-v4-flash",
    models: [
      { id: "deepseek-v4-flash", label: "DeepSeek V4 Flash", note: "快速、低成本、支持工具调用" },
      { id: "deepseek-v4-pro", label: "DeepSeek V4 Pro", note: "更强推理与复杂任务" },
    ],
  },
};

export type ProviderConfig = {
  provider: ProviderId;
  model: string;
  apiKey: string;
  thinking: boolean;
  baseUrl?: string;
};

export function defaultProviderConfig(provider: ProviderId = "mimo"): Omit<ProviderConfig, "apiKey"> & { apiKey: string } {
  return {
    provider,
    model: PROVIDERS[provider].defaultModel,
    apiKey: "",
    thinking: true,
  };
}

export function providerChatEndpoint(provider: ProviderId, baseUrl?: string) {
  return `${(baseUrl || PROVIDERS[provider].baseUrl).replace(/\/$/, "")}/chat/completions`;
}

export function providerModelsEndpoint(provider: ProviderId) {
  return `${PROVIDERS[provider].baseUrl}/models`;
}
