"use client";

import { ArrowRight, GitBranch, PackageCheck, Plus, RotateCcw, Route, Users } from "lucide-react";
import { useMemo, useState } from "react";
import type { RoleCardNode } from "@/app/components/RoleCardView";

type EvidenceBinding = {
  assertion_type: string;
  method: string;
  source_refs: string[];
  confidence: number;
  as_of: string;
  note?: string;
};

type Scenario = {
  id: string;
  title: string;
  summary: string;
  scenario_family: string;
  goal: string;
  trigger: string;
  expected_outcomes: string[];
  event_refs: string[];
  task_refs: string[];
  knowledge_state: string;
  lifecycle: "accepted" | "candidate" | "deprecated";
  evidence_binding: EvidenceBinding;
};

type ProcessNode = {
  id: string;
  scenario_id: string;
  kind: "event" | "artifact" | "actor" | "work_object" | "tool_system" | "quality_criterion" | "exception_risk";
  event_type?: "activity" | "decision" | "handoff" | "exception" | "outcome";
  label: string;
  summary: string;
  lane?: string;
  sequence_hint?: number;
  task_refs?: string[];
  capability_refs?: string[];
  knowledge_skill_refs?: string[];
  artifact_refs?: string[];
  actor_refs?: string[];
  lifecycle: "accepted" | "candidate" | "deprecated";
  evidence_binding: EvidenceBinding;
};

type ProcessRelation = {
  id: string;
  type: string;
  source: string;
  target: string;
  qualifiers?: Record<string, unknown>;
};

export type WorkProcessPayload = {
  manifest: {
    package_id: string;
    package_version: string;
    snapshot_id: string;
    status: string;
  };
  validation: { warnings: string[]; stats: Record<string, number> };
  workProcess: {
    scenarios: Scenario[];
    nodes: ProcessNode[];
    relations: ProcessRelation[];
    alignment: Array<{ semantic_target_id: string; scenario_refs: string[]; status: string; note: string }>;
  };
};

export type ProcessReferenceNode = {
  id: string;
  type: string;
  label: string;
  summary: string;
  ring: number;
  lifecycle: "accepted" | "candidate" | "deprecated";
  assertion_refs: string[];
  evidence_summary: {
    binding_refs: string[];
    source_refs: string[];
    max_confidence: number;
    has_segment_evidence: boolean;
    temporal_status_counts: Record<string, number>;
  };
  data: Record<string, unknown>;
  packageId: string;
  packageVersion: string;
  snapshotId: string;
};

type Props = {
  payload: WorkProcessPayload;
  query: string;
  selectedId: string;
  taskId?: string;
  semanticNodes?: RoleCardNode[];
  taskKnowledgeSkills?: RoleCardNode[];
  embedded?: boolean;
  onSelect: (node: ProcessReferenceNode | RoleCardNode) => void;
  onReference: (node: ProcessReferenceNode | RoleCardNode) => void;
  onDragStart: (node: ProcessReferenceNode | RoleCardNode) => void;
  onDragEnd: () => void;
};

const eventTypeLabels: Record<string, string> = {
  activity: "行动",
  decision: "决策",
  handoff: "交接",
  exception: "异常",
  outcome: "结果",
};

export function toProcessReference(item: Scenario | ProcessNode, payload: WorkProcessPayload): ProcessReferenceNode {
  const isScenario = "title" in item;
  const binding = item.evidence_binding;
  return {
    id: item.id,
    type: isScenario ? "scenario" : item.kind,
    label: isScenario ? item.title : item.label,
    summary: item.summary,
    ring: isScenario ? 0 : 1,
    lifecycle: item.lifecycle,
    assertion_refs: [],
    evidence_summary: {
      binding_refs: [`process-binding:${item.id}`],
      source_refs: binding.source_refs,
      max_confidence: binding.confidence,
      has_segment_evidence: false,
      temporal_status_counts: {},
    },
    data: isScenario
      ? { goal: item.goal, trigger: item.trigger, expected_outcomes: item.expected_outcomes, task_refs: item.task_refs, knowledge_state: item.knowledge_state }
      : { event_type: item.event_type, lane: item.lane, sequence_hint: item.sequence_hint, task_refs: item.task_refs, capability_refs: item.capability_refs, knowledge_skill_refs: item.knowledge_skill_refs, artifact_refs: item.artifact_refs, actor_refs: item.actor_refs, knowledge_state: "inferred_pattern" },
    packageId: payload.manifest.package_id,
    packageVersion: payload.manifest.package_version,
    snapshotId: payload.manifest.snapshot_id,
  };
}

