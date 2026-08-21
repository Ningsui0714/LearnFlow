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
        "hierarchical_planning",
        "evidence_candidate_search",
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

    schema_version: Literal["learning-work-task-planning-analysis-v2"]
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
    candidates: list[PlanCandidate] = Field(min_length=3, max_length=3)
    critics: list[PlanCriticVerdict] = Field(min_length=6, max_length=6)
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
        selected = self.decision.selected_candidate_id
        if selected and selected not in candidate_ids:
            raise ValueError("Plan 决策引用了不存在的候选")
        if [item.sequence for item in self.stages] != list(range(1, 7)):
            raise ValueError("Plan 六阶段必须按 1 到 6 的顺序输出")
        checklist_ids = {item.package_id for item in self.execution_checklist}
        if checklist_ids != package_ids:
            raise ValueError("执行清单必须覆盖且只能覆盖全部工作包")
        return self


_PHASES = (
    ("contract", "任务语义锁定", {"task_contract_compiler", "plan_builder"}),
    ("evidence", "证据探索与事实校验", {"evidence_explorer"}),
    ("synthesis", "候选步骤图生成", {"candidate_planner"}),
    ("review", "多维评审与决策", {"critic_committee", "targeted_patch_agent"}),
    ("delivery", "交付编译与版本封存", {"artifact_publisher"}),
)

_ROLE_DURATION = {
    "task_contract_compiler": 2,
    "plan_builder": 3,
    "evidence_explorer": 5,
    "candidate_planner": 4,
    "critic_committee": 4,
    "targeted_patch_agent": 3,
    "artifact_publisher": 2,
}


def _phase_for(role: str) -> tuple[str, str]:
    for phase_id, label, roles in _PHASES:
        if role in roles:
            return phase_id, label
    return "synthesis", "候选步骤图生成"


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
    role_priority: dict[str, int],
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
            role_priority.get(str(by_id[key].get("agent_role")), 50), key,
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
        duration = _ROLE_DURATION.get(str(item.get("agent_role")), 3)
        parents = item.get("depends_on") or []
        parent_score, parent_path = max(
            (best[parent] for parent in parents),
            default=(0, []),
            key=lambda value: value[0],
        )
        best[package_id] = (parent_score + duration, [*parent_path, package_id])
    return max(best.values(), default=(0, []), key=lambda value: value[0])[1]


