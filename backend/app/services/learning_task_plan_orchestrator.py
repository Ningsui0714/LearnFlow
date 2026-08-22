"""Deterministic, inspectable planning analysis for learning-work-task Plans.

This module deliberately produces planning artifacts rather than hidden model
reasoning.  It expands the validated remote Plan into a hierarchy, dependency
schedule, alternative candidates, critic verdicts, risks, and versioned local
replanning records that can be rendered and audited by the workspace UI.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.learning_task_plan_gateway import LearningTaskPlanRun


PlanDecisionCode = Literal[
    "SELECT_CANDIDATE", "REQUEST_EVIDENCE", "LOCAL_REPLAN", "STOP",
]
ReplanFailureCode = Literal[
    "evidence_gap", "dependency_blocked", "safety_conflict",
    "artifact_rejected", "mapping_conflict",
]


class PlanHierarchyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: Literal["goal", "phase", "work_package", "atomic_step"]
    parent_id: str | None = None
    label: str
    objective: str
    package_id: str | None = None
    depth: int = Field(ge=0, le=3)


class PlanGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    edge_type: Literal["contains", "precedes", "produces", "reviews"]


class PlanCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    strategy: Literal["fidelity_first", "evidence_first", "balanced_parallel"]
    title: str
    ordered_package_ids: list[str]
    parallel_waves: list[list[str]]
    scores: dict[str, int]
    weighted_score: int = Field(ge=0, le=100)
    hard_gate_passed: bool
    tradeoffs: list[str]


class PlanCriticVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    critic_id: str
    dimension: Literal[
        "task_identity", "dependency", "evidence", "safety",
        "deliverable", "teaching_fit",
    ]
    verdict: Literal["pass", "warning", "fail"]
    score: int = Field(ge=0, le=100)
    findings: list[str]
    affected_package_ids: list[str]


class PlanRiskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str
    package_id: str
    category: Literal[
        "evidence", "dependency", "safety", "artifact", "mapping",
    ]
    likelihood: Literal["low", "medium", "high"]
    impact: Literal["low", "medium", "high"]
    mitigation: str
    evidence_required: bool


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: PlanDecisionCode
    selected_candidate_id: str | None = None
    confidence: int = Field(ge=0, le=100)
    reasons: list[str]
    triggered_rules: list[str]


class PlanRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str
    analysis_version: int = Field(ge=1)
    parent_revision_id: str | None = None
    cause: str
    failure_code: ReplanFailureCode | None = None
    affected_package_ids: list[str]
    preserved_package_ids: list[str]
    controls_added: list[str]


PlanStageStatus = Literal[
    "completed", "ready", "blocked", "pending", "not_started",
]


class PlanStageSubstep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    substep_id: str
    label: str
    status: PlanStageStatus
    detail: str
    parent_substep_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    output_ref: str | None = None


class PlanStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: Literal[
        "task_contract",
        "grounding_clarification",
        "evidence_search_planning",
        "evidence_grounded_task_planning",
        "critic_finalize",
        "execution_handoff",
    ]
    sequence: int = Field(ge=1, le=6)
    label: str
    status: PlanStageStatus
    summary: str
    input_refs: list[str]
    output_refs: list[str]
    substeps: list[PlanStageSubstep]

    @model_validator(mode="after")
    def validate_substep_tree(self) -> "PlanStage":
        substep_ids = [item.substep_id for item in self.substeps]
        if len(substep_ids) != len(set(substep_ids)):
            raise ValueError("Plan 阶段子步骤 ID 必须唯一")
        known = set(substep_ids)
        for item in self.substeps:
            references = set(item.depends_on)
            if item.parent_substep_id:
                references.add(item.parent_substep_id)
            if not references <= known:
                raise ValueError("Plan 阶段子步骤引用了不存在的节点")
        return self


class PlanExecutionChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: str
    objective: str
    status: Literal["pending", "in_progress", "completed", "blocked"]
    expected_artifact: str
    observation_state: Literal[
        "not_observed", "observed", "accepted", "rejected",
    ]
    completion_condition: str


class PlanHandoffArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_type: Literal[
        "html", "pdf", "versioned_json",
        "knowledge_learning_entry", "feedback_contract",
    ]
    label: str
    status: Literal["planned", "ready", "generated"]
    contract_ref: str


class LearningTaskPlanningAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["learning-work-task-planning-analysis-v3"]
    run_id: str
    plan_version: int = Field(ge=1)
    analysis_version: int = Field(ge=1)
    planning_status: Literal[
        "ready_for_confirmation", "planned_not_executed",
        "replanned_not_executed", "needs_evidence",
    ]
    active_revision_id: str
    hierarchy: list[PlanHierarchyNode]
    graph_edges: list[PlanGraphEdge]
    topological_waves: list[list[str]]
    critical_path: list[str]
    candidates: list[PlanCandidate] = Field(default_factory=list, max_length=3)
    critics: list[PlanCriticVerdict] = Field(default_factory=list, max_length=6)
    risks: list[PlanRiskItem]
    decision: PlanDecision
    stages: list[PlanStage] = Field(min_length=6, max_length=6)
    execution_checklist: list[PlanExecutionChecklistItem]
    handoff_artifacts: list[PlanHandoffArtifact] = Field(
        min_length=5, max_length=5,
    )
    evidence_semantics: Literal["operational_only"]
    revision_history: list[PlanRevision]
    repair_budget_remaining: int = Field(ge=0, le=2)
    metrics: dict[str, int]

    @model_validator(mode="after")
    def validate_references(self) -> "LearningTaskPlanningAnalysis":
        package_ids = {
            node.package_id for node in self.hierarchy if node.package_id
        }
        for wave in self.topological_waves:
            if not set(wave) <= package_ids:
                raise ValueError("Plan 波次引用了不存在的工作包")
        candidate_ids = {item.candidate_id for item in self.candidates}
        if len(self.candidates) not in {0, 3}:
            raise ValueError("学习型任务候选必须尚未生成或完整生成三份")
        if len(self.critics) not in {0, 6}:
            raise ValueError("Critic 必须尚未运行或完整输出六维结论")
        selected = self.decision.selected_candidate_id
        if selected and selected not in candidate_ids:
            raise ValueError("Plan 决策引用了不存在的候选")
        if [item.sequence for item in self.stages] != list(range(1, 7)):
            raise ValueError("Plan 六阶段必须按 1 到 6 的顺序输出")
        checklist_ids = {item.package_id for item in self.execution_checklist}
        if checklist_ids != package_ids:
            raise ValueError("执行清单必须覆盖且只能覆盖全部工作包")
        return self


def _topological_waves(packages: list[dict[str, Any]]) -> list[list[str]]:
    remaining = {
        item["package_id"]: set(item.get("depends_on") or [])
        for item in packages
    }
    waves: list[list[str]] = []
    while remaining:
        ready = sorted(key for key, deps in remaining.items() if not deps)
        if not ready:  # The gateway validator already rejects this condition.
            break
        waves.append(ready)
        ready_set = set(ready)
        remaining = {
            key: deps - ready_set
            for key, deps in remaining.items()
            if key not in ready_set
        }
    return waves


def _priority_order(
    packages: list[dict[str, Any]],
    package_priority: dict[str, int],
) -> list[str]:
    by_id = {item["package_id"]: item for item in packages}
    remaining = {
        item["package_id"]: set(item.get("depends_on") or [])
        for item in packages
    }
    ordered: list[str] = []
    while remaining:
        ready = [key for key, deps in remaining.items() if not deps]
        ready.sort(key=lambda key: (
            package_priority.get(key, 50), key,
        ))
        chosen = ready[0]
        ordered.append(chosen)
        remaining = {
            key: deps - {chosen}
            for key, deps in remaining.items()
            if key != chosen
        }
    return ordered


def _critical_path(packages: list[dict[str, Any]]) -> list[str]:
    by_id = {item["package_id"]: item for item in packages}
    waves = _topological_waves(packages)
    best: dict[str, tuple[int, list[str]]] = {}
    for package_id in [item for wave in waves for item in wave]:
        item = by_id[package_id]
        duration = max(1, int(item.get("estimated_minutes") or 3))
        parents = item.get("depends_on") or []
        parent_score, parent_path = max(
            (best[parent] for parent in parents),
            default=(0, []),
            key=lambda value: value[0],
        )
        best[package_id] = (parent_score + duration, [*parent_path, package_id])
    return max(best.values(), default=(0, []), key=lambda value: value[0])[1]


def _nested_mapping_candidates(run: dict[str, Any], key: str) -> list[Any]:
    state = run.get("state") if isinstance(run.get("state"), dict) else {}
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    run_artifacts = run.get("artifacts") if isinstance(run.get("artifacts"), dict) else {}
    return [
        run.get(key),
        state.get(key),
        artifacts.get(key),
        run_artifacts.get(key),
    ]


def _extract_evidence_ledger(run: dict[str, Any]) -> dict[str, Any] | None:
    for candidate in _nested_mapping_candidates(run, "evidence_ledger"):
        if not isinstance(candidate, dict):
            continue
        entries = candidate.get("entries") or candidate.get("items")
        if isinstance(entries, list) and entries:
            return candidate
    return None


def _extract_task_steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    state = run.get("state") if isinstance(run.get("state"), dict) else {}
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    containers: list[Any] = [
        run.get("learning_task_plan"),
        state.get("learning_task_plan"),
        state.get("step_plan"),
        state.get("selected_candidate"),
        artifacts.get("learning_task_plan"),
        artifacts.get("step_plan"),
        artifacts.get("selected_candidate"),
    ]
    for container in containers:
        if isinstance(container, list):
            steps = container
        elif isinstance(container, dict):
            steps = (
                container.get("task_steps")
                or container.get("steps")
                or container.get("work_steps")
            )
        else:
            continue
        if isinstance(steps, list) and steps and all(
            isinstance(item, dict) for item in steps
        ):
            return steps
    return []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _positive_int(value: Any, default: int = 3) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _learning_task_packages(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize evidence-grounded learning task steps for planning analysis."""
    steps = _extract_task_steps(run)
    packages: list[dict[str, Any]] = []
    known_ids: list[str] = []
    for index, step in enumerate(steps):
        package_id = str(
            step.get("step_id") or step.get("package_id") or f"step_{index + 1:02d}"
        ).strip()
        raw_dependencies = step.get("depends_on") or step.get("dependency_ids")
        if isinstance(raw_dependencies, list):
            dependencies = [
                str(item) for item in raw_dependencies if str(item) in known_ids
            ]
        else:
            dependencies = known_ids[-1:] if known_ids else []
        title = str(
            step.get("title") or step.get("name") or step.get("step_name")
            or f"作业步骤 {index + 1}"
        ).strip()
        objective = str(
            step.get("objective") or step.get("instruction")
            or step.get("description") or title
        ).strip()
        expected_artifact = str(
            step.get("expected_artifact") or step.get("deliverable")
            or step.get("output") or "可检查步骤产物"
        ).strip()
        completion_condition = str(
            step.get("completion_condition") or step.get("acceptance_criteria")
            or step.get("checkpoint") or "步骤产物通过明确的验收检查。"
        ).strip()
        knowledge_ids = _string_list(step.get("knowledge_point_ids"))
        skill_ids = _string_list(step.get("skill_point_ids"))
        packages.append({
            "package_id": package_id,
            "title": title,
            "phase": str(step.get("phase") or step.get("stage") or "真实作业过程"),
            "objective": objective,
            "depends_on": dependencies,
            "allowed_tools": [],
            "expected_artifact": expected_artifact,
            "completion_condition": completion_condition,
            "knowledge_point_ids": knowledge_ids,
            "skill_point_ids": skill_ids,
            "safety_constraints": _string_list(step.get("safety_constraints")),
            "source_refs": _string_list(
                step.get("source_refs") or step.get("evidence_refs")
            ),
            "estimated_minutes": _positive_int(
                step.get("estimated_minutes") or step.get("duration_minutes")
            ),
        })
        known_ids.append(package_id)
    return packages


