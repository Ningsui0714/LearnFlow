import type { WebResearchReport, WebSearchCategory } from "@/lib/build/types";

const categoryLabels: Record<WebSearchCategory, string> = {
  official_standard: "标准政策",
  job_market: "招聘市场",
  work_practice: "工作实践",
  technology: "技术资料",
  education: "教学评价",
  future_signal: "未来信号",
  user_focus: "用户关注",
};

const dispositionLabels: Record<WebResearchReport["candidates"][number]["disposition"], string> = {
  selected: "已入选",
  duplicate_content: "正文重复",
  low_relevance: "岗位相关性不足",
  domain_limit: "同域名配额",
  source_limit: "来源上限",
  unreadable: "正文不可读",
};

export default function ResearchAudit({ report }: { report: WebResearchReport }) {
  const coverage = report.categoryCoverage || [];
  const candidates = report.candidates || [];
  const selected = candidates.filter((candidate) => candidate.disposition === "selected").length;
  return (
    <div className="research-audit">
      {coverage.length ? <div className="research-coverage" aria-label="联网研究类别覆盖">
        {coverage.map((item) => <span className={item.status} key={item.category}>
          <b>{categoryLabels[item.category]}</b>
          <small>{item.selectedSourceCount}/{item.candidateCount} 来源 · {item.status === "covered" ? "已覆盖" : item.status === "failed" ? "查询失败" : "待补充"}</small>
        </span>)}
      </div> : null}
      <details className="research-trace">
        <summary>查询与候选审计 <small>{report.queries.length} 查询 · {selected}/{report.candidateCount} 入选 · {report.failures.length} 失败</small></summary>
        <div className="research-query-list">
          {report.queries.map((query) => <article key={query.id}>
            <span><b>{categoryLabels[query.category]}</b><small>{query.query}</small></span>
            <em>{query.resultCount} 结果 · {query.responseTimeMs ?? "—"} ms · {query.credits ?? "—"} credits{query.requestId ? ` · ${query.requestId}` : ""}</em>
          </article>)}
        </div>
        {candidates.length ? <div className="research-candidate-list">
          {candidates.map((candidate, index) => <article className={candidate.disposition} key={`${candidate.url}:${candidate.disposition}:${index}`}>
            <span><b>{candidate.title}</b><small>{candidate.domain} · 相关性 {Math.round(candidate.relevanceScore * 100)}% · 排序 {candidate.rankingScore.toFixed(2)}</small></span>
            <em>{dispositionLabels[candidate.disposition]}{candidate.duplicateOf ? ` · 合并至 ${candidate.duplicateOf}` : ""}</em>
            <a href={candidate.url} target="_blank" rel="noreferrer">原页</a>
          </article>)}
        </div> : null}
      </details>
    </div>
  );
}
