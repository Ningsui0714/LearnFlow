import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ResearchAudit from "@/app/components/ResearchAudit";
import type { WebResearchReport } from "@/lib/build/types";

test("来源审计同时展示类别覆盖、查询追踪与未入选原因", () => {
  const report: WebResearchReport = {
    provider: "tavily",
    providerName: "Tavily",
    startedAt: "2026-08-21T00:00:00.000Z",
    completedAt: "2026-08-21T00:00:01.000Z",
    queries: [{
      id: "query:standard",
      category: "official_standard",
      query: "工业机器人系统运维员 国家职业标准",
      resultCount: 2,
      requestId: "request-search-1",
      responseTimeMs: 240,
      credits: 2,
    }],
    selectedSourceCount: 1,
    candidateCount: 2,
    deduplicatedCount: 0,
    candidates: [
      {
        title: "国家职业技能标准",
        url: "https://example.gov.cn/standard",
        domain: "example.gov.cn",
        queryIds: ["query:standard"],
        categories: ["official_standard"],
        relevanceScore: 1,
        rankingScore: 0.98,
        disposition: "selected",
      },
      {
        title: "无关榜单",
        url: "https://example.com/list",
        domain: "example.com",
        queryIds: ["query:standard"],
        categories: ["official_standard"],
        relevanceScore: 0,
        rankingScore: 0.32,
        disposition: "low_relevance",
      },
    ],
    categoryCoverage: [{ category: "official_standard", queryCount: 1, candidateCount: 2, selectedSourceCount: 1, status: "covered" }],
    failures: [],
    extraction: { requestCount: 1, requestedSourceCount: 1, extractedSourceCount: 1, failedSourceCount: 0, requestIds: ["request-extract-1"] },
    usage: { searchCredits: 2, extractCredits: 1, totalCredits: 3 },
  };

  const html = renderToStaticMarkup(createElement(ResearchAudit, { report }));
  assert.match(html, /标准政策/);
  assert.match(html, /request-search-1/);
  assert.match(html, /岗位相关性不足/);
  assert.match(html, /1\/2 入选/);
});