export default function WorkProcessForestView({ payload, query, selectedId, taskId, semanticNodes = [], taskKnowledgeSkills = [], embedded = false, onSelect, onReference, onDragStart, onDragEnd }: Props) {
  const visibleScenarios = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return payload.workProcess.scenarios.filter((scenario) => {
      const taskMatch = taskId ? scenario.task_refs.includes(taskId) : true;
      const queryMatch = needle ? `${scenario.title} ${scenario.summary} ${scenario.goal} ${scenario.trigger}`.toLowerCase().includes(needle) : true;
      return taskMatch && queryMatch;
    });
  }, [payload, query, taskId]);
  const [activeId, setActiveId] = useState(payload.workProcess.scenarios[0]?.id || "");
  const semanticNodeMap = useMemo(() => new Map(semanticNodes.map((node) => [node.id, node])), [semanticNodes]);

  const scenario = visibleScenarios.find((item) => item.id === activeId) || visibleScenarios[0];
  if (!scenario) return <div className="process-empty">没有匹配的工作场景。</div>;

  const scenarioNodes = payload.workProcess.nodes.filter((node) => node.scenario_id === scenario.id);
  const events = scenarioNodes.filter((node) => node.kind === "event").sort((a, b) => (a.sequence_hint || 999) - (b.sequence_hint || 999));
  const auxiliary = new Map(scenarioNodes.filter((node) => node.kind !== "event").map((node) => [node.id, node]));
  const eventIds = new Set(events.map((event) => event.id));
  const relations = payload.workProcess.relations.filter((relation) => eventIds.has(relation.source) || eventIds.has(relation.target));
  const columns = [...new Set(events.map((event) => event.sequence_hint || 0))].sort((a, b) => a - b);
  const alignment = payload.workProcess.alignment.filter((item) => item.scenario_refs.includes(scenario.id));
  const scenarioRef = toProcessReference(scenario, payload);

  return (
    <div className={`process-forest ${embedded ? "embedded" : ""} ${taskId ? "task-filtered" : ""}`}>
      <aside className="forest-index" aria-label="工作场景森林">
        <div className="forest-kicker"><Route size={13} /> {taskId ? "任务事理场景" : "工作场景森林"}</div>
        {visibleScenarios.map((item, index) => (
            <button key={item.id} className={item.id === scenario.id ? "active" : ""} onClick={() => { setActiveId(item.id); onSelect(toProcessReference(item, payload)); }}>
            <i>{String(index + 1).padStart(2, "0")}</i>
            <span><b>{item.title}</b><small>{item.scenario_family} · {item.event_refs.length} 个事件</small></span>
          </button>
        ))}
        <div className="forest-boundary"><GitBranch size={13} /><span><b>当前边界</b><small>{taskId ? "保留完整场景脉络，并突出直接实现当前任务的事件。" : "全部为 inferred_pattern 候选模板；尚无真实 WorkEpisode。"}</small></span></div>
      </aside>

      <section className="process-tree">
        <header className="process-summary">
          <div>
            <span>{taskId ? "任务事理流程" : "候选工作模式"} · {scenario.scenario_family}</span>
            <h2>{scenario.title}</h2>
            <p>{scenario.summary}</p>
          </div>
          <button draggable onDragStart={() => onDragStart(scenarioRef)} onDragEnd={onDragEnd} onClick={() => onReference(scenarioRef)}><Plus size={13} /> 引用场景</button>
        </header>
        <div className="process-contract">
          <span><b>触发</b>{scenario.trigger}</span>
          <ArrowRight size={15} />
          <span><b>目标</b>{scenario.goal}</span>
          <ArrowRight size={15} />
          <span><b>结果</b>{scenario.expected_outcomes.join("、")}</span>
        </div>

        <div className="process-scroll" aria-label={`${scenario.title}事理图谱`}>
          <div className="process-columns" style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(178px, 1fr))` }}>
            {columns.map((sequence) => (
              <div className="process-column" key={sequence}>
                <span className="sequence-label">阶段 {sequence}</span>
                {events.filter((event) => (event.sequence_hint || 0) === sequence).map((event) => {
                  const reference = toProcessReference(event, payload);
                  const outgoing = relations.filter((relation) => relation.source === event.id);
                  const artifacts = (event.artifact_refs || []).map((id) => auxiliary.get(id)).filter((item): item is ProcessNode => Boolean(item));
                  const taskMatch = taskId ? (event.task_refs || []).includes(taskId) : true;
                  const explicitKnowledgeSkills = (event.knowledge_skill_refs || []).map((id) => semanticNodeMap.get(id)).filter((item): item is RoleCardNode => Boolean(item));
                  // Older packages may bind skills to the stable task without
                  // repeating the same relation on its matching process event.
                  // Reuse that task projection only on an event that explicitly
                  // realizes the task; this is a display fallback, not a new fact.
                  const knowledgeSkills = [...new Map([
                    ...explicitKnowledgeSkills,
                    ...(taskId && taskMatch ? taskKnowledgeSkills : []),
                  ].map((skill) => [skill.id, skill])).values()];
                  return (
                    <div
                      key={event.id}
                      className={`process-event ${event.event_type || "activity"} ${selectedId === event.id ? "selected" : ""} ${taskMatch ? "task-match" : "context-event"}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => onSelect(reference)}
                      onKeyDown={(keyboardEvent) => { if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") onSelect(reference); }}
                      draggable
                      onDragStart={() => onDragStart(reference)}
                      onDragEnd={onDragEnd}
                    >
                      <div className="event-head"><span>{eventTypeLabels[event.event_type || "activity"]}</span><em>{taskId && !taskMatch ? "关联上下文" : event.lane || "岗位"}</em></div>
                      {knowledgeSkills.length > 0 && <div className="event-skills"><b>此步使用</b>{knowledgeSkills.map((skill) => <button key={skill.id} onClick={(clickEvent) => { clickEvent.stopPropagation(); onSelect(skill); }} title={skill.summary}>{skill.label}</button>)}</div>}
                      <h3>{event.label}</h3>
                      <p>{event.summary}</p>
                      {artifacts.length > 0 && <div className="event-artifacts">{artifacts.map((artifact) => <span key={artifact.id}><PackageCheck size={11} />{artifact.label}</span>)}</div>}
                      <div className="event-links">
                        {outgoing.filter((relation) => relation.type === "branches_to").map((relation) => <span className="branch" key={relation.id}><GitBranch size={10} /> 分支 → {auxiliary.get(relation.target)?.label || events.find((item) => item.id === relation.target)?.label || relation.target}</span>)}
                        {outgoing.filter((relation) => relation.type === "loops_to").map((relation) => <span className="loop" key={relation.id}><RotateCcw size={10} /> 返工 → {events.find((item) => item.id === relation.target)?.label || relation.target}</span>)}
                      </div>
                      <button className="process-quote" onClick={(clickEvent) => { clickEvent.stopPropagation(); onReference(reference); }}><Plus size={11} /> 引用</button>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        <footer className="process-meta">
          <span><Users size={12} /> {new Set(events.flatMap((event) => event.actor_refs || [])).size} 类参与者</span>
          <span><PackageCheck size={12} /> {scenarioNodes.filter((node) => node.kind === "artifact").length} 类交付物</span>
          <span><GitBranch size={12} /> {relations.filter((relation) => relation.type === "branches_to").length} 个分支 · {relations.filter((relation) => relation.type === "loops_to").length} 个返工环</span>
          <span>任务映射：{alignment.map((item) => `${item.semantic_target_id.replace("task:", "")} ${item.status}`).join(" · ")}</span>
        </footer>
      </section>
    </div>
  );
}