def _build_hierarchy(packages: list[dict[str, Any]], goal: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = [{
        "node_id": "goal",
        "node_type": "goal",
        "parent_id": None,
        "label": "规划总目标",
        "objective": goal,
        "package_id": None,
        "depth": 0,
    }]
    used_phases: set[str] = set()
    for item in packages:
        phase_id, phase_label = _phase_for(str(item.get("agent_role")))
        if phase_id not in used_phases:
            nodes.append({
                "node_id": f"phase_{phase_id}",
                "node_type": "phase",
                "parent_id": "goal",
                "label": phase_label,
                "objective": f"完成{phase_label}并产出可检查中间件。",
                "package_id": None,
                "depth": 1,
            })
            used_phases.add(phase_id)
        package_id = item["package_id"]
        nodes.append({
            "node_id": f"package_{package_id}",
            "node_type": "work_package",
            "parent_id": f"phase_{phase_id}",
            "label": item["objective"],
            "objective": item["completion_condition"],
            "package_id": package_id,
            "depth": 2,
        })
        atomic_specs = (
            ("prepare", "输入与约束检查", "核验依赖、权限和输入完整性。"),
            ("produce", "受控产物生成", str(item["objective"])),
            ("verify", "产物门禁校验", str(item["completion_condition"])),
        )
        for suffix, label, objective in atomic_specs:
            nodes.append({
                "node_id": f"atomic_{package_id}_{suffix}",
                "node_type": "atomic_step",
                "parent_id": f"package_{package_id}",
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
    for item in packages:
        for parent in item.get("depends_on") or []:
            edges.append({
                "source": f"package_{parent}",
                "target": f"package_{item['package_id']}",
                "edge_type": "precedes",
            })
    return edges


def _critics(run: dict[str, Any], packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = run["plan"]
    package_ids = [item["package_id"] for item in packages]
    blocking = [item for item in plan.get("unknowns") or [] if item.get("blocking")]
    roles = {str(item.get("agent_role")) for item in packages}
    artifacts = {str(item.get("expected_artifact")) for item in packages}
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
            "verdict": "warning" if blocking else "pass",
            "score": 68 if blocking else 92,
            "findings": ([f"仍有 {len(blocking)} 个阻塞性证据缺口。"] if blocking else ["未发现阻塞性证据缺口。"]),
            "affected_package_ids": [item["package_id"] for item in packages if item.get("agent_role") == "evidence_explorer"],
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
            "verdict": "pass" if artifacts & {"delivery_bundle", "selected_candidate", "candidate_set"} else "warning",
            "score": 90 if artifacts & {"delivery_bundle", "selected_candidate", "candidate_set"} else 74,
            "findings": ["每个工作包均声明产物与完成条件。"],
            "affected_package_ids": [],
        },
        {
            "critic_id": "critic_teaching",
            "dimension": "teaching_fit",
            "verdict": "pass" if "candidate_planner" in roles else "warning",
            "score": 90 if "candidate_planner" in roles else 70,
            "findings": ["候选规划阶段负责保持真实作业顺序并补齐课堂实施条件。"],
            "affected_package_ids": [item["package_id"] for item in packages if item.get("agent_role") == "candidate_planner"],
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
) -> list[dict[str, Any]]:
    blocking = sum(1 for item in run["plan"].get("unknowns") or [] if item.get("blocking"))
    critic_floor = min(item["score"] for item in critics)
    strategies = (
        (
            "candidate_fidelity", "fidelity_first", "任务保真优先",
            {"task_contract_compiler": 0, "plan_builder": 1, "evidence_explorer": 2, "candidate_planner": 3, "critic_committee": 4, "targeted_patch_agent": 5, "artifact_publisher": 6},
            {"fidelity": 98, "executability": 88, "evidence": 90, "safety": 90, "teaching_fit": 84, "efficiency": 76},
            ["最大限度保持企业任务对象、动作与产物。", "串行门禁较多，整体耗时相对更长。"],
        ),
        (
            "candidate_evidence", "evidence_first", "证据充分优先",
            {"evidence_explorer": 0, "task_contract_compiler": 1, "plan_builder": 2, "critic_committee": 3, "candidate_planner": 4, "targeted_patch_agent": 5, "artifact_publisher": 6},
            {"fidelity": 92, "executability": 85, "evidence": 98, "safety": 93, "teaching_fit": 82, "efficiency": 72},
            ["优先关闭来源与事实缺口。", "证据探索可能延后候选步骤生成。"],
        ),
        (
            "candidate_balanced", "balanced_parallel", "并行均衡方案",
            {"task_contract_compiler": 0, "evidence_explorer": 1, "plan_builder": 2, "candidate_planner": 3, "critic_committee": 4, "artifact_publisher": 5, "targeted_patch_agent": 6},
            {"fidelity": 94, "executability": 94, "evidence": 90, "safety": 91, "teaching_fit": 94, "efficiency": 95},
            ["在依赖约束内最大化并行波次。", "需要在汇合点执行严格的版本门禁。"],
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


def _initial_revision(run: dict[str, Any], package_ids: list[str]) -> dict[str, Any]:
    return {
        "revision_id": "revision_1",
        "analysis_version": 1,
        "parent_revision_id": None,
        "cause": "从已校验任务契约生成分层多候选 Plan。",
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
    "candidate_generator": "候选生成器",
    "candidate_critic": "候选评审器",
    "task_compiler": "任务编译器",
}


def _build_stages(
    run: dict[str, Any],
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
    packages = plan["work_packages"]
    blocking_unknowns = [
        item for item in plan.get("unknowns") or [] if item.get("blocking")
    ]
    confirmed = run["phase"] not in {"INTAKE", "CONTRACT_READY"}

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
            "detail": f"run_id 与 {len(packages)} 个唯一 package_id 已锁定。",
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
            "detail": f"读取任务契约、当前 Run 状态及 {len(packages)} 个规划工作包。",
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
            "status": "blocked" if blocking_unknowns else "completed",
            "detail": (
                f"仍有 {len(blocking_unknowns)} 个阻塞项，需要补充证据或用户确认。"
                if blocking_unknowns else "当前没有阻塞性澄清项。"
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

    hierarchy_steps: list[dict[str, Any]] = []
    for node in hierarchy:
        hierarchy_steps.append({
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
    hierarchy_steps.extend([
        {
            "substep_id": "hierarchy_dag",
            "label": "依赖 DAG 与拓扑波次",
            "status": "completed",
            "detail": f"形成 {len(waves)} 个可调度波次，只有同波次节点允许并行。",
            "parent_substep_id": "hierarchy_goal",
            "output_ref": "topological_schedule.json",
        },
        {
            "substep_id": "hierarchy_critical_path",
            "label": "关键路径",
            "status": "completed",
            "detail": " → ".join(critical_path) or "无关键路径",
            "parent_substep_id": "hierarchy_dag",
            "output_ref": "critical_path",
        },
    ])

    allowed_tools = sorted({
        tool for item in packages for tool in item.get("allowed_tools") or []
    })
    search_steps: list[dict[str, Any]] = [{
        "substep_id": "search_route",
        "label": "证据路由",
        "status": "blocked" if blocking_unknowns else "completed",
        "detail": "只使用工作包工具白名单中声明的来源与校验器。",
        "output_ref": "evidence_route",
    }]
    for tool in allowed_tools:
        search_steps.append({
            "substep_id": f"search_tool_{tool}",
            "label": _TOOL_LABELS.get(tool, tool),
            "status": "ready" if blocking_unknowns else "completed",
            "detail": "已登记到当前 Plan 的允许工具集合。",
            "parent_substep_id": "search_route",
            "output_ref": f"tool:{tool}",
        })
    search_steps.extend([
        {
            "substep_id": "search_ledger",
            "label": "证据账本",
            "status": "blocked" if blocking_unknowns else "completed",
            "detail": (
                "等待关闭阻塞性证据缺口。" if blocking_unknowns
                else "来源、适用范围与可信门禁已进入候选评分。"
            ),
            "parent_substep_id": "search_route",
            "output_ref": "evidence_ledger",
        },
        {
            "substep_id": "candidate_search",
            "label": "多候选搜索",
            "status": "blocked" if blocking_unknowns else "completed",
            "detail": "在共同依赖图上生成不同优先级策略。",
            "depends_on": ["search_ledger"],
            "output_ref": "candidate_set",
        },
    ])
    for candidate in candidates:
        search_steps.append({
            "substep_id": f"candidate_{candidate['candidate_id']}",
            "label": candidate["title"],
            "status": "completed" if candidate["hard_gate_passed"] else "blocked",
            "detail": f"加权分 {candidate['weighted_score']}；{len(candidate['parallel_waves'])} 个依赖波次。",
            "parent_substep_id": "candidate_search",
            "output_ref": candidate["candidate_id"],
        })

    gate_status: PlanStageStatus = (
        "blocked" if decision["code"] == "REQUEST_EVIDENCE"
        else "completed" if confirmed
        else "ready"
    )
    critic_steps: list[dict[str, Any]] = [{
        "substep_id": "critic_committee",
        "label": "六维 Critic 委员会",
        "status": "completed",
        "detail": "评审结论只作用于 Plan 门禁，不写入学习掌握证据。",
        "output_ref": "critic_report.json",
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
            "status": "completed" if confirmed else gate_status,
            "detail": "确认只推进 Plan 状态，不代表任务已经执行。",
            "parent_substep_id": "decision_select",
            "output_ref": "task_plan.json" if confirmed else "awaiting_confirmation",
        },
    ])

    execution_checklist = [{
        "package_id": item["package_id"],
        "objective": item["objective"],
        "status": "pending",
        "expected_artifact": item["expected_artifact"],
        "observation_state": "not_observed",
        "completion_condition": item["completion_condition"],
    } for item in packages]
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
            "status": "pending",
            "detail": f"已形成 {len(packages)} 个待执行工作包；当前没有运行证据。",
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
        {"stage_id": "grounding_clarification", "sequence": 2, "label": "环境落地与澄清", "status": "blocked" if blocking_unknowns else "completed", "summary": "读取现状并显式形成目标、范围、成功标准与停止条件。", "input_refs": ["task_contract", "run_state"], "output_refs": ["task_specification", "clarification_register"], "substeps": grounding_steps},
        {"stage_id": "hierarchical_planning", "sequence": 3, "label": "分层规划", "status": "completed", "summary": "Goal → Phase → Work Package → Atomic Step，并计算 DAG 与关键路径。", "input_refs": ["task_specification"], "output_refs": ["hierarchy.json", "topological_schedule.json"], "substeps": hierarchy_steps},
        {"stage_id": "evidence_candidate_search", "sequence": 4, "label": "证据与候选搜索", "status": "blocked" if blocking_unknowns else "completed", "summary": "经证据路由与账本生成三类可比较候选。", "input_refs": ["hierarchy.json", "allowed_tools"], "output_refs": ["evidence_ledger", "candidate_set"], "substeps": search_steps},
        {"stage_id": "critic_finalize", "sequence": 5, "label": "Critic 门禁与定稿", "status": gate_status, "summary": "六维独立评审驱动补证据、局部重规划、选定与确认。", "input_refs": ["candidate_set", "evidence_ledger"], "output_refs": ["critic_report.json", "proposed_plan.json", "task_plan.json" if confirmed else "awaiting_confirmation"], "substeps": critic_steps},
        {"stage_id": "execution_handoff", "sequence": 6, "label": "执行观察与交接", "status": "pending", "summary": "仅生成待运行清单和交接契约；尚无执行、观察或掌握证据。", "input_refs": ["task_plan.json"], "output_refs": ["execution_checklist", "delivery_bundle", "feedback_contract"], "substeps": execution_steps},
    ]
    return stages, execution_checklist, handoff_artifacts


def build_planning_analysis(run_payload: dict[str, Any]) -> dict[str, Any]:
    run = LearningTaskPlanRun.model_validate(run_payload).model_dump(mode="json")
    plan = run["plan"]
    packages = plan["work_packages"]
    package_ids = [item["package_id"] for item in packages]
    waves = _topological_waves(packages)
    hierarchy = _build_hierarchy(packages, plan["goal"])
    critics = _critics(run, packages)
    risks = _risks(run, packages)
    candidates = _candidates(run, packages, waves, critics)
    blocking = sum(1 for item in plan.get("unknowns") or [] if item.get("blocking"))
    eligible = [item for item in candidates if item["hard_gate_passed"]]
    selected = max(eligible, key=lambda item: item["weighted_score"], default=None)
    if blocking:
        decision = {
            "code": "REQUEST_EVIDENCE",
            "selected_candidate_id": None,
            "confidence": 82,
            "reasons": [f"检测到 {blocking} 个阻塞性证据缺口，候选不能进入执行。"],
            "triggered_rules": ["EVIDENCE_BLOCKING_UNKNOWN"],
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
        status = "ready_for_confirmation" if run["phase"] == "CONTRACT_READY" else "planned_not_executed"
    else:
        decision = {
            "code": "LOCAL_REPLAN",
            "selected_candidate_id": None,
            "confidence": 64,
            "reasons": ["至少一个硬门禁未通过，需要修订受影响子图。"],
            "triggered_rules": ["CRITIC_GATE_REJECT"],
        }
        status = "planned_not_executed"
    critical_path = _critical_path(packages)
    stages, execution_checklist, handoff_artifacts = _build_stages(
        run, hierarchy, waves, critical_path, candidates, critics, decision,
    )
    analysis = {
        "schema_version": "learning-work-task-planning-analysis-v2",
        "run_id": run["run_id"],
        "plan_version": plan["plan_version"],
        "analysis_version": 1,
        "planning_status": status,
        "active_revision_id": "revision_1",
        "hierarchy": hierarchy,
        "graph_edges": _build_edges(packages, hierarchy),
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
        "revision_history": [_initial_revision(run, package_ids)],
        "repair_budget_remaining": plan["repair_budget"],
        "metrics": {
            "hierarchy_nodes": len(hierarchy),
            "dependency_edges": sum(len(item.get("depends_on") or []) for item in packages),
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
    packages = run["plan"]["work_packages"]
    package_ids = [item["package_id"] for item in packages]
    if target_package_id not in package_ids:
        raise ValueError("局部重规划目标工作包不存在")

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
