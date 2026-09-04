import assert from "node:assert/strict";
import test from "node:test";
import type { ColdStartRequest } from "@/lib/build/types";
import { cleanText, planRoleSearchQueries, researchRoleSources } from "@/lib/search/web-research";
import { createRoleSearchPlan } from "@/lib/search/query-planner";
import type { ModelInvoker } from "@/lib/agent/model";

function request(): ColdStartRequest {
  return {
    runId: "run-web-research-test",
    projectId: "project-web-research-test",
    roleTitle: "工业机器人系统运维员",
    roleDescription: "重点了解高职学生需要掌握的现场任务和安全规范。",
    market: "中国大陆",
    audience: ["高职学生", "教师"],
    snapshotAsOf: "2026-08-21",
    sources: [],
  };
}

test("网页正文清洗移除内嵌图片、营销噪声与敏感长数字", () => {
  const cleaned = cleanText(`正文：岗位需要完成模型评测。\n![二维码](data:image/png;base64,ABCDEF)\n立即报名 添加微信 13812345678\n银行卡 6222021234567890123\n相关推荐\n正文结束。`);
  assert.ok(!cleaned.includes("data:image"));
  assert.ok(!cleaned.includes("13812345678"));
  assert.ok(!cleaned.includes("6222021234567890123"));
  assert.ok(!cleaned.includes("相关推荐"));
  assert.ok(cleaned.includes("岗位需要完成模型评测"));
});

test("岗位联网研究计划覆盖标准、市场、实践、技术、教学和未来信号", () => {
  const queries = planRoleSearchQueries(request());
  const categories = new Set(queries.map((query) => query.category));
  for (const category of ["official_standard", "job_market", "work_practice", "technology", "education", "future_signal", "user_focus"]) {
    assert.ok(categories.has(category as never), `缺少 ${category}`);
  }
  assert.ok(queries.every((query) => query.query.includes("工业机器人系统运维员")));
  assert.equal(new Set(queries.map((query) => query.id)).size, queries.length);
});

