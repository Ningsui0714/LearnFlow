"use client";

import { BookOpenCheck, ExternalLink, SearchX, X } from "lucide-react";
import type { WebResearchReport } from "@/lib/build/types";
import ResearchAudit from "@/app/components/ResearchAudit";

export type EvidenceSourceItem = {
  id: string;
  title: string;
  kind: string;
  tier?: string;
  status?: string;
  asOf?: string;
  locator?: string;
  note?: string;
  discovery?: string;
};

type Props = {
  sources: EvidenceSourceItem[];
  query: string;
  research?: WebResearchReport;
  sourceIds?: string[];
  contextLabel?: string;
  onClearContext?: () => void;
};

export default function EvidenceSourceView({ sources, query, research, sourceIds = [], contextLabel, onClearContext }: Props) {
  const needle = query.trim().toLowerCase();
  const scopedSources = sourceIds.length ? sources.filter((source) => sourceIds.includes(source.id)) : sources;
  const visibleSources = needle
    ? scopedSources.filter((source) => `${source.title} ${source.kind} ${source.tier || ""} ${source.note || ""}`.toLowerCase().includes(needle))
    : scopedSources;

  return (
    <div className="evidence-source-view">
      <header>
        <span>PROVENANCE &amp; EVIDENCE</span>
        <h2>来源证据</h2>
        <p>这里展示岗位包实际登记的来源、时间与可追溯位置，不把图谱节点数量当作证据质量。</p>
        <div className="evidence-source-facts">
          <span><b>{sources.length}</b><small>登记来源</small></span>
          <span><b>{sources.filter((source) => source.locator).length}</b><small>可定位原文</small></span>
          <span><b>{new Set(sources.map((source) => source.kind)).size}</b><small>来源类型</small></span>
        </div>
      </header>

      {research ? <ResearchAudit report={research} /> : null}

      {sourceIds.length ? <div className="evidence-context-filter"><span><b>当前证据范围</b><small>{contextLabel || "所选岗位对象"} · {scopedSources.length} 个已登记来源</small></span>{onClearContext ? <button onClick={onClearContext}><X size={12} /> 查看全部来源</button> : null}</div> : null}

      {visibleSources.length ? (
        <section className="evidence-source-grid" aria-label="岗位包来源列表">
          {visibleSources.map((source) => (
            <article key={source.id}>
              <div className="evidence-source-icon"><BookOpenCheck size={15} /></div>
              <div>
                <span className="evidence-source-meta">{source.kind} · {source.tier || "未分级"}{source.asOf ? ` · ${source.asOf}` : ""}</span>
                <h3>{source.title}</h3>
                {source.discovery ? <p>{source.discovery}</p> : null}
                {source.note ? <small>{source.note}</small> : null}
              </div>
              <footer>
                {source.status ? <em>{source.status}</em> : <span />}
                {source.locator ? <a href={source.locator} target="_blank" rel="noreferrer">查看原文 <ExternalLink size={11} /></a> : <i>项目内资料</i>}
              </footer>
            </article>
          ))}
        </section>
      ) : (
        <div className="evidence-source-empty"><SearchX size={22} /><span>没有匹配当前检索条件的来源。</span></div>
      )}
    </div>
  );
}