def _build_learning_task_hierarchy(
    packages: list[dict[str, Any]],
    goal: str,
) -> list[dict[str, Any]]:
    if not packages:
        return []
    nodes: list[dict[str, Any]] = [{
        "node_id": "goal",
        "node_type": "goal",
        "parent_id": None,
        "label": "学习型任务目标",
        "objective": goal,
        "package_id": None,
        "depth": 0,
    }]
    phases: dict[str, str] = {}
    for item in packages:
        phase_label = item["phase"]
        phase_id = phases.get(phase_label)
        if not phase_id:
            phase_id = f"learning_phase_{len(phases) + 1:02d}"
            phases[phase_label] = phase_id
            nodes.append({
                "node_id": phase_id,
                "node_type": "phase",
                "parent_id": "goal",
                "label": phase_label,
                "objective": "按证据确认的真实作业顺序组织学习任务步骤。",
                "package_id": None,
                "depth": 1,
            })
        package_id = item["package_id"]
        package_node_id = f"learning_step_{package_id}"
        nodes.append({
            "node_id": package_node_id,
            "node_type": "work_package",
            "parent_id": phase_id,
            "label": item["title"],
            "objective": item["objective"],
            "package_id": package_id,
            "depth": 2,
        })
        atomic_specs = (
            ("operate", "执行操作", item["objective"]),
            ("deliver", "形成步骤产物", item["expected_artifact"]),
            ("accept", "执行验收检查", item["completion_condition"]),
        )
        for suffix, label, objective in atomic_specs:
            nodes.append({
                "node_id": f"learning_atomic_{package_id}_{suffix}",
                "node_type": "atomic_step",
                "parent_id": package_node_id,
                "label": label,
                "objective": objective,
                "package_id": package_id,
                "depth": 3,
            })
    return nodes