test("联网结果被规范化、去重并登记为带查询索引的公开来源", async () => {
  const originalFetch = globalThis.fetch;
  let call = 0;
  globalThis.fetch = async (_url, init) => {
    call += 1;
    const body = JSON.parse(String(init?.body || "{}")) as { query?: string };
    return new Response(JSON.stringify({
      results: [
        {
          title: "人力资源社会保障部职业标准",
          url: "https://www.gov.cn/standard/robot?utm_source=test",
          text: `职业标准正文 ${body.query || ""}。`.repeat(120),
          publishedDate: "2025-01-02",
          score: 0.94,
        },
        {
          title: `企业实践资料 ${call}`,
          url: `https://example${call}.com/case`,
          text: `现场任务、交付物、安全检查和异常处理说明 ${body.query || ""}。`.repeat(90),
          score: 0.72,
        },
        {
          title: "不得抓取的本地地址",
          url: "http://127.0.0.1/private",
          text: `工业机器人系统运维员 ${body.query || ""}`.repeat(100),
          score: 1,
        },
      ],
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const progress: string[] = [];
    const result = await researchRoleSources({
      request: request(),
      config: { provider: "exa", apiKey: "exa-test-secret" },
      sourceLimit: 10,
      onProgress: (event) => progress.push(event.kind),
    });
    assert.equal(result.report.queries.length, 7);
    assert.ok(result.report.deduplicatedCount >= 6, "同一个官方 URL 应跨查询去重");
    assert.ok(result.sources.some((source) => source.domain === "www.gov.cn" && source.sourceTier === "authoritative"));
    assert.ok(result.sources.every((source) => source.locator && source.queryIds?.length));
    assert.ok(result.sources.every((source) => !source.locator?.includes("127.0.0.1")), "厂商结果不能把私网地址带入抓取与来源索引");
    assert.ok(!JSON.stringify(result).includes("exa-test-secret"), "来源索引不得保存 API Key");
    assert.ok(progress.includes("source-deduplicated"));
    assert.ok(progress.includes("source-fetched"));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("模型规划补充聚焦查询，但不能删掉六类核心证据覆盖", async () => {
  const reasoning: string[] = [];
  const model: ModelInvoker = async function* () {
    yield { type: "reasoning", delta: "先辨析岗位边界。" };
    yield {
      type: "text",
      delta: JSON.stringify({
        queries: [
          { category: "technology", query: "industrial robot predictive maintenance official documentation", priority: 9 },
          { category: "work_practice", query: "工业机器人系统运维员 现场点检 故障闭环 交付记录", priority: 8 },
          { category: "job_market", query: "工业机器人运维 招聘 现场安全 任职要求", priority: 7 },
          { category: "education", query: "工业机器人运维 高职 实训 评价标准", priority: 6 },
        ],
      }),
    };
  };
  const ambiguousRequest = {
    ...request(),
    roleTitle: "工业机器人运维相关岗位方向",
    roleDescription: "还不清楚具体岗位，希望先辨析现场运维相关方向。",
  };
  const plan = await createRoleSearchPlan({ request: ambiguousRequest, model, onReasoning: (delta) => reasoning.push(delta) });
  const categories = new Set(plan.queries.map((query) => query.category));
  assert.equal(plan.strategy, "model_assisted");
  for (const category of ["official_standard", "job_market", "work_practice", "technology", "education", "future_signal"]) {
    assert.ok(categories.has(category as never), `缺少 ${category}`);
  }
  assert.ok(plan.queries.some((query) => query.query.includes("predictive maintenance")));
  assert.deepEqual(reasoning, ["先辨析岗位边界。"]);
});

test("明确岗位直接采用确定性覆盖计划，不为搜索词额外消耗模型调用", async () => {
  let called = false;
  const model: ModelInvoker = async function* () {
    called = true;
    yield { type: "text", delta: "{}" };
  };
  const plan = await createRoleSearchPlan({ request: request(), model });
  assert.equal(plan.strategy, "deterministic");
  assert.equal(called, false);
  assert.equal(plan.queries.length, 7);
});

test("搜索厂商临时限流时只做有限重试并继续生成来源", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (_url, init) => {
    calls += 1;
    if (calls === 1) return new Response("rate limited", { status: 429 });
    const body = JSON.parse(String(init?.body || "{}")) as { query?: string };
    return new Response(JSON.stringify({
      results: [{
        title: `检索结果 ${calls}`,
        url: `https://retry-example-${calls}.com/source`,
        text: `岗位任务、交付物和安全规范 ${body.query || ""}。`.repeat(100),
        score: 0.8,
      }],
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const progress: string[] = [];
    const result = await researchRoleSources({
      request: request(),
      config: { provider: "exa", apiKey: "exa-test-secret" },
      onProgress: (event) => progress.push(event.kind),
    });
    assert.equal(calls, 8, "七个查询中仅首个查询应多重试一次");
    assert.ok(progress.includes("search-retrying"));
    assert.ok(result.sources.length > 0);
    assert.equal(result.report.failures.length, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Tavily 采用高级搜索后定向抽取，并把请求追踪与用量写入来源索引", async () => {
  const originalFetch = globalThis.fetch;
  let searchCalls = 0;
  let extractCalls = 0;
  const extractBatchSizes: number[] = [];
  const searchBodies: Array<Record<string, unknown>> = [];
  globalThis.fetch = async (url, init) => {
    const endpoint = String(url);
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("X-Project-ID"), "project-web-research-test");
    assert.equal(headers.get("X-Session-Id"), "run-web-research-test");
    const body = JSON.parse(String(init?.body || "{}")) as Record<string, unknown>;
    if (endpoint.endsWith("/extract")) {
      extractCalls += 1;
      const urls = body.urls as string[];
      extractBatchSizes.push(urls.length);
      assert.equal(body.chunks_per_source, 5);
      assert.equal(body.extract_depth, "basic");
      return new Response(JSON.stringify({
        results: urls.map((sourceUrl) => ({ url: sourceUrl, raw_content: `定向抽取的岗位正文、任务、交付物与规范。${sourceUrl}`.repeat(80) })),
        failed_results: [],
        request_id: `extract-request-${extractCalls}`,
        usage: { credits: Math.ceil(urls.length / 5) },
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    searchCalls += 1;
    searchBodies.push(body);
    return new Response(JSON.stringify({
      results: [{
        title: `Tavily 来源 ${searchCalls}`,
        url: `https://tavily-source-${searchCalls}.example.com/page`,
        content: `搜索阶段的相关证据片段 ${String(body.query || "")}。`.repeat(80),
        score: 0.88,
      }],
      request_id: `search-request-${searchCalls}`,
      response_time: "0.25",
      usage: { credits: 2 },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const result = await researchRoleSources({
      request: request(),
      config: { provider: "tavily", apiKey: "tvly-test-secret" },
      sourceLimit: 10,
    });
    assert.equal(searchCalls, 7);
    assert.equal(extractCalls, 2, "正文应拆成小批次抽取，避免一次请求失败清空全部来源");
    assert.ok(extractBatchSizes.every((size) => size <= 4));
    assert.ok(searchBodies.every((body) => body.search_depth === "advanced" && body.chunks_per_source === 3));
    assert.ok(searchBodies.every((body) => body.include_raw_content === false && body.include_usage === true));
    assert.ok(searchBodies.every((body) => body.country === "china"));
    assert.equal(result.report.extraction?.extractedSourceCount, 7);
    assert.equal(result.report.extraction?.requestCount, 2);
    assert.equal(result.report.usage?.searchCredits, 14);
    assert.equal(result.report.usage?.extractCredits, 2);
    assert.equal(result.report.usage?.totalCredits, 16);
    assert.ok(result.sources.every((source) => source.extractionMethod === "provider_extract"));
    assert.ok(result.sources.every((source) => (source.providerRequestIds?.length || 0) >= 2));
    assert.ok(result.report.queries.every((query) => query.responseTimeMs === 250));
    assert.ok(result.report.categoryCoverage.every((coverage) => coverage.status === "covered"));
    assert.equal(result.report.candidates.filter((candidate) => candidate.disposition === "selected").length, 7);
    assert.ok(!JSON.stringify(result).includes("tvly-test-secret"));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Tavily 排除与岗位弱相关的高分页面，并在抽取正文乱码时保留可读搜索证据", async () => {
  const originalFetch = globalThis.fetch;
  let searchCalls = 0;
  let extractCalls = 0;
  globalThis.fetch = async (url, init) => {
    const body = JSON.parse(String(init?.body || "{}")) as Record<string, unknown>;
    if (String(url).endsWith("/extract")) {
      extractCalls += 1;
      const urls = body.urls as string[];
      return new Response(JSON.stringify({
        results: urls.map((sourceUrl) => ({
          url: sourceUrl,
          raw_content: sourceUrl.includes("relevant-1.example.com")
            ? "PE".repeat(2000)
            : `工业机器人系统运维员的点检、诊断、维修、保养与安全交付规范。${sourceUrl}`.repeat(60),
        })),
        failed_results: [],
        request_id: `extract-quality-${extractCalls}`,
        usage: { credits: 1 },
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    searchCalls += 1;
    const query = String(body.query || "");
    return new Response(JSON.stringify({
      results: [
        {
          title: `工业机器人系统运维员资料 ${searchCalls}`,
          url: `https://relevant-${searchCalls}.example.com/page`,
          content: `工业机器人系统运维员现场工作证据 ${query}。`.repeat(70),
          score: 0.78,
        },
        {
          title: `完全无关的 PDM 软件榜单 ${searchCalls}`,
          url: `https://irrelevant-${searchCalls}.example.com/pdm`,
          content: "产品数据管理软件采购、营销与价格排行榜。".repeat(100),
          score: 0.99,
        },
      ],
      request_id: `search-quality-${searchCalls}`,
      response_time: 0.2,
      usage: { credits: 2 },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const result = await researchRoleSources({
      request: request(),
      config: { provider: "tavily", apiKey: "tvly-test-secret" },
      sourceLimit: 10,
    });
    assert.equal(searchCalls, 7);
    assert.equal(extractCalls, 2);
    assert.ok(result.sources.every((source) => !source.title.includes("PDM")));
    assert.equal(result.sources.filter((source) => source.extractionMethod === "provider_extract").length, 6);
    assert.equal(result.sources.filter((source) => source.extractionMethod === "search_content").length, 1);
    assert.equal(result.report.extraction?.extractedSourceCount, 6);
    assert.equal(result.report.extraction?.failedSourceCount, 1);
    assert.ok(result.sources.every((source) => !source.content.includes("PEPEPE")));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("技术证据缺失时宁可标记类别缺口，也不拿只提到工业机器人的产品榜单凑数", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    const body = JSON.parse(String(init?.body || "{}")) as Record<string, unknown>;
    if (String(url).endsWith("/extract")) {
      const urls = body.urls as string[];
      return new Response(JSON.stringify({
        results: urls.map((sourceUrl) => ({ url: sourceUrl, raw_content: `工业机器人系统运维员岗位任务、安全规范与实训要求。${sourceUrl}`.repeat(80) })),
        failed_results: [],
        request_id: "extract-role-specific",
        usage: { credits: 1 },
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    const query = String(body.query || "");
    const technology = query.includes("官方技术文档");
    return new Response(JSON.stringify({
      results: technology ? [{
        title: "2026 年最佳 PDM 软件工具",
        url: "https://weak-technology.example.com/pdm-ranking",
        content: "工业机器人产品数据管理、采购、营销和价格排行榜。".repeat(100),
        score: 0.99,
      }] : [{
        title: `工业机器人系统运维员资料 ${stableTestId(query)}`,
        url: `https://role-source-${stableTestId(query)}.example.com/page`,
        content: `工业机器人系统运维员岗位任务、安全规范与实训要求。${query}`.repeat(70),
        score: 0.8,
      }],
      request_id: `search-${stableTestId(query)}`,
      usage: { credits: 2 },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const result = await researchRoleSources({
      request: request(),
      config: { provider: "tavily", apiKey: "tvly-test-secret" },
      sourceLimit: 10,
    });
    assert.ok(result.sources.every((source) => !source.title.includes("PDM")));
    assert.equal(result.report.categoryCoverage.find((coverage) => coverage.category === "technology")?.status, "missing");
    assert.equal(result.report.candidates.find((candidate) => candidate.title.includes("PDM"))?.disposition, "low_relevance");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

function stableTestId(value: string) {
  let hash = 0;
  for (const character of value) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return hash.toString(36);
}
