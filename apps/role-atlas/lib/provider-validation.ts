import { z } from "zod";
import { providerIds, PROVIDERS, type ProviderConfig } from "./providers";

export const providerConfigSchema = z.object({
  provider: z.enum(providerIds),
  model: z.string().min(1).max(80),
  apiKey: z.string().min(8).max(512),
  thinking: z.boolean().default(true),
  baseUrl: z.string().url().optional(),
});

export function validateProviderConfig(input: unknown): ProviderConfig {
  const config = providerConfigSchema.parse(input);
  const definition = PROVIDERS[config.provider];
  if (!definition.models.some((model) => model.id === config.model)) {
    throw new Error("MODEL_NOT_ALLOWED");
  }
  return { ...config, thinking: true };
}
