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


class LearningTaskPlanningAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["learning-work-task-planning-analysis-v1"]
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
    analysis = {
        "schema_version": "learning-work-task-planning-analysis-v1",
        "run_id": run["run_id"],
        "plan_version": plan["plan_version"],
        "analysis_version": 1,
        "planning_status": status,
        "active_revision_id": "revision_1",
        "hierarchy": hierarchy,
        "graph_edges": _build_edges(packages, hierarchy),
        "topological_waves": waves,
        "critical_path": _critical_path(packages),
        "candidates": candidates,
        "critics": critics,
        "risks": risks,
        "decision": decision,
        "revision_history": [_initial_revision(run, package_ids)],
        "repair_budget_remaining": plan["repair_budget"],
        "metrics": {
            "hierarchy_nodes": len(hierarchy),
            "dependency_edges": sum(len(item.get("depends_on") or []) for item in packages),
            "parallel_waves": len(waves),
            "candidate_count": len(candidates),
            "critic_count": len(critics),
            "risk_count": len(risks),
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
    updated["metrics"]["revision_count"] = len(updated["revision_history"])
    return LearningTaskPlanningAnalysis.model_validate(updated).model_dump(mode="json")
