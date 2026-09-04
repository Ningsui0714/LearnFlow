import assert from "node:assert/strict";
import test from "node:test";
import { resolveProviderConfig, resolveSearchProviderConfig, runtimeConfigStatus } from "@/lib/server-runtime-config";

function withEnv(values: Record<string, string | undefined>, run: () => void) {
  const previous = Object.fromEntries(Object.keys(values).map((key) => [key, process.env[key]]));
  try {
    for (const [key, value] of Object.entries(values)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    run();
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

test("服务端运行时状态只暴露是否配置，不暴露 .env.local 中的密钥", () => {
  withEnv({
    MIMO_API_KEY: "mimo-secret-value",
    TAVILY_API_KEY: "tavily-secret-value",
    ROLE_ATLAS_MODEL_PROVIDER: "mimo",
    ROLE_ATLAS_MODEL: "mimo-v2.5",
    ROLE_ATLAS_SEARCH_PROVIDER: "tavily",
  }, () => {
    const status = runtimeConfigStatus();
    const serialized = JSON.stringify(status);
    assert.equal(status.model.configured, true);
    assert.equal(status.search.configured, true);
    assert.doesNotMatch(serialized, /secret-value/);
  });
});

test("始终使用服务端 MiMo 与 Tavily，客户端配置不能覆盖", () => {
  withEnv({
    MIMO_API_KEY: "mimo-server-secret",
    TAVILY_API_KEY: "tavily-server-secret",
    ROLE_ATLAS_MODEL_PROVIDER: "mimo",
    ROLE_ATLAS_MODEL: "mimo-v2.5",
    ROLE_ATLAS_SEARCH_PROVIDER: "tavily",
  }, () => {
    assert.equal(resolveProviderConfig().apiKey, "mimo-server-secret");
    assert.equal(resolveSearchProviderConfig().apiKey, "tavily-server-secret");
    const resolved = resolveProviderConfig({ provider: "mimo", model: "mimo-v2.5-pro", apiKey: "mimo-session-secret", thinking: true });
    assert.equal(resolved.apiKey, "mimo-server-secret");
    assert.equal(resolved.model, "mimo-v2.5");
  });
});

test("服务端密钥缺失时稳定拒绝，不静默生成伪配置", () => {
  withEnv({ MIMO_API_KEY: undefined, TAVILY_API_KEY: undefined }, () => {
    assert.throws(() => resolveProviderConfig(), /SERVER_MODEL_NOT_CONFIGURED/);
    assert.throws(() => resolveSearchProviderConfig(), /SERVER_SEARCH_NOT_CONFIGURED/);
  });
});