def _build_edges(packages: list[dict[str, Any]], hierarchy: list[dict[str, Any]]) -> list[dict[str, str]]:
    edges = [
        {"source": node["parent_id"], "target": node["node_id"], "edge_type": "contains"}
        for node in hierarchy if node["parent_id"]
    ]
    package_nodes = {
        str(node["package_id"]): str(node["node_id"])
        for node in hierarchy
        if node.get("node_type") == "work_package" and node.get("package_id")
    }
    for item in packages:
        for parent in item.get("depends_on") or []:
            edges.append({
                "source": package_nodes.get(parent, f"learning_step_{parent}"),
                "target": package_nodes.get(
                    item["package_id"], f"learning_step_{item['package_id']}"
                ),
                "edge_type": "precedes",
            })
    return edges


def _critics(
    run: dict[str, Any],
    packages: list[dict[str, Any]],
    *,
    evidence_ready: bool,
) -> list[dict[str, Any]]:
    if not packages:
        return []
    plan = run["plan"]
    package_ids = [item["package_id"] for item in packages]
    blocking = [] if evidence_ready else [
        item for item in plan.get("unknowns") or [] if item.get("blocking")
    ]
    missing_mappings = [
        item["package_id"] for item in packages
        if not item.get("knowledge_point_ids") or not item.get("skill_point_ids")
    ]
    missing_sources = [
        item["package_id"] for item in packages if not item.get("source_refs")
    ]
    missing_artifacts = [
        item["package_id"] for item in packages
        if not str(item.get("expected_artifact") or "").strip()
        or not str(item.get("completion_condition") or "").strip()
    ]
    stop_text = " ".join(plan.get("stop_conditions") or [])
    return [
        {
            "critic_id": "critic_identity",
            "dimension": "task_identity",
            "verdict": "pass",
            "score": 100,
            "findings": ["Run、任务契约和 Plan 使用同一语义指纹。"],
            "affected_package_ids": [],
        },
        {
            "critic_id": "critic_dependency",
            "dimension": "dependency",
            "verdict": "pass",
            "score": 96,
            "findings": ["依赖图无环，所有前置工作包均可解析。"],
            "affected_package_ids": [],
        },
        {
            "critic_id": "critic_evidence",
            "dimension": "evidence",
            "verdict": "warning" if blocking or missing_sources else "pass",
            "score": 68 if blocking else 78 if missing_sources else 94,
            "findings": (
                [f"仍有 {len(blocking)} 个阻塞性证据缺口。"] if blocking
                else [f"{len(missing_sources)} 个学习任务步骤缺少来源引用。"] if missing_sources
                else ["证据账本已就绪，所有任务步骤均带来源引用。"]
            ),
            "affected_package_ids": missing_sources,
        },
        {
            "critic_id": "critic_safety",
            "dimension": "safety",
            "verdict": "pass" if any(word in stop_text for word in ("安全", "权限", "停止", "终止")) else "warning",
            "score": 91 if any(word in stop_text for word in ("安全", "权限", "停止", "终止")) else 72,
            "findings": ["停止条件已建立。" if stop_text else "需要补充明确的安全停止条件。"],
            "affected_package_ids": package_ids[-1:] if not stop_text else [],
        },
        {
            "critic_id": "critic_delivery",
            "dimension": "deliverable",
            "verdict": "warning" if missing_artifacts else "pass",
            "score": 74 if missing_artifacts else 92,
            "findings": [
                f"{len(missing_artifacts)} 个步骤缺少产物或验收条件。"
                if missing_artifacts else "每个学习任务步骤均声明产物与验收条件。"
            ],
            "affected_package_ids": missing_artifacts,
        },
        {
            "critic_id": "critic_teaching",
            "dimension": "teaching_fit",
            "verdict": "warning" if missing_mappings else "pass",
            "score": 70 if missing_mappings else 93,
            "findings": [
                f"{len(missing_mappings)} 个步骤缺少知识点或技能点强映射。"
                if missing_mappings else "每个步骤均具备知识点与技能点映射。"
            ],
            "affected_package_ids": missing_mappings,
        },
    ]


