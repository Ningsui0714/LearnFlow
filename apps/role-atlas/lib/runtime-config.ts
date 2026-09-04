import type { ProviderId } from "./providers";
import type { SearchProviderId } from "./search/providers";

export type RuntimeConfigStatus = {
  model: {
    configured: boolean;
    provider: ProviderId;
    model: string;
    source: "server_env" | "none";
  };
  search: {
    configured: boolean;
    provider: SearchProviderId;
    source: "server_env" | "none";
  };
};