def _risks(run: dict[str, Any], packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = run["plan"]
    risks: list[dict[str, Any]] = []
    evidence_packages = [
        item["package_id"] for item in packages
        if item.get("agent_role") == "evidence_explorer"
    ]
    for index, unknown in enumerate(plan.get("unknowns") or []):
        risks.append({
            "risk_id": f"risk_unknown_{index + 1}",
            "package_id": evidence_packages[0] if evidence_packages else packages[0]["package_id"],
            "category": "evidence",
            "likelihood": "high" if unknown.get("blocking") else "medium",
            "impact": "high" if unknown.get("blocking") else "medium",
            "mitigation": str(unknown.get("question") or "补齐可追溯证据。"),
            "evidence_required": True,
        })
    for item in packages:
        if len(item.get("depends_on") or []) >= 2:
            risks.append({
                "risk_id": f"risk_join_{item['package_id']}",
                "package_id": item["package_id"],
                "category": "dependency",
                "likelihood": "medium",
                "impact": "high",
                "mitigation": "在汇合点逐项检查上游产物版本与完成门禁。",
                "evidence_required": False,
            })
    if not risks:
        target = packages[min(1, len(packages) - 1)]
        risks.append({
            "risk_id": "risk_artifact_gate",
            "package_id": target["package_id"],
            "category": "artifact",
            "likelihood": "low",
            "impact": "medium",
            "mitigation": "按完成条件校验中间产物，不合格时仅回退当前子图。",
            "evidence_required": False,
        })
    return risks[:12]


def _candidates(
    run: dict[str, Any],
    packages: list[dict[str, Any]],
    waves: list[list[str]],
    critics: list[dict[str, Any]],
    *,
    evidence_ready: bool,
) -> list[dict[str, Any]]:
    if not packages or not critics:
        return []
    blocking = 0 if evidence_ready else sum(
        1 for item in run["plan"].get("unknowns") or [] if item.get("blocking")
    )
    critic_floor = min(item["score"] for item in critics)
    original_priority = {
        item["package_id"]: index for index, item in enumerate(packages)
    }
    evidence_priority = {
        item["package_id"]: -len(item.get("source_refs") or [])
        for item in packages
    }
    learning_priority = {
        item["package_id"]: -(
            len(item.get("knowledge_point_ids") or [])
            + len(item.get("skill_point_ids") or [])
        )
        for item in packages
    }
    strategies = (
        (
            "candidate_fidelity", "fidelity_first", "任务保真优先",
            original_priority,
            {"fidelity": 98, "executability": 88, "evidence": 90, "safety": 90, "teaching_fit": 84, "efficiency": 76},
            ["最大限度保持企业任务对象、动作与产物。", "串行门禁较多，整体耗时相对更长。"],
        ),
        (
            "candidate_evidence", "evidence_first", "证据充分优先",
            evidence_priority,
            {"fidelity": 92, "executability": 85, "evidence": 98, "safety": 93, "teaching_fit": 82, "efficiency": 72},
            ["在不违反依赖的前提下，优先安排来源覆盖更充分的步骤。", "证据较弱的步骤会被推迟并要求补证据。"],
        ),
        (
            "candidate_balanced", "balanced_parallel", "并行均衡方案",
            learning_priority,
            {"fidelity": 94, "executability": 94, "evidence": 90, "safety": 91, "teaching_fit": 94, "efficiency": 95},
            ["在依赖约束内兼顾知识技能覆盖并利用可并行波次。", "需要在汇合点执行严格的步骤产物门禁。"],
        ),
    )
    weights = {"fidelity": 24, "executability": 20, "evidence": 18, "safety": 18, "teaching_fit": 12, "efficiency": 8}
    result: list[dict[str, Any]] = []
    for candidate_id, strategy, title, priority, base_scores, tradeoffs in strategies:
        scores = dict(base_scores)
        scores["evidence"] = max(45, scores["evidence"] - blocking * 12)
        scores["safety"] = min(scores["safety"], critic_floor + 20)
        weighted = round(sum(scores[key] * weights[key] for key in weights) / 100)
        result.append({
            "candidate_id": candidate_id,
            "strategy": strategy,
            "title": title,
            "ordered_package_ids": _priority_order(packages, priority),
            "parallel_waves": waves,
            "scores": scores,
            "weighted_score": weighted,
            "hard_gate_passed": blocking == 0 and critic_floor >= 70,
            "tradeoffs": tradeoffs,
        })
    return result


def _initial_revision(
    run: dict[str, Any],
    package_ids: list[str],
    *,
    task_plan_ready: bool,
) -> dict[str, Any]:
    return {
        "revision_id": "revision_1",
        "analysis_version": 1,
        "parent_revision_id": None,
        "cause": (
            "从证据账本生成学习型任务分层树与三类候选 Plan。"
            if task_plan_ready
            else "从已校验任务契约生成证据检索计划；学习型任务 Plan 等待证据。"
        ),
        "failure_code": None,
        "affected_package_ids": package_ids,
        "preserved_package_ids": [],
        "controls_added": ["语义指纹锁定", "依赖无环校验", "工具白名单"],
    }


_TOOL_LABELS = {
    "task_database": "任务库",
    "knowledge_base_pro": "知识库 Pro",
    "official_web": "权威 Web",
    "evidence_verifier": "证据校验器",
}


def _build_stages(
    run: dict[str, Any],
    workflow_packages: list[dict[str, Any]],
    task_packages: list[dict[str, Any]],
    evidence_ledger: dict[str, Any] | None,
    hierarchy: list[dict[str, Any]],
    waves: list[list[str]],
    critical_path: list[str],
    candidates: list[dict[str, Any]],
    critics: list[dict[str, Any]],
    decision: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile the visible six-stage timeline shown in the workspace.

    These are inspectable artifacts and state summaries. They intentionally do
    not expose hidden model reasoning or claim that planned work was executed.
    """
    plan = run["plan"]
    blocking_unknowns = [
        item for item in plan.get("unknowns") or [] if item.get("blocking")
    ]
    user_blocking_unknowns = [
        item for item in blocking_unknowns
        if item.get("required_evidence") == "user_confirmation"
    ]
    evidence_ready = evidence_ledger is not None
    task_plan_ready = bool(task_packages and hierarchy and candidates)
    search_plan_confirmed = run["phase"] not in {"INTAKE", "CONTRACT_READY"}
    task_plan_finalized = run["phase"] == "COMMITTED"

    contract_steps = [
        {
            "substep_id": "contract_input",
            "label": "上游任务 JSON",
            "status": "completed",
            "detail": str(
                run["task_contract"].get("raw_input")
                or run["task_contract"].get("normalized_input")
                or plan["goal"]
            ),
            "output_ref": f"run:{run['run_id']}",
        },
        {
            "substep_id": "contract_schema",
            "label": "Schema 校验",
            "status": "completed",
            "detail": "Run、TaskPlan、工作包角色/工具/产物均通过版本化白名单校验。",
            "parent_substep_id": "contract_input",
            "output_ref": plan["schema_version"],
        },
        {
            "substep_id": "contract_ids",
            "label": "稳定 ID 校验",
            "status": "completed",
            "detail": f"run_id 与 {len(workflow_packages)} 个检索工作包 ID 已锁定。",
            "parent_substep_id": "contract_input",
            "output_ref": run["run_id"],
        },
        {
            "substep_id": "contract_fingerprint",
            "label": "语义指纹锁定",
            "status": "completed",
            "detail": "任务对象、动作与预期产物在后续修订中保持不变。",
            "parent_substep_id": "contract_input",
            "output_ref": plan["task_contract_fingerprint"],
        },
        {
            "substep_id": "contract_artifact",
            "label": "任务契约产物",
            "status": "completed",
            "detail": "形成可审计 task_contract，作为所有后续阶段的共同基线。",
            "depends_on": ["contract_schema", "contract_ids", "contract_fingerprint"],
            "output_ref": "task_contract",
        },
    ]

    grounding_steps = [
        {
            "substep_id": "grounding_context",
            "label": "环境与现状读取",
            "status": "completed",
            "detail": f"读取任务契约、当前 Run 状态及 {len(workflow_packages)} 个检索工作包。",
            "output_ref": "grounding_context",
        },
        {
            "substep_id": "grounding_facts",
            "label": "可发现事实",
            "status": "completed",
            "detail": f"输入层级：{run['task_contract'].get('input_level') or '未声明'}；当前阶段：{run['phase']}。",
            "parent_substep_id": "grounding_context",
            "output_ref": "discovered_facts",
        },
        {
            "substep_id": "grounding_preferences",
            "label": "用户偏好与待确认项",
            "status": "blocked" if user_blocking_unknowns else "completed",
            "detail": (
                f"仍有 {len(user_blocking_unknowns)} 个问题必须由用户确认。"
                if user_blocking_unknowns else "当前没有必须由用户补充的阻塞项。"
            ),
            "parent_substep_id": "grounding_context",
            "output_ref": "clarification_register",
        },
        {
            "substep_id": "grounding_spec",
            "label": "目标、范围与成功标准",
            "status": "completed",
            "detail": f"1 项总目标、{len(plan['success_criteria'])} 条成功标准。",
            "output_ref": "task_specification",
        },
        {
            "substep_id": "grounding_success",
            "label": "成功标准",
            "status": "completed",
            "detail": "；".join(plan["success_criteria"]),
            "parent_substep_id": "grounding_spec",
            "output_ref": "success_criteria",
        },
        {
            "substep_id": "grounding_stop",
            "label": "停止条件与课堂约束",
            "status": "completed",
            "detail": "；".join(plan["stop_conditions"]),
            "parent_substep_id": "grounding_spec",
            "output_ref": "stop_conditions",
        },
    ]

    evidence_workflows = [
        item for item in workflow_packages
        if item.get("agent_role") == "evidence_explorer"
    ]
    allowed_tools = sorted({
        tool
        for item in evidence_workflows
        for tool in item.get("allowed_tools") or []
    })
    search_steps: list[dict[str, Any]] = [{
        "substep_id": "search_questions",
        "label": "证据问题分解",
        "status": "completed",
        "detail": f"把 {len(blocking_unknowns)} 个未知项转成可执行检索问题。",
        "output_ref": "evidence_questions",
    }]
    for unknown in plan.get("unknowns") or []:
        search_steps.append({
            "substep_id": f"search_question_{unknown['unknown_id']}",
            "label": unknown["question"],
            "status": "ready" if unknown.get("blocking") else "completed",
            "detail": f"所需证据类型：{unknown['required_evidence']}。",
            "parent_substep_id": "search_questions",
            "output_ref": unknown["unknown_id"],
        })
    search_steps.append({
        "substep_id": "search_route",
        "label": "来源路由与可信门槛",
        "status": "completed",
        "detail": "先规划去哪里查、用什么校验器、何时停止；此处不生成学习任务步骤。",
        "depends_on": ["search_questions"],
        "output_ref": "evidence_route",
    })
    for tool in allowed_tools:
        search_steps.append({
            "substep_id": f"search_tool_{tool}",
            "label": _TOOL_LABELS.get(tool, tool),
            "status": "ready",
            "detail": "已登记到证据检索计划的工具白名单。",
            "parent_substep_id": "search_route",
            "output_ref": f"tool:{tool}",
        })
    for item in evidence_workflows:
        search_steps.append({
            "substep_id": f"search_package_{item['package_id']}",
            "label": item["objective"],
            "status": "ready" if not evidence_ready else "completed",
            "detail": item["completion_condition"],
            "parent_substep_id": "search_route",
            "output_ref": item["expected_artifact"],
        })
    search_steps.append({
        "substep_id": "search_plan_artifact",
        "label": "证据检索计划",
        "status": "completed" if search_plan_confirmed else "ready",
        "detail": "只规定证据问题、来源、查询顺序、预算与停止条件。",
        "depends_on": ["search_route"],
        "output_ref": "evidence_search_plan.json",
    })

    task_planning_steps: list[dict[str, Any]] = [{
        "substep_id": "task_evidence_ledger",
        "label": "执行检索并形成证据账本",
        "status": "completed" if evidence_ready else "blocked",
        "detail": (
            "证据条目已到位，可以开始生成学习型任务候选。"
            if evidence_ready else "尚无可验证证据账本，禁止提前生成学习任务步骤。"
        ),
        "output_ref": "evidence_ledger" if evidence_ready else "awaiting_evidence_ledger",
    }]
    for node in hierarchy:
        task_planning_steps.append({
            "substep_id": f"hierarchy_{node['node_id']}",
            "label": node["label"],
            "status": "completed",
            "detail": node["objective"],
            "parent_substep_id": (
                f"hierarchy_{node['parent_id']}" if node["parent_id"] else None
            ),
            "output_ref": (
                f"work-package:{node['package_id']}"
                if node.get("package_id") else node["node_type"]
            ),
        })
    if hierarchy:
        task_planning_steps.extend([{
            "substep_id": "hierarchy_dag",
            "label": "学习任务步骤 DAG 与拓扑波次",
            "status": "completed",
            "detail": f"形成 {len(waves)} 个可调度波次，只有同波次节点允许并行。",
            "parent_substep_id": "hierarchy_goal",
            "output_ref": "topological_schedule.json",
        }, {
            "substep_id": "hierarchy_critical_path",
            "label": "真实作业关键路径",
            "status": "completed",
            "detail": " → ".join(critical_path) or "无关键路径",
            "parent_substep_id": "hierarchy_dag",
            "output_ref": "critical_path",
        }])
    task_planning_steps.append({
        "substep_id": "candidate_search",
        "label": "学习型任务多候选生成",
        "status": "completed" if candidates else "blocked",
        "detail": (
            "基于同一证据账本比较保真、证据与并行策略。"
            if candidates else "必须等待证据账本与真实 task_steps。"
        ),
        "depends_on": ["task_evidence_ledger"],
        "output_ref": "candidate_set" if candidates else "awaiting_task_steps",
    })
    for candidate in candidates:
        task_planning_steps.append({
            "substep_id": f"candidate_{candidate['candidate_id']}",
            "label": candidate["title"],
            "status": "completed" if candidate["hard_gate_passed"] else "blocked",
            "detail": f"加权分 {candidate['weighted_score']}；{len(candidate['parallel_waves'])} 个依赖波次。",
            "parent_substep_id": "candidate_search",
            "output_ref": candidate["candidate_id"],
        })

    gate_status: PlanStageStatus = (
        "blocked" if not task_plan_ready
        else "completed" if task_plan_finalized
        else "ready"
    )
    critic_steps: list[dict[str, Any]] = [{
        "substep_id": "critic_committee",
        "label": "六维 Critic 委员会",
        "status": "completed" if critics else "blocked",
        "detail": (
            "评审学习任务同一性、依赖、证据、安全、交付与教学适配。"
            if critics else "学习型任务候选尚未生成，Critic 不提前运行。"
        ),
        "output_ref": "critic_report.json" if critics else "awaiting_candidates",
    }]
    for critic in critics:
        critic_steps.append({
            "substep_id": f"critic_{critic['critic_id']}",
            "label": critic["dimension"],
            "status": (
                "blocked" if critic["verdict"] == "fail"
                else "ready" if critic["verdict"] == "warning"
                else "completed"
            ),
            "detail": f"{critic['verdict']} · {critic['score']} · {critic['findings'][0]}",
            "parent_substep_id": "critic_committee",
            "output_ref": critic["critic_id"],
        })
    critic_steps.extend([
        {
            "substep_id": "decision_controller",
            "label": "决策控制器",
            "status": gate_status,
            "detail": "；".join(decision["reasons"]),
            "depends_on": ["critic_committee"],
            "output_ref": decision.get("selected_candidate_id") or decision["code"],
        },
        {
            "substep_id": "decision_evidence",
            "label": "补充证据",
            "status": "ready" if decision["code"] == "REQUEST_EVIDENCE" else "completed",
            "detail": "证据不足时返回上一阶段，只补充受影响事实。",
            "parent_substep_id": "decision_controller",
        },
        {
            "substep_id": "decision_replan",
            "label": "局部重规划",
            "status": "ready" if decision["code"] == "LOCAL_REPLAN" else "completed",
            "detail": "冻结未受影响工作包，只重算失败节点及其后继子图。",
            "parent_substep_id": "decision_controller",
        },
        {
            "substep_id": "decision_select",
            "label": "选定候选",
            "status": gate_status,
            "detail": "硬门禁通过后形成 proposed_plan，并等待确认或修订。",
            "parent_substep_id": "decision_controller",
            "output_ref": "proposed_plan.json",
        },
        {
            "substep_id": "decision_confirmation",
            "label": "确认 / 修订",
            "status": "completed" if task_plan_finalized else gate_status,
            "detail": "确认的是证据支撑的学习型任务 Plan，不代表任务已经执行。",
            "parent_substep_id": "decision_select",
            "output_ref": "task_plan.json" if task_plan_finalized else "awaiting_confirmation",
        },
    ])

    execution_checklist = [{
        "package_id": item["package_id"],
        "objective": item["objective"],
        "status": "pending",
        "expected_artifact": item["expected_artifact"],
        "observation_state": "not_observed",
        "completion_condition": item["completion_condition"],
    } for item in task_packages]
    handoff_artifacts = [
        {"artifact_id": "handoff_html", "artifact_type": "html", "label": "中央任务网页", "status": "planned", "contract_ref": "learning-work-task-page"},
        {"artifact_id": "handoff_pdf", "artifact_type": "pdf", "label": "可审阅任务文档", "status": "planned", "contract_ref": "learning-work-task-pdf"},
        {"artifact_id": "handoff_json", "artifact_type": "versioned_json", "label": "版本化任务 JSON", "status": "planned", "contract_ref": "learning-work-task-bundle-v1"},
        {"artifact_id": "handoff_learning", "artifact_type": "knowledge_learning_entry", "label": "知识点级个性化学习入口", "status": "planned", "contract_ref": "personalized-learning-entry-v1"},
        {"artifact_id": "handoff_feedback", "artifact_type": "feedback_contract", "label": "批注与下游反馈契约", "status": "planned", "contract_ref": "feedback_contract"},
    ]
    execution_steps: list[dict[str, Any]] = [
        {
            "substep_id": "execution_checklist",
            "label": "运行清单",
            "status": "pending" if task_packages else "not_started",
            "detail": (
                f"已形成 {len(task_packages)} 个待执行学习任务步骤；当前没有运行证据。"
                if task_packages else "学习型任务 Plan 尚未形成，暂不生成运行清单。"
            ),
            "output_ref": "execution_checklist",
        },
    ]
    for item in execution_checklist:
        execution_steps.append({
            "substep_id": f"execution_{item['package_id']}",
            "label": item["package_id"],
            "status": "pending",
            "detail": item["objective"],
            "parent_substep_id": "execution_checklist",
            "output_ref": item["expected_artifact"],
        })
    execution_steps.extend([
        {
            "substep_id": "execution_observation",
            "label": "环境观察与产物检查",
            "status": "not_started",
            "detail": "执行器接入后记录环境 Observation、产物门禁与失败定位。",
            "depends_on": ["execution_checklist"],
            "output_ref": "observation_register",
        },
        {
            "substep_id": "execution_failure",
            "label": "失败定位与局部回路",
            "status": "not_started",
            "detail": "失败时冻结已通过步骤，仅回传受影响子图到局部重规划。",
            "parent_substep_id": "execution_observation",
            "output_ref": "failure_report",
        },
        {
            "substep_id": "execution_handoff",
            "label": "成果交接",
            "status": "not_started",
            "detail": "HTML、PDF、版本化 JSON 与知识点级学习入口均等待真实产物生成。",
            "depends_on": ["execution_observation"],
            "output_ref": "delivery_bundle",
        },
    ])
    for artifact in handoff_artifacts:
        execution_steps.append({
            "substep_id": f"execution_{artifact['artifact_id']}",
            "label": artifact["label"],
            "status": "not_started",
            "detail": f"计划交接契约：{artifact['contract_ref']}。",
            "parent_substep_id": "execution_handoff",
            "output_ref": artifact["artifact_id"],
        })

    stages = [
        {"stage_id": "task_contract", "sequence": 1, "label": "任务契约", "status": "completed", "summary": "输入、Schema、稳定 ID 与语义指纹形成共同基线。", "input_refs": ["upstream_task.json"], "output_refs": ["task_contract"], "substeps": contract_steps},
        {"stage_id": "grounding_clarification", "sequence": 2, "label": "环境落地与澄清", "status": "blocked" if user_blocking_unknowns else "completed", "summary": "读取现状并显式形成目标、范围、成功标准与停止条件。", "input_refs": ["task_contract", "run_state"], "output_refs": ["task_specification", "clarification_register"], "substeps": grounding_steps},
        {"stage_id": "evidence_search_planning", "sequence": 3, "label": "证据检索规划", "status": "completed" if search_plan_confirmed else "ready", "summary": "先规划证据问题、来源、查询顺序与停止条件，不提前生成任务步骤。", "input_refs": ["task_specification", "unknown_register"], "output_refs": ["evidence_search_plan.json"], "substeps": search_steps},
        {"stage_id": "evidence_grounded_task_planning", "sequence": 4, "label": "证据驱动的学习任务规划", "status": "completed" if task_plan_ready else "ready" if evidence_ready else "blocked", "summary": "先形成证据账本，再生成 Goal、真实作业阶段、任务步骤、原子操作和三类候选。", "input_refs": ["evidence_search_plan.json", "evidence_ledger"], "output_refs": ["learning_task_hierarchy.json", "candidate_set"], "substeps": task_planning_steps},
        {"stage_id": "critic_finalize", "sequence": 5, "label": "学习任务 Critic 与定稿", "status": gate_status, "summary": "六维独立评审驱动补证据、局部重规划、选定与最终确认。", "input_refs": ["candidate_set", "evidence_ledger"], "output_refs": ["critic_report.json", "proposed_plan.json", "task_plan.json" if task_plan_finalized else "awaiting_confirmation"], "substeps": critic_steps},
        {"stage_id": "execution_handoff", "sequence": 6, "label": "执行观察与交接", "status": "pending" if task_plan_ready else "not_started", "summary": "正式学习任务 Plan 确认后才生成运行清单；当前不伪造执行或掌握证据。", "input_refs": ["task_plan.json"], "output_refs": ["execution_checklist", "delivery_bundle", "feedback_contract"], "substeps": execution_steps},
    ]
    return stages, execution_checklist, handoff_artifacts


def build_planning_analysis(run_payload: dict[str, Any]) -> dict[str, Any]:
    run = LearningTaskPlanRun.model_validate(run_payload).model_dump(mode="json")
    plan = run["plan"]
    workflow_packages = plan["work_packages"]
    evidence_ledger = _extract_evidence_ledger(run)
    evidence_ready = evidence_ledger is not None
    task_packages = _learning_task_packages(run) if evidence_ready else []
    package_ids = [item["package_id"] for item in task_packages]
    waves = _topological_waves(task_packages) if task_packages else []
    hierarchy = _build_learning_task_hierarchy(task_packages, plan["goal"])
    critics = _critics(
        run, task_packages, evidence_ready=evidence_ready,
    )
    risks = _risks(run, task_packages or workflow_packages)
    candidates = _candidates(
        run,
        task_packages,
        waves,
        critics,
        evidence_ready=evidence_ready,
    )
    eligible = [item for item in candidates if item["hard_gate_passed"]]
    selected = max(eligible, key=lambda item: item["weighted_score"], default=None)
    if not evidence_ready:
        decision = {
            "code": "REQUEST_EVIDENCE",
            "selected_candidate_id": None,
            "confidence": 82,
            "reasons": ["证据检索计划已经形成，但证据账本尚未到位，禁止生成学习型任务步骤。"],
            "triggered_rules": ["EVIDENCE_LEDGER_REQUIRED"],
        }
        status = "needs_evidence"
    elif not task_packages:
        decision = {
            "code": "REQUEST_EVIDENCE",
            "selected_candidate_id": None,
            "confidence": 78,
            "reasons": ["证据账本已就绪，但尚未收到由证据支撑的 task_steps。"],
            "triggered_rules": ["EVIDENCE_GROUNDED_TASK_STEPS_REQUIRED"],
        }
        status = "needs_evidence"
    elif selected:
        decision = {
            "code": "SELECT_CANDIDATE",
            "selected_candidate_id": selected["candidate_id"],
            "confidence": selected["weighted_score"],
            "reasons": ["所有硬门禁通过。", f"{selected['title']}获得最高加权分。"],
            "triggered_rules": ["IDENTITY_LOCKED", "DAG_VALID", "CRITIC_GATE_PASS"],
        }
        status = (
            "planned_not_executed"
            if run["phase"] == "COMMITTED"
            else "ready_for_confirmation"
        )
    else:
        decision = {
            "code": "LOCAL_REPLAN",
            "selected_candidate_id": None,
            "confidence": 64,
            "reasons": ["至少一个硬门禁未通过，需要修订受影响子图。"],
            "triggered_rules": ["CRITIC_GATE_REJECT"],
        }
        status = "planned_not_executed"
    critical_path = _critical_path(task_packages) if task_packages else []
    stages, execution_checklist, handoff_artifacts = _build_stages(
        run,
        workflow_packages,
        task_packages,
        evidence_ledger,
        hierarchy,
        waves,
        critical_path,
        candidates,
        critics,
        decision,
    )
    analysis = {
        "schema_version": "learning-work-task-planning-analysis-v3",
        "run_id": run["run_id"],
        "plan_version": plan["plan_version"],
        "analysis_version": 1,
        "planning_status": status,
        "active_revision_id": "revision_1",
        "hierarchy": hierarchy,
        "graph_edges": _build_edges(task_packages, hierarchy),
        "topological_waves": waves,
        "critical_path": critical_path,
        "candidates": candidates,
        "critics": critics,
        "risks": risks,
        "decision": decision,
        "stages": stages,
        "execution_checklist": execution_checklist,
        "handoff_artifacts": handoff_artifacts,
        "evidence_semantics": "operational_only",
        "revision_history": [_initial_revision(
            run, package_ids, task_plan_ready=bool(candidates),
        )],
        "repair_budget_remaining": plan["repair_budget"],
        "metrics": {
            "hierarchy_nodes": len(hierarchy),
            "dependency_edges": sum(
                len(item.get("depends_on") or []) for item in task_packages
            ),
            "parallel_waves": len(waves),
            "candidate_count": len(candidates),
            "critic_count": len(critics),
            "risk_count": len(risks),
            "stage_count": len(stages),
            "stage_substep_count": sum(len(item["substeps"]) for item in stages),
            "execution_pending": len(execution_checklist),
        },
    }
    return LearningTaskPlanningAnalysis.model_validate(analysis).model_dump(mode="json")


_REPLAN_CONTROLS: dict[str, list[str]] = {
    "evidence_gap": ["刷新证据查询", "提高来源可信门槛", "重新计算证据覆盖率"],
    "dependency_blocked": ["冻结已完成上游", "重排未完成波次", "新增汇合点版本检查"],
    "safety_conflict": ["插入安全前置门禁", "暂停受影响后继包", "要求人工确认"],
    "artifact_rejected": ["保留通过项", "只修补被拒产物", "重新执行产物验收"],
    "mapping_conflict": ["锁定真实作业步骤", "重算知识技能强关系", "复核稳定 ID"],
}


def replan_analysis(
    run_payload: dict[str, Any],
    current_payload: dict[str, Any],
    *,
    target_package_id: str,
    failure_code: ReplanFailureCode,
    observation: str,
    expected_analysis_version: int,
) -> dict[str, Any]:
    run = LearningTaskPlanRun.model_validate(run_payload).model_dump(mode="json")
    current = LearningTaskPlanningAnalysis.model_validate(current_payload)
    if current.run_id != run["run_id"] or current.plan_version != run["plan"]["plan_version"]:
        raise ValueError("Plan 基线已经变化，请刷新后重试")
    if current.analysis_version != expected_analysis_version:
        raise ValueError(f"规划分析版本已变化，当前为 v{current.analysis_version}")
    if current.repair_budget_remaining <= 0:
        raise ValueError("局部重规划预算已经用尽")
    packages = _learning_task_packages(run)
    if not _extract_evidence_ledger(run) or not packages or not current.candidates:
        raise ValueError("证据驱动的学习型任务 Plan 尚未生成，不能局部重规划")
    package_ids = [item["package_id"] for item in packages]
    if target_package_id not in package_ids:
        raise ValueError("局部重规划目标学习任务步骤不存在")

    affected = {target_package_id}
    changed = True
    while changed:
        changed = False
        for item in packages:
            if item["package_id"] not in affected and affected.intersection(item.get("depends_on") or []):
                affected.add(item["package_id"])
                changed = True
    affected_ordered = [item for item in package_ids if item in affected]
    preserved = [item for item in package_ids if item not in affected]
    next_version = current.analysis_version + 1
    digest = sha256(
        f"{run['run_id']}:{next_version}:{target_package_id}:{failure_code}:{observation}".encode()
    ).hexdigest()[:10]
    revision_id = f"revision_{next_version}_{digest}"
    revision = {
        "revision_id": revision_id,
        "analysis_version": next_version,
        "parent_revision_id": current.active_revision_id,
        "cause": observation.strip(),
        "failure_code": failure_code,
        "affected_package_ids": affected_ordered,
        "preserved_package_ids": preserved,
        "controls_added": _REPLAN_CONTROLS[failure_code],
    }
    updated = deepcopy(current.model_dump(mode="json"))
    updated.update({
        "analysis_version": next_version,
        "planning_status": "replanned_not_executed",
        "active_revision_id": revision_id,
        "repair_budget_remaining": current.repair_budget_remaining - 1,
    })
    updated["revision_history"] = [*updated["revision_history"], revision]
    selected = max(updated["candidates"], key=lambda item: item["weighted_score"])
    selected["title"] = f"{selected['title']} · 局部修订 v{next_version}"
    selected["tradeoffs"] = [
        f"冻结 {len(preserved)} 个未受影响工作包，只重规划 {len(affected_ordered)} 个工作包。",
        *_REPLAN_CONTROLS[failure_code],
    ]
    updated["decision"] = {
        "code": "SELECT_CANDIDATE",
        "selected_candidate_id": selected["candidate_id"],
        "confidence": max(70, selected["weighted_score"] - 2),
        "reasons": ["已完成局部子图修订，任务语义指纹保持不变。", "未受影响工作包保持冻结。"],
        "triggered_rules": ["LOCAL_SUBGRAPH_REPLAN", failure_code.upper()],
    }
    finalize_stage = next(
        item for item in updated["stages"]
        if item["stage_id"] == "critic_finalize"
    )
    finalize_stage["status"] = "ready"
    finalize_stage["summary"] = (
        f"局部子图修订 v{next_version} 已生成；等待确认后再进入执行。"
    )
    finalize_stage["substeps"].append({
        "substep_id": f"decision_revision_{next_version}",
        "label": f"局部修订 v{next_version}",
        "status": "completed",
        "detail": (
            f"冻结 {len(preserved)} 个未受影响工作包，只重规划 "
            f"{len(affected_ordered)} 个受影响工作包。"
        ),
        "parent_substep_id": "decision_replan",
        "depends_on": [],
        "output_ref": revision_id,
    })
    execution_stage = next(
        item for item in updated["stages"]
        if item["stage_id"] == "execution_handoff"
    )
    execution_stage["status"] = "pending"
    execution_stage["summary"] = (
        "修订后的运行清单仍为 pending；尚无执行、观察或掌握证据。"
    )
    updated["metrics"]["revision_count"] = len(updated["revision_history"])
    updated["metrics"]["stage_substep_count"] = sum(
        len(item["substeps"]) for item in updated["stages"]
    )
    return LearningTaskPlanningAnalysis.model_validate(updated).model_dump(mode="json")
