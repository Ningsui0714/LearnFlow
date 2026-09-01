"""Executable architecture authority for LearnFlow.

This registry is deliberately boring: it does not route requests or let an
LLM select policy. It defines ownership and contracts so agents, tools,
workbenches and evidence events can be inspected and checked for drift.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from app.services.action_board import ACTION_BOARD


REGISTRY_VERSION = "2026-09-01.1"
EVENT_SCHEMA_VERSION = "learnflow.evidence.v1"
SKILL_SPEC_VERSION = "learnflow.skill.v3"
# The learner-facing SkillSpec changed in this registry release.
FRONTEND_SKILL_MANIFEST_REGISTRY_VERSION = "2026-08-29.1"
KERNEL_NAMES = ("structure", "knowledge", "human", "value", "practice")
LIFECYCLE_STATES = ("implemented", "optional_unimplemented", "deprecated")
PLUGIN_PACKAGE_PROTOCOL = "learnflow.plugin-package.v1"
PLUGIN_REGISTRY_PROJECTION_PROTOCOL = "learnflow.plugin-registry-projection.v1"
_PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,127}$")
_PLUGIN_LOCAL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")

# This is the canonical allow-list used by Tutor semantic observations. The
# runtime imports it instead of maintaining a second copy.
SEMANTIC_MEMORY_KEYS = {
    "structure": {
        "path_position", "path_dependencies", "resume_anchor",
        "focus_transition", "deferred_threads", "navigation_blocker",
    },
    "knowledge": {
        "concept_understanding", "knowledge_gap", "pending_question",
        "misconceptions", "active_concepts", "recent_errors", "retention_status",
    },
    "human": {
        "affect", "cognitive_load", "attention", "frustration",
        "pace_preference", "format_preference", "pace_adjustment",
        "format_request", "support_need",
    },
    "value": {
        "current_priority", "current_motivation", "goal_candidate",
        "interest_signal", "relevance_reason",
    },
    "practice": {
        "current_attempt", "assistance_level", "artifact_state",
        "recent_feedback", "transfer_readiness", "review_history",
    },
}


@dataclass(frozen=True)
class AgentContract:
    id: str
    name: str
    plane: str
    components: tuple[str, ...]
    input_contract: tuple[str, ...]
    output_contract: tuple[str, ...]
    kernel_access: str
    must_not: tuple[str, ...]


@dataclass(frozen=True)
class ChatModeContract:
    id: str
    name: str
    owner_agent: str
    skills: tuple[str, ...]
    boundary: str
    completion: str


@dataclass(frozen=True)
class KernelContract:
    id: str
    question: str
    short_term_keys: tuple[str, ...]
    long_term_rule: str
    fact_role: str
    module_role: str
    claim_role: str
    claim_mode: str
    shared_subjects: tuple[str, ...]
    hard_boundaries: tuple[str, ...]
    writer: str = "five_kernel_reducer"


@dataclass(frozen=True)
class ToolContract:
    id: str
    name: str
    owner: str
    origin: str
    mode: str
    reads_kernels: tuple[str, ...] = ()
    writes_kernels: tuple[str, ...] = ()
    write_path: str = "none"


@dataclass(frozen=True)
class SkillStateContract:
    id: str
    title: str
    short_title: str
    substate_id: str
    substate_label: str
    instructional_objective: str
    tutor_instruction: str
    next_action: str
    accepted_signals: tuple[str, ...] = ("attempt",)
    can_loop: bool = True
    requires_learner_reply: bool = True
    loop_instruction: str = "缩小当前动作并补一层支架；不得把提示后的回应当作独立完成。"


@dataclass(frozen=True)
class SkillCalibrationAxisContract:
    id: str
    title: str
    description: str
    options: tuple[tuple[str, str], ...]
    default: str


@dataclass(frozen=True)
class SkillRuntimeContract:
    version: str
    bound_chat_modes: tuple[str, ...]
    initial_state: str
    states: tuple[SkillStateContract, ...]
    turn_budget: int
    verification_required: bool
    required_context: tuple[str, ...]
    input_objects: tuple[str, ...]
    output_objects: tuple[str, ...]
    allowed_event_types: tuple[str, ...]
    evidence_policy: str
    failure_policy: str
    eval_suite: str
    knowledge_requirements: dict[str, Any]
    calibration_axes: tuple[SkillCalibrationAxisContract, ...] = ()
    maturity: str = "production_candidate"


@dataclass(frozen=True)
class SkillContract:
    id: str
    name: str
    owner_agent: str
    tools: tuple[str, ...]
    output_contract: str
    strategy_authority: str
    origin: str = "learnflow"
    learner_selectable: bool = False
    description: str = ""
    invocation_prompt: str = ""
    aliases: tuple[str, ...] = ()
    best_for: tuple[str, ...] = ()
    avoid_when: tuple[str, ...] = ()
    atomic_task_capable: bool = False
    spec_version: str = SKILL_SPEC_VERSION
    runtime: SkillRuntimeContract | None = None


@dataclass(frozen=True)
class WorkbenchContract:
    id: str
    name: str
    surface: str
    owner_agent: str
    capabilities: tuple[str, ...]
    origin: str = "learnflow"


@dataclass(frozen=True)
class EventContract:
    id: str
    owner_agent: str
    capability: str
    tool: str
    workbench: str
    kernel_targets: tuple[str, ...]
    evidence_role: str
    origin: str = "learnflow"
    payload_version: str | None = None
    reducer_binding: str | None = None


@dataclass(frozen=True)
class ImplementationBinding:
    id: str
    kind: str
    module: str = ""
    symbol: str = ""
    path: str = ""
    method: str = ""
    route: str = ""
    endpoint: str = ""
    member: str = ""


@dataclass(frozen=True)
class PublicationContract:
    lifecycle: str
    bindings: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class HostInterfaceContract:
    id: str
    mode: str
    provider: str
    input_contract: str
    output_contract: str
    write_boundary: str
    content_trust: str = "trusted_metadata"


@dataclass(frozen=True)
class PluginContract:
    id: str
    package_protocol: str
    release_version: str
    owner_agent: str
    scope: str
    object_types: tuple[str, ...]
    host_interfaces: tuple[str, ...]
    workflows: tuple[str, ...]
    tools: tuple[str, ...]
    skills: tuple[str, ...]
    surface_slots: tuple[str, ...]
    events: tuple[str, ...]
    kernel_allow_list: tuple[str, ...]
    manifest_path: str
    execution_boundary: str


# Three primary contracts are responsibility families, not three competing
# chat personas. Concrete domain workers stay behind the corresponding
# structured interface.
AGENTS = {
    item.id: item for item in (
        AgentContract(
            "tutor_agent", "Tutor 控制 Agent", "control",
            ("global_main_agent", "project_tutor", "checkpoint_tutor", "learning_task_runtime"),
            ("current_learner", "page_context", "five_kernel_context_packet", "recent_evidence"),
            ("structured_intent", "reply", "action_proposal", "handoff_refs"),
            "read projections; emit events through Action Board",
            ("direct database writes", "claim mastery", "bypass confirmation policy"),
        ),
        AgentContract(
            "learning_design_agent", "学习设计 Agent", "capability",
            ("roadmap_agent", "learning_task_planner", "lecture_agent", "concept_agent", "animation_agent"),
            ("project_brief", "processed_sources", "learner_projection", "provenance"),
            ("roadmap_proposal", "lecture_artifact", "assessment_spec", "visual_artifact"),
            "read scoped projections; artifacts never mutate mastery",
            ("apply roadmap without confirmation", "invent source provenance", "write kernels"),
        ),
        AgentContract(
            "practice_agent", "实践与验证 Agent", "capability",
            ("exercise_agent", "code_agent", "remediation_renderer"),
            ("assessment_spec", "submission", "test_result", "error_evidence"),
            ("practice_artifact", "feedback", "explanation_sections"),
            "read scoped projections; assessed events enter the reducer",
            ("choose remediation policy", "override deterministic grading", "write kernels"),
        ),
    )
}


# These are Tutor postures, not additional Agents. Project and checkpoint are
# product scopes; LearningTask and SkillRun remain the durable runtimes.
CHAT_MODES = {
    item.id: item for item in (
        ChatModeContract(
            "free", "自由探索", "tutor_agent", ("intent_and_handoff",),
            "直接回应开放问题，并把清楚的短期、深度或长期意图收敛到其他模式",
            "检测到明确意图时塌陷；否则保持自由",
        ),
        ChatModeContract(
            "explain", "简单讲解", "tutor_agent", ("guided_explanation",),
            "完成一个边界清楚的定义、区别或最小示例，不自动创建 LearningTask",
            "讲解交付后标记完成，下一轮从自由模式重新判断",
        ),
        ChatModeContract(
            "learn", "学习任务引导", "tutor_agent",
            ("atomic_learning_loop", "guided_explanation", "socratic_dialogue",
             "feynman_dialogue", "worked_example_fading"),
            "围绕一个 LearningTask 组合讲解、练习、验证、纠错与复习转交",
            "任务或 SkillRun 结束、退出或明确转向后返回自由",
        ),
        ChatModeContract(
            "plan", "学习规划", "tutor_agent",
            ("intent_and_handoff", "learning_path_planning"),
            "澄清跨多个任务、来源、阶段或真实产物的目标，并优先形成项目提案",
            "提案完成、接受、放弃或明确转向后返回自由",
        ),
    )
}


KERNELS = {
    item.id: item for item in (
        KernelContract("structure", "学习者走到哪里，怎样离开与返回",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["structure"])),
                       "Only stable path patterns and confirmed project structure may consolidate.",
                       "Event-backed navigation, dependency and boundary observations.",
                       "A replaceable route or boundary snapshot; it may remain state-first with one compact anchor claim.",
                       "Optional factual anchor about position or dependency, never a mastery statement.",
                       "sparse_anchor", ("course", "concept", "project", "checkpoint", "task"),
                       ("Learning-path self-report never implies knowledge mastery.",)),
        KernelContract("knowledge", "对哪个知识点理解到什么程度",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["knowledge"])),
                       "Two explicit same-concept self-reports may consolidate only as an exposure boundary; mastery and misconception require graded or explicitly correctable evidence.",
                       "Concept attempts, misconceptions, questions, retention and correction facts.",
                       "Concept-scoped evidence synthesis shared by subject key with Structure but independently authoritative.",
                       "Testable concept claim with explicit evidence grade and correction history.",
                       "evidence_claims", ("course", "concept", "checkpoint", "task"),
                       ("Exposure and self-report cannot become mastery.", "Mastery requires repeated verified evidence.")),
        KernelContract("human", "当前怎样教更合适",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["human"])),
                       "Preferences consolidate after explicit confirmation or cross-session evidence.",
                       "Explicit preferences plus bounded, time-sensitive load and support observations.",
                       "A compact adaptation directive; transient sensitive facts normally expire before module synthesis.",
                       "Sparse learner-correctable teaching directive, not a personality or diagnosis label.",
                       "directive_claims", ("preference", "session", "task"),
                       ("No personality, medical or fixed learning-style inference.", "Sensitive content is excluded from ordinary Agent context.")),
        KernelContract("value", "为什么学，什么更值得投入",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["value"])),
                       "Long-term goals require explicit learner confirmation.",
                       "Goal proposals, confirmed goals, interests, relevance and priority observations.",
                       "A learner-visible goal or interest trajectory; proposals remain short-lived until explicit confirmation.",
                       "Confirmed direction or stable relevance claim with the learner's original evidence quote.",
                       "consent_claims", ("goal", "course", "project", "task"),
                       ("Planning tools may propose but never silently confirm a long-term goal.",)),
        KernelContract("practice", "能否独立做出来",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["practice"])),
                       "Independent and transfer attempts outrank assisted completion.",
                       "Attempts, assistance level, artifacts, feedback, transfer and project performance facts.",
                       "Artifact or task scoped performance history; event/fact-first and often richer than a generic summary module.",
                       "Bounded capability claim that states assistance and transfer conditions; optional until evidence is sufficient.",
                       "performance_claims", ("practice", "artifact", "project", "checkpoint", "task"),
                       ("Assisted success and original-item retry never become independent transfer.", "Project evidence may outlive a single learning session.")),
    )
}


HOST_INTERFACES = {
    item.id: item for item in (
        HostInterfaceContract(
            "project.read.v1", "read", "project_service",
            "project-scoped identity request", "owned Project identity and goal scope",
            "read only; ownership is revalidated on every call",
        ),
        HostInterfaceContract(
            "source.read.v1", "read", "source_version_runtime",
            "fixed source ids and bounded chunk budget", "immutable SourceVersion refs and bounded Chunks",
            "read only; never returns another project", "untrusted_content",
        ),
        HostInterfaceContract(
            "knowledge_baseline.read.v1", "read", "domain_knowledge_packet_compiler",
            "project packet ids or bounded query", "confirmed DomainKnowledgePacket projection",
            "read only; domain truth never implies learner mastery",
        ),
        HostInterfaceContract(
            "roadmap.read.v1", "read", "project_roadmap_reader",
            "current project scope", "versioned Roadmap and checkpoint DAG",
            "read only; changes require an Action Board proposal",
        ),
        HostInterfaceContract(
            "checkpoint.read.v1", "read", "checkpoint_context",
            "owned checkpoint ids", "checkpoint brief and teaching contract",
            "read only; direct checkpoint mutation is forbidden",
        ),
        HostInterfaceContract(
            "learning_task.read.v1", "read", "learning_task_runtime",
            "owned task ids and bounded list", "formal LearningTask refs and versions",
            "read only; changes require an Action Board proposal",
        ),
        HostInterfaceContract(
            "learning_file.read.v1", "read", "learning_file_service",
            "owned managed file refs", "answer-safe lecture and practice projection",
            "read only; hidden answers and judge data are excluded",
        ),
        HostInterfaceContract(
            "learner_context.read.v1", "read", "context_packet_assembler",
            "manifest kernel allow-list plus project scope", "bounded answer-safe ContextPacket",
            "no Kernel write interface exists",
        ),
        HostInterfaceContract(
            "artifact.resolve.v1", "read", "managed_artifact_service",
            "typed ArtifactRef or fixed PluginObjectRef", "verified immutable artifact or object projection",
            "does not provide arbitrary filesystem or database access",
        ),
        HostInterfaceContract(
            "model.generate_structured.v1", "host_mediated", "plugin_host",
            "bounded prompt and JSON schema", "schema-validated structured candidate",
            "host owns credential, budget and audit; plugin never receives model secrets",
        ),
        HostInterfaceContract(
            "action.propose.v1", "proposal", "action_board",
            "registered core capability plus fixed PluginObjectRef", "learner-visible Action Board proposal",
            "never executes the side effect inside the plugin process",
        ),
        HostInterfaceContract(
            "event.record.v1", "event_gateway", "evidence_ledger",
            "manifest-declared zero-target plugin event", "scoped append-only EvidenceEvent",
            "external plugin events cannot declare Kernel targets",
        ),
    )
}


PLUGIN_CONTRACTS = {
    item.id: item for item in (
        PluginContract(
            id="role_capability_graph",
            package_protocol="learnflow.plugin-package.v1",
            release_version="1.0.0",
            owner_agent="learning_design_agent",
            scope="project",
            object_types=(
                "role", "task", "capability", "knowledge_skill", "claim",
                "semantic_edge", "scenario", "process_event", "actor",
                "work_object", "artifact", "risk", "bridge",
            ),
            host_interfaces=(
                "project.read.v1", "source.read.v1", "knowledge_baseline.read.v1",
                "model.generate_structured.v1", "event.record.v1",
            ),
            workflows=("generate", "explain", "iterate", "validate", "upgrade"),
            tools=("read_graph", "explain"),
            skills=("role_capability_graphing",),
            surface_slots=("project.context.tabs",),
            events=("package_generated", "snapshot_iterated", "snapshot_explained", "release_upgraded"),
            kernel_allow_list=(),
            manifest_path="plugins/role_capability_graph/manifest.json",
            execution_boundary=(
                "built-in Agent Package behind deterministic Plugin Host; optional signed native runner is distribution-only"
            ),
        ),
        PluginContract(
            id="learning_task_conversion",
            package_protocol="learnflow.plugin-package.v1",
            release_version="1.0.0",
            owner_agent="learning_design_agent",
            scope="project",
            object_types=(
                "learning_task", "task_step", "knowledge_point", "skill_point",
                "task_relation", "learning_resource", "review_note",
            ),
            host_interfaces=(
                "project.read.v1", "source.read.v1", "knowledge_baseline.read.v1",
                "model.generate_structured.v1", "event.record.v1",
            ),
            workflows=("generate", "revise", "review", "handoff"),
            tools=("read_task", "prepare_handoff"),
            skills=("learning_task_planning",),
            surface_slots=("project.context.tabs",),
            events=("task_generated", "revision_submitted", "handoff_prepared"),
            kernel_allow_list=(),
            manifest_path="plugins/learning_task_conversion/manifest.json",
            execution_boundary=(
                "built-in Agent Package behind deterministic Plugin Host with a repository-owned central workspace binding"
            ),
        ),
    )
}


def _plugin_manifest_items(
    manifest: Mapping[str, Any], field: str,
) -> list[dict[str, Any]]:
    value = manifest.get(field, [])
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _plugin_local_ids(
    manifest: Mapping[str, Any], field: str,
) -> list[str]:
    return [str(item.get("id") or "") for item in _plugin_manifest_items(manifest, field)]


def _plugin_qualified_id(plugin_id: str, kind: str, local_id: str) -> str:
    if kind == "tool":
        # This is the exact identifier accepted by call_project_plugin_tool.
        return f"{plugin_id}:{local_id}"
    if kind == "event":
        # This is the exact zero-target event type admitted by event.record.v1.
        return f"plugin:{plugin_id}:{local_id}"
    return f"{plugin_id}:{kind}:{local_id}"


def validate_plugin_manifest_projection(manifest: Mapping[str, Any]) -> list[str]:
    """Validate one installable manifest before it contributes registry rows.

    Installed packages contribute only namespaced projections.  They can bind
    to one of the three existing Agent owners and registered Host Interfaces,
    but cannot publish primary Agents, reuse core IDs, or introduce an event
    that can reach the five-kernel reducer.
    """

    errors: list[str] = []
    plugin_id = str(manifest.get("plugin_id") or "")
    if manifest.get("protocol") != PLUGIN_PACKAGE_PROTOCOL:
        errors.append("plugin manifest must use learnflow.plugin-package.v1")
    if not _PLUGIN_ID_PATTERN.fullmatch(plugin_id):
        errors.append("plugin_id must be a lowercase stable identifier")
    owner = str(manifest.get("owner") or "")
    if owner not in AGENTS:
        errors.append("plugin owner must be one of the three primary Agents")
    if manifest.get("scope") != "project":
        errors.append("plugin instance scope must be project")
    forbidden_contribution_fields = {
        "agents": "primary Agents",
        "primary_agents": "primary Agents",
        "agent_contracts": "primary Agents",
        "capabilities": "core capabilities",
        "workbenches": "core workbenches",
        "reducers": "Kernel reducers",
        "kernel_mutations": "Kernel mutations",
    }
    for field, label in forbidden_contribution_fields.items():
        if manifest.get(field):
            errors.append(f"plugin manifest cannot contribute {label}: {field}")
    explicit_namespace = manifest.get("namespace")
    if explicit_namespace is not None and str(explicit_namespace) != f"plugin:{plugin_id}":
        errors.append("plugin manifest cannot override its deterministic namespace")

    kernel_allow_list = manifest.get("kernel_allow_list", [])
    if not isinstance(kernel_allow_list, list):
        errors.append("kernel_allow_list must be an array")
    elif len({str(item) for item in kernel_allow_list}) != len(kernel_allow_list):
        errors.append("kernel_allow_list must contain unique Kernels")
    elif set(str(item) for item in kernel_allow_list) - set(KERNEL_NAMES):
        errors.append("plugin kernel_allow_list contains an unknown Kernel")

    host_ports = manifest.get("host_ports", [])
    if not isinstance(host_ports, list):
        errors.append("host_ports must be an array")
        host_ports = []
    elif len({str(item) for item in host_ports}) != len(host_ports):
        errors.append("host_ports must contain unique Host Interfaces")
    unknown_ports = sorted(set(str(item) for item in host_ports) - set(HOST_INTERFACES))
    if unknown_ports:
        errors.append(f"plugin manifest references unknown Host Interfaces: {', '.join(unknown_ports)}")

    object_types = manifest.get("object_types", [])
    if not isinstance(object_types, list) or not object_types:
        errors.append("plugin manifest must declare object_types")
        object_types = []
    if len({str(item) for item in object_types}) != len(object_types):
        errors.append("plugin manifest object_types must be unique")
    if any(not _PLUGIN_LOCAL_ID_PATTERN.fullmatch(str(item)) for item in object_types):
        errors.append("plugin object type must be a local stable identifier")

    registered_plugin = PLUGIN_CONTRACTS.get(plugin_id)
    allowed_core_local_ids = set()
    if registered_plugin:
        allowed_core_local_ids.update(registered_plugin.workflows)
        allowed_core_local_ids.update(registered_plugin.tools)
        allowed_core_local_ids.update(registered_plugin.skills)
        allowed_core_local_ids.update(registered_plugin.events)
    reserved_core_ids = (
        set(AGENTS) | set(KERNELS) | set(TOOLS) | set(SKILLS) |
        set(WORKBENCHES) | set(ACTION_BOARD) | set(EVENTS) |
        set(HOST_INTERFACES)
    ) - allowed_core_local_ids

    item_fields = {
        "workflows": "workflow",
        "tools": "tool",
        "skills": "skill",
        "surfaces": "surface",
        "events": "event",
    }
    workflow_items = _plugin_manifest_items(manifest, "workflows")
    declared_workflows = set(_plugin_local_ids(manifest, "workflows"))
    workflow_by_id = {
        str(item.get("id") or ""): item
        for item in workflow_items
        if item.get("id")
    }
    for field, kind in item_fields.items():
        raw = manifest.get(field, [])
        if not isinstance(raw, list):
            errors.append(f"plugin manifest {field} must be an array")
            continue
        items = _plugin_manifest_items(manifest, field)
        if len(items) != len(raw):
            errors.append(f"plugin manifest {field} entries must be objects")
        ids = [str(item.get("id") or "") for item in items]
        if len(set(ids)) != len(ids):
            errors.append(f"plugin manifest {field} ids must be unique")
        for item, local_id in zip(items, ids):
            if not _PLUGIN_LOCAL_ID_PATTERN.fullmatch(local_id):
                errors.append(f"plugin {kind} id must be a local stable identifier: {local_id or '<empty>'}")
                continue
            if local_id in reserved_core_ids:
                errors.append(f"plugin {kind} cannot override core registry id: {local_id}")
            qualified_id = _plugin_qualified_id(plugin_id, kind, local_id)
            for explicit_field in ("qualified_id", "registry_id", "core_id"):
                explicit_id = item.get(explicit_field)
                if explicit_id is not None and str(explicit_id) != qualified_id:
                    errors.append(
                        f"plugin {kind} cannot override its deterministic namespace: {local_id}"
                    )
            for owner_field in ("owner", "owner_agent"):
                item_owner = item.get(owner_field)
                if item_owner is not None and str(item_owner) not in AGENTS:
                    errors.append(
                        f"plugin {kind} owner must be one of the three primary Agents: {local_id}"
                    )
            if kind == "event" and list(
                item.get("kernel_targets", item.get("target_kernels", [])) or []
            ):
                errors.append(f"external plugin event cannot target Kernels: {local_id}")
            if kind in {"tool", "skill"}:
                workflow_refs: list[str] = []
                if kind == "tool" and item.get("workflow") is not None:
                    workflow_refs = [str(item.get("workflow"))]
                elif kind == "skill":
                    workflow_refs = [str(value) for value in list(item.get("workflows") or [])]
                unknown_workflows = sorted(set(workflow_refs) - declared_workflows)
                if unknown_workflows:
                    errors.append(
                        f"plugin {kind} references unknown workflows: {local_id}:"
                        f"{','.join(unknown_workflows)}"
                    )
                if kind == "tool" and item.get("mode") == "read" and workflow_refs:
                    target = workflow_by_id.get(workflow_refs[0])
                    if target and str(target.get("mode") or "").casefold() != "read":
                        errors.append(
                            f"plugin read tool must reference a read workflow: {local_id}"
                        )
                    required_ports = (
                        target.get(
                            "host_ports",
                            target.get("required_host_ports", manifest.get("host_ports", [])),
                        )
                        if target else []
                    )
                    if isinstance(required_ports, list) and {
                        "action.propose.v1", "event.record.v1"
                    } & set(required_ports):
                        errors.append(
                            f"plugin read tool cannot use write Host Ports: {local_id}"
                        )
    return errors


def plugin_registry_projection(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the order-independent namespaced projection of one manifest."""

    errors = validate_plugin_manifest_projection(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    plugin_id = str(manifest["plugin_id"])
    owner = str(manifest["owner"])

    def rows(field: str, kind: str) -> list[dict[str, Any]]:
        result = []
        for item in sorted(_plugin_manifest_items(manifest, field), key=lambda value: str(value["id"])):
            local_id = str(item["id"])
            row = {
                "id": _plugin_qualified_id(plugin_id, kind, local_id),
                "local_id": local_id,
                "owner_agent": str(item.get("owner") or item.get("owner_agent") or owner),
            }
            if kind == "tool":
                mode = str(item.get("mode") or "")
                row.update({
                    "mode": mode,
                    "model_exposure": "project_discovery" if mode == "read" else "not_model_callable",
                })
            if kind == "event":
                row["kernel_targets"] = []
            result.append(row)
        return result

    return {
        "protocol": PLUGIN_REGISTRY_PROJECTION_PROTOCOL,
        "plugin_id": plugin_id,
        "release_version": str(manifest.get("version") or ""),
        "owner_agent": owner,
        "scope": "project",
        "namespace": f"plugin:{plugin_id}",
        "object_types": [
            {
                "id": _plugin_qualified_id(plugin_id, "object", local_id),
                "local_id": local_id,
            }
            for local_id in sorted(str(item) for item in manifest.get("object_types", []))
        ],
        "host_interfaces": [
            {"id": interface_id, "mode": HOST_INTERFACES[interface_id].mode}
            for interface_id in sorted(str(item) for item in manifest.get("host_ports", []))
        ],
        "workflows": rows("workflows", "workflow"),
        "tools": rows("tools", "tool"),
        "skills": rows("skills", "skill"),
        "surfaces": rows("surfaces", "surface"),
        "events": rows("events", "event"),
        "kernel_allow_list": sorted(str(item) for item in manifest.get("kernel_allow_list", [])),
    }


TOOLS = {
    item.id: item for item in (
        ToolContract("action_board", "Action Board", "tutor_agent", "learnflow", "transaction",
                     KERNEL_NAMES, (), "EvidenceEvent"),
        ToolContract(
            "plugin_package_runtime", "Signed LearnFlow Plugin Package Host", "tutor_agent",
            "learnflow", "harness", (), (),
            ".lfplugin validation + publisher trust + immutable release/instance/snapshot/object/run contracts; no direct core-object or Kernel write",
        ),
        ToolContract(
            "plugin_process_runner", "Trusted Signed Plugin Process Broker", "tutor_agent",
            "learnflow", "harness", (), (),
            "fixed argv + sanitized environment + bounded JSON-RPC/Host Ports in a fresh process; filesystem/network/secrets/CPU/memory remain explicitly unisolated",
        ),
        ToolContract(
            "discover_project_plugin_tools", "Project Plugin Tool Discovery", "tutor_agent",
            "learnflow", "read", KERNEL_NAMES, (),
            "owned project + enabled signed release + grants -> bounded read-only qualified tool schemas",
        ),
        ToolContract(
            "call_project_plugin_tool", "Project Plugin Read-only Tool Dispatcher", "tutor_agent",
            "learnflow", "read", KERNEL_NAMES, (),
            "previously discovered qualified tool + pinned snapshot -> audited read-only plugin result; side effects are rejected",
        ),
        ToolContract(
            "plugin_action_proposer", "Plugin-to-Action Board Proposal Gateway", "tutor_agent",
            "learnflow", "proposal", (), (),
            "fixed PluginObjectRef + registered core capability -> learner confirmation proposal; plugin never executes core mutation",
        ),
        ToolContract("tutor_context", "Tutor Context Assembler", "tutor_agent", "learnflow", "read",
                     KERNEL_NAMES),
        ToolContract("chat_mode_runtime", "Deterministic Chat Mode Runtime", "tutor_agent", "learnflow", "orchestration",
                     KERNEL_NAMES, (), "AgentSession context + registered EvidenceEvent only"),
        ToolContract("vnext_agent_turn_runtime", "vNext Bounded Agent Turn Graph", "tutor_agent", "vnext", "orchestration",
                     KERNEL_NAMES, (), "typed ContextEnvelope -> bounded observe/act/observe loop -> structured AgentTurnTrace; read-only model tools and no direct learner-state write"),
        ToolContract("vnext_chat_session_store", "vNext Cross-browser Chat Session Store", "tutor_agent", "vnext", "adapter",
                     (), (), "learner-owned AgentSession + idempotent AgentMessage projection; browser cache is non-authoritative and persistence creates no learning evidence"),
        ToolContract("computer_knowledge_search", "Explanation-oriented Computer Knowledge Search", "learning_design_agent", "vnext", "read",
                     (), (), "privacy scrub -> bounded facet plan -> tiered adapters + circuit breakers -> hybrid deterministic rerank/MMR -> coverage audit -> one bounded gap search -> versioned untrusted evidence bundle; quick/standard/deep budgets and no learner-state write"),
        ToolContract("web_evidence_reader", "Allow-listed Web Evidence Reader", "learning_design_agent", "vnext", "read",
                     (), (), "exact URL from current search -> HTTPS/redirect/content guards -> query-relevant bounded page excerpt -> untrusted evidence page; cacheable and no learner-state write"),
        ToolContract("learning_video_search", "Goal-aligned Learning Video Search", "learning_design_agent", "vnext", "read",
                     (), (), "structured learning target -> bounded Bilibili/YouTube adapters + offline catalog -> discovered candidate IDs and metadata; no content or mastery claim"),
        ToolContract("learning_video_inspector", "Current-turn Learning Video Inspector", "learning_design_agent", "vnext", "read",
                     (), (), "candidate ID from current search -> subtitle/ASR availability + timestamped relevant segments + outcome gaps + answer-leak audit; zero learner-state write"),
        ToolContract("teaching_contract_gate", "Deterministic Teaching Contract Gate", "learning_design_agent", "learnflow", "policy",
                     (), (), "DomainKnowledgePacketRef + TeachingContentBrief -> ready | ready_with_gaps | blocked_knowledge; blocked knowledge never publishes a generic scaffold"),
        ToolContract("source_version_runtime", "Immutable Source Version Runtime", "learning_design_agent", "learnflow", "harness",
                     (), (), "learner-owned Source + inspected content hash -> immutable SourceVersion + version-bound Chunk history; zero learner-state write"),
        ToolContract("domain_knowledge_packet_compiler", "Scoped Domain Knowledge Packet Compiler", "learning_design_agent", "learnflow", "harness",
                     (), (), "DomainBrief + uploaded/project/curated/temporary evidence -> versioned claim-level DomainKnowledgePacket with source closure, coverage, freshness and conflicts; zero learner-state write"),
        ToolContract("source_integrity_monitor", "Source Integrity and Freshness Monitor", "learning_design_agent", "learnflow", "policy",
                     (), (), "hash/version/freshness/injection/conflict checks -> active | stale | conflicted | quarantined | superseded; affected packets become stale without changing mastery"),
        ToolContract("checkpoint_delivery_readiness", "Teaching Package and Atomic Task Readiness Projection", "learning_design_agent", "learnflow", "projection",
                     (), (), "existing Source/Lecture/Question/Exercise/Assessment -> package readiness; learner-owned LearningTask -> task readiness; optional answer-free Knowledge ContextPacket stays a separate read-only design input; compatibility summary retained and no mastery inference"),
        ToolContract("safe_visual_generation", "Shared Learning VisualSpec Runtime", "learning_design_agent", "vnext", "harness",
                     (), (), "explicit learner visual intent + bounded request/prior-artifact topic anchor -> exact/illustrative deterministic compiler including convolution_trace | long-tail provider-native JSON plan -> request-derived topic coverage + minimum process substance -> scalar-preserving local punctuation repair -> at most one budgeted model repair -> deterministic layout/state timeline -> semantic usefulness and safety gates -> sanitized SVG + bounded frame grounding for Tutor claims; each stage and attempt is observable, Desktop and Web share the same TS runtime, and one requested visual cannot drift into another visual or repeated video search"),
        ToolContract("learning_diagram_generator", "Learning Diagram Generator", "learning_design_agent", "vnext", "artifact",
                     (), (), "explicit diagram intent -> computer/math abstraction selection -> validated useful VisualSpec -> deterministic static SVG; zero learner-state write"),
        ToolContract("learning_animation_generator", "Learning Animation Generator", "learning_design_agent", "vnext", "artifact",
                     (), (), "explicit animation intent + recoverable topic -> request-specific state-changing computer/math process with at least two transitions for process storyboards -> validated VisualSpec frames -> deterministic inspectable SVG timeline + truthful bounded Tutor grounding; zero learner-state write"),
        ToolContract("selection_followup_context", "Selection Follow-up Context Assembler", "tutor_agent", "vnext", "orchestration",
                     (), (), "main conversation + ancestor sheets -> current branch context; no learner-state write"),
        ToolContract("vnext_learning_task_runtime", "vNext In-chat Learning Task Runtime", "tutor_agent", "vnext", "orchestration",
                     KERNEL_NAMES, (), "browser interaction -> formal AgentSession + LearningSkillRun + linked LearningTask -> deterministic turn transition; browser events are display/offline projections and lifecycle never implies mastery"),
        ToolContract("vnext_learning_plan_runtime", "vNext In-chat Learning Plan Runtime", "tutor_agent", "vnext", "orchestration",
                     KERNEL_NAMES, (), "planning events -> learner-visible proposal -> explicit confirmation EvidenceEvent -> reducer; proposal/rejection remain zero-target"),
        ToolContract("vnext_five_kernel_profile_reader", "vNext Formal Five-kernel Context Reader", "tutor_agent", "vnext", "read",
                     KERNEL_NAMES, (), "ContextPolicy -> KernelHead + scoped Memory Graph -> bounded read-only Tutor context; local simulation is offline fallback only"),
        ToolContract("vnext_learning_workspace_reader", "vNext Scoped Learning Workspace Reader", "tutor_agent", "vnext", "read",
                     KERNEL_NAMES, (), "learner/session/project/checkpoint-scoped LearningTask queue + answer-free LearningAttempt/RemediationCase/ReviewSchedule projection + project source knowledge domains -> bounded read-only observation"),
        ToolContract("domain_knowledge_reader", "Learner Domain Knowledge Library Reader", "tutor_agent", "vnext", "read",
                     (), (), "learner-owned processed Source/Chunk library -> relevance-ranked, provenance-bearing, bounded untrusted context; never learner knowledge evidence"),
        ToolContract("learning_file_service", "Managed Lecture and Practice File Service", "tutor_agent", "vnext", "artifact",
                     (), (), "learner-owned Lecture/Exercise/ConceptQuestion refs -> answer-safe file views, explicit open/attach audit events; generation and opening never imply mastery"),
        ToolContract("active_learning_file_reader", "Active Paper Learning File Reader", "tutor_agent", "vnext", "read",
                     (), (), "current paper artifact ref -> owned Lecture/Practice/Source answer-safe bounded content; Source remains untrusted and access never implies mastery"),
        ToolContract("assessment_blueprint_builder", "Assessment Blueprint and Rubric Builder", "learning_design_agent", "vnext", "proposal",
                     ("knowledge", "structure", "human"), (), "formal LearningTask + checkpoint scope -> validated versioned AssessmentBlueprint + Rubric draft; proposal is zero-target and grading remains deterministic"),
        ToolContract("dynamic_practice_generator", "Blueprint-bound Dynamic Practice Generator", "learning_design_agent", "vnext", "artifact",
                     ("knowledge", "structure", "human"), (), "formal LearningTask + checkpoint scope + target-skill blueprint -> model candidates -> deterministic schema/answer/duplicate gate -> answer-safe ConceptQuestion set; generation is zero-target and psychometrically uncalibrated"),
        ToolContract("similar_practice_generator", "Construct-preserving Similar Practice Generator", "learning_design_agent", "vnext", "artifact",
                     ("knowledge", "structure"), (), "source practice family + invariant radical features -> changed incidental features -> deterministic validation -> formal variant set; no mastery inference"),
        ToolContract("practice_quality_inspector", "Deterministic Practice Item Quality Inspector", "learning_design_agent", "vnext", "read",
                     (), (), "formal practice ref -> schema/construct/answer determinism/duplicate report; item quality is not learner performance evidence"),
        ToolContract("project_workspace_reader", "Scoped Project Workspace Reader", "tutor_agent", "vnext", "read",
                     ("structure", "knowledge", "human", "value", "practice"), (), "owned Project/Roadmap/Checkpoint/Session/LearningTask/Source/File refs + scoped ContextPacket -> bounded project observation"),
        ToolContract("project_source_reader", "Project General Source Reader", "tutor_agent", "vnext", "read",
                     (), (), "current-project processed Source/Chunk only -> bounded untrusted excerpts with provenance; never learner evidence"),
        ToolContract("project_learning_file_reader", "Project Managed Learning File Reader", "tutor_agent", "vnext", "read",
                     (), (), "current-project Lecture/Exercise refs -> answer-safe content; hidden answers remain server-side"),
        ToolContract("project_roadmap_reader", "Project Tutor Roadmap Reader", "tutor_agent", "vnext", "read",
                     ("structure",), (), "project_tutor session only -> current versioned checkpoint DAG including editability; empty graph is a valid observation"),
        ToolContract("project_roadmap_proposer", "Project Tutor Roadmap Proposal Tool", "tutor_agent", "vnext", "proposal",
                     ("structure", "knowledge", "human", "value"), (), "project_tutor session only + exact project theme + scoped sources/context -> typed create/revision proposal; only not-started nodes may change and explicit learner confirmation is required"),
        ToolContract("project_learning_file_proposer", "Learning File Generation Proposal Harness", "learning_design_agent", "vnext", "proposal",
                     ("knowledge", "human"), (), "current formal LearningTask + managed artifact refs -> reuse existing lecture/practice or a confirmation-required generation proposal; project scope is used when available; user-triggered materialization and no mastery inference"),
        ToolContract("role_capability_package_runtime", "Role Capability Package Compiler", "learning_design_agent", "learnflow", "artifact",
                     (), (), "fixed project sources + explicit task seeds -> validated immutable role capability snapshot; zero learner-state write"),
        ToolContract("role_capability_graph_reader", "Role Capability Graph Reader", "learning_design_agent", "learnflow", "read",
                     (), (), "learner-owned project -> current immutable role snapshot -> bounded graph objects; no mastery inference"),
        ToolContract("role_capability_explainer", "Snapshot-pinned Role Capability Explainer", "learning_design_agent", "learnflow", "read",
                     (), (), "pinned snapshot + bounded query -> objects, relations and evidence refs; no role fact mutation and no learner-state write"),
        ToolContract("role_capability_iteration_runtime", "Contracted Role Capability Iteration Runtime", "learning_design_agent", "learnflow", "harness",
                     (), (), "base snapshot -> contract -> inspect -> bounded patch -> validate -> meaningful diff -> immutable successor; zero learner-state write"),
        ToolContract("vnext_learning_path_graph_reader", "vNext Official + Personal Learning Path Graph Reader", "tutor_agent", "vnext", "read",
                     ("structure", "knowledge", "value"), (), "compatibility dispatcher over exact then conditional fuzzy retrieval; not model-visible; self-report is never Knowledge mastery"),
        ToolContract("vnext_learning_path_exact_reader", "vNext Exact Learning Path Node Reader", "tutor_agent", "vnext", "read",
                     ("structure", "knowledge", "value"), (), "normalized id/title/alias equality over versioned official + personal nodes -> bounded candidates with match reasons; miss explicitly requests fuzzy retrieval"),
        ToolContract("vnext_learning_path_fuzzy_reader", "vNext Fuzzy Learning Path Graph Search", "tutor_agent", "vnext", "read",
                     ("structure", "knowledge", "value"), (), "exact-miss query -> versioned intent/topic normalization + deterministic lexical/spelling/topical rank fusion -> resolved, ambiguous, or graph-gap observation; ambiguity cannot become a route"),
        ToolContract("vnext_personal_path_node_proposer", "vNext Evidence-backed Personal Path Node Proposer", "tutor_agent", "vnext", "proposal",
                     ("structure", "knowledge", "value"), (), "confirmed graph gap + runtime-injected structured search evidence + deterministic topic/authority/independence gate + duplicate guard -> learner-visible node proposal; the model cannot supply provenance URLs and the proposal has zero kernel target until explicit learner confirmation"),
        ToolContract("vnext_learning_path_planner", "vNext Personalized Long-term Learning Path Planner", "learning_design_agent", "vnext", "proposal",
                     ("structure", "knowledge", "human", "value"), (), "resolved goal + official/personal DAG + scoped ContextPacket -> hard-prerequisite closure + direct soft prerequisites + deterministic topological order; co-learning never imposes precedence; model may explain but cannot choose mastery or commit"),
        ToolContract("vnext_learning_path_plan_manager", "vNext Confirmed Learning Path Plan Manager", "tutor_agent", "vnext", "orchestration",
                     ("structure", "value"), (), "learner-visible route proposal -> explicit learner confirmation -> registered EvidenceEvent -> reducer; revisions and archive preserve history"),
        ToolContract("personal_concept_graph_reader", "Personal Concept Learning Graph Reader", "tutor_agent", "vnext", "read",
                     ("structure", "knowledge"), (), "shared ConceptAnchor identity + Knowledge history + Structure relations -> bounded read-only context; official course graph remains separate"),
        ToolContract("concept_self_report_gateway", "Learner Concept Self-report Gateway", "tutor_agent", "vnext", "orchestration",
                     ("structure", "knowledge"), (), "explicit raw learner text -> registered statement/observation/relation EvidenceEvents -> deterministic reducer; unverified and no mastery inference"),
        ToolContract("vnext_personal_path_node_runtime", "vNext Personal Learning Path Node Runtime", "tutor_agent", "vnext", "orchestration",
                     ("structure", "knowledge", "value"), (), "search-backed proposal or status edit -> explicit learner confirmation -> EvidenceEvent -> reducer"),
        ToolContract("learner_memory_manager", "Learner-controlled Five-kernel Memory Manager", "tutor_agent", "learnflow", "transaction",
                     KERNEL_NAMES, (), "learner confirmation/correction/retraction/archive -> EvidenceEvent -> reducer or projection filter; immutable history retained"),
        ToolContract("vnext_five_kernel_explicit_editor", "vNext Learner-controlled Five-kernel Explicit Editor", "tutor_agent", "vnext", "transaction",
                     KERNEL_NAMES, (), "learner-authored kernel-specific edit -> profile/concept/claim/plan gateway -> registered EvidenceEvent -> reducer; Practice cannot be self-upgraded"),
        ToolContract("workspace_lifecycle", "Conversation and Project Workspace Lifecycle", "tutor_agent", "learnflow", "transaction",
                     (), (), "confirmed workspace removal + zero-target audit event; learning evidence retained"),
        ToolContract("checkpoint_context", "Checkpoint Tutor Context Assembler", "tutor_agent", "learnflow", "read",
                     KERNEL_NAMES),
        ToolContract("source_ingestion", "Source Ingestion + Chunking", "learning_design_agent", "learnflow", "artifact"),
        ToolContract("repository_knowledge_domains", "Repository Knowledge Domain Context Builder", "learning_design_agent", "learnflow", "read"),
        ToolContract("hierarchical_rag", "Hierarchical RAG", "learning_design_agent", "learnflow", "read",
                     ("knowledge", "structure")),
        ToolContract("content_generation", "Roadmap/Lecture/Assessment Generation", "learning_design_agent", "learnflow", "artifact",
                     KERNEL_NAMES),
        ToolContract("micro_learning_orchestrator", "Focused Micro-learning Orchestrator", "tutor_agent", "learnflow", "orchestration",
                     KERNEL_NAMES, (), "bounded model enhancement -> deterministic fallback + EvidenceEvent + existing learning domain records"),
        ToolContract("learning_skill_runtime", "Conversation Learning Skill Runtime", "tutor_agent", "learnflow", "orchestration",
                     (), (), "LearningSkillRun + zero-target events + verified workbench handoff"),
        ToolContract("learning_task_runtime", "Learner-visible Learning Task Runtime", "tutor_agent", "learnflow", "orchestration",
                     KERNEL_NAMES, (), "LearningTask + plan revisions + managed artifact refs + deterministic runtime projection + zero-target lifecycle events"),
        ToolContract("learning_task_planner", "Adaptive Learning Task Planner", "learning_design_agent", "learnflow", "proposal",
                     ("human",), (), "bounded model enhancement -> validated deterministic LearningTask plan using task source/scoped evidence plus portable human preferences only"),
        ToolContract("teach_back_analyzer", "Deterministic Teach-back Analyzer", "practice_agent", "learnflow", "assessment",
                     ("knowledge", "practice"), (), "LearningAttempt + EvidenceEvent"),
        ToolContract("process_animation", "Process Animation", "learning_design_agent", "learnflow", "artifact",
                     ("knowledge", "human")),
        ToolContract(
            "code_executor",
            "Policy-gated Local Code Executor",
            "practice_agent",
            "learnflow",
            "assessment",
            (),
            (),
            "unsupported by default; explicit development-only trusted_local_process mode discloses that host filesystem, network, and secrets are not isolated",
        ),
        ToolContract("deterministic_assessment", "Deterministic Assessment", "practice_agent", "learnflow", "assessment"),
        ToolContract("deterministic_remediation", "RemediationStrategy", "practice_agent", "fused", "policy",
                     ("knowledge", "human", "practice"), (), "EvidenceEvent"),
        ToolContract("review_scheduler", "Deterministic Spaced Review Scheduler", "practice_agent", "learnflow", "projection",
                     ("knowledge", "practice"), (), "LearningAttempt/Event -> ReviewSchedule"),
        ToolContract("review_proficiency_projector", "Evidence-bound DSR Review Proficiency Projector", "practice_agent", "learnflow", "projection",
                     ("knowledge", "practice"), (), "LearningAttempt/Event/ReviewSchedule -> rebuildable proficiency + D/S/R cold-start projection; never mastery authority"),
        ToolContract("review_context_reader", "Answer-free Review Evidence Reader", "tutor_agent", "vnext", "read",
                     ("knowledge", "practice"), (), "scoped schedules + graded evidence + correctable memories -> bounded answer-free Agent observation"),
        ToolContract("review_reflection_gateway", "Learner Review Reflection Gateway", "tutor_agent", "vnext", "event_gateway",
                     ("knowledge",), (), "explicit learner reflection -> EvidenceEvent -> five_kernel_reducer; unverified and no mastery inference"),
        ToolContract("evidence_ledger", "Evidence Ledger Gateway", "tutor_agent", "learnflow", "event_gateway",
                     (), (), "append-only EvidenceEvent"),
        ToolContract("five_kernel_reducer", "Five-kernel Deterministic Reducer", "tutor_agent", "learnflow", "projection",
                     (), KERNEL_NAMES, "EvidenceEvent -> KernelMutation"),
        ToolContract("memory_graph", "Inspectable Memory Graph", "tutor_agent", "learnflow", "projection",
                     KERNEL_NAMES, (), "KernelMutation -> Fact -> versioned Module -> Claim"),
        ToolContract("kernel_head_projector", "Bounded Kernel Head Projector", "tutor_agent", "learnflow", "projection",
                     KERNEL_NAMES, (), "KernelState/Memory Graph -> rebuildable KernelHead"),
        ToolContract("five_kernel_retriever", "Scoped Five-kernel Retriever", "tutor_agent", "learnflow", "read",
                     KERNEL_NAMES, (), "exact scope -> hybrid recall -> one-hop relations"),
        ToolContract("context_packet_assembler", "Capability ContextPacket Assembler", "tutor_agent", "learnflow", "read",
                     KERNEL_NAMES, (), "ContextPolicy -> bounded answer-free ContextPacket"),
        ToolContract("workflow_gateway", "Mock / Xingchen Workflow Gateway", "learning_design_agent", "companion", "optional_adapter",
                     KERNEL_NAMES, (), "validated artifact or EvidenceEvent only"),
        ToolContract("workflow_validator", "Workflow Builder + Validator", "learning_design_agent", "companion", "maintenance"),
        ToolContract("seeded_demo", "Seeded Competition Demo", "tutor_agent", "fused", "demo"),
        ToolContract("task_runtime", "Idempotent Background Task Runtime", "tutor_agent", "learnflow", "execution"),
        ToolContract("workspace_file_service", "Desktop Workspace File Service", "tutor_agent", "learnflow", "filesystem",
                     (), (), "confirmed WorkspaceOperation only"),
        ToolContract("managed_artifact_service", "Managed Learning Artifact Service", "tutor_agent", "learnflow", "artifact",
                     (), (), "versioned lecture/draft/annotation domain APIs"),
        ToolContract("local_agent_broker", "Local Agent Broker", "tutor_agent", "learnflow", "isolated_execution",
                     (), (), "two-confirmation WorkspaceOperation batch only"),
    )
}


# `ToolContract.mode` is retained for API compatibility. These complete, orthogonal
# classifications define what each registered object *is* at the Agent interface.
# Only `aci_tool` objects are candidates for model tool calling. Harness, projection,
# policy and adapter objects remain service-side infrastructure.
TOOL_INTERFACE_ROLES = {
    **{tool_id: "aci_tool" for tool_id in {
        "action_board", "computer_knowledge_search", "web_evidence_reader", "learning_video_search", "learning_video_inspector", "learning_diagram_generator", "learning_animation_generator",
        "vnext_five_kernel_profile_reader", "vnext_learning_workspace_reader", "vnext_learning_path_exact_reader", "vnext_learning_path_fuzzy_reader", "vnext_personal_path_node_proposer", "domain_knowledge_reader",
        "review_context_reader", "review_reflection_gateway",
        "vnext_learning_path_planner", "vnext_learning_path_plan_manager",
        "personal_concept_graph_reader", "concept_self_report_gateway",
        "vnext_personal_path_node_runtime", "learner_memory_manager",
        "vnext_five_kernel_explicit_editor", "workspace_lifecycle", "source_ingestion",
        "repository_knowledge_domains", "hierarchical_rag", "content_generation",
        "teach_back_analyzer", "process_animation", "code_executor",
        "deterministic_assessment", "evidence_ledger", "five_kernel_retriever",
        "workspace_file_service", "managed_artifact_service", "learning_file_service", "active_learning_file_reader", "local_agent_broker",
        "assessment_blueprint_builder", "dynamic_practice_generator", "similar_practice_generator", "practice_quality_inspector",
        "project_workspace_reader", "project_source_reader", "project_learning_file_reader",
        "project_roadmap_reader", "project_roadmap_proposer", "project_learning_file_proposer",
        "discover_project_plugin_tools", "call_project_plugin_tool",
    }},
    **{tool_id: "harness" for tool_id in {
        "tutor_context", "chat_mode_runtime", "vnext_agent_turn_runtime", "vnext_learning_path_graph_reader",
        "safe_visual_generation", "selection_followup_context", "vnext_learning_task_runtime",
        "vnext_learning_plan_runtime", "micro_learning_orchestrator",
        "learning_skill_runtime", "learning_task_runtime", "learning_task_planner",
        "checkpoint_context", "context_packet_assembler", "task_runtime", "seeded_demo",
        "source_version_runtime", "domain_knowledge_packet_compiler",
        "plugin_package_runtime", "plugin_process_runner", "plugin_action_proposer",
    }},
    **{tool_id: "projection" for tool_id in {
        "review_scheduler", "review_proficiency_projector", "five_kernel_reducer", "memory_graph", "kernel_head_projector", "checkpoint_delivery_readiness",
    }},
    "deterministic_remediation": "policy",
    "teaching_contract_gate": "policy",
    "source_integrity_monitor": "policy",
    "vnext_chat_session_store": "adapter",
    "workflow_gateway": "adapter",
    "workflow_validator": "adapter",
    # These four static objects are compatibility aliases over the generic
    # plugin host.  They are deliberately not part of the model tool surface.
    "role_capability_package_runtime": "adapter",
    "role_capability_graph_reader": "adapter",
    "role_capability_explainer": "adapter",
    "role_capability_iteration_runtime": "adapter",
}

# Exposure is intentionally narrower than the ACI catalog. vNext currently gives
# the model a bounded set of read/artifact capabilities; proposal and write tools stay behind
# deterministic orchestration and explicit learner confirmation.
TOOL_MODEL_EXPOSURE = {
    tool_id: (
        "vnext_native"
        if tool_id in {
            "computer_knowledge_search", "web_evidence_reader", "learning_video_search", "learning_video_inspector", "learning_diagram_generator", "learning_animation_generator",
            "vnext_five_kernel_profile_reader", "vnext_learning_workspace_reader", "vnext_learning_path_exact_reader", "vnext_learning_path_fuzzy_reader", "vnext_personal_path_node_proposer", "domain_knowledge_reader",
            "review_context_reader", "project_workspace_reader", "project_source_reader",
            "project_learning_file_reader", "project_roadmap_reader", "project_roadmap_proposer", "project_learning_file_proposer",
            "discover_project_plugin_tools", "call_project_plugin_tool",
            "assessment_blueprint_builder", "dynamic_practice_generator", "similar_practice_generator", "practice_quality_inspector", "active_learning_file_reader",
        }
        else "agent_mediated"
        if TOOL_INTERFACE_ROLES.get(tool_id) == "aci_tool"
        else "not_model_callable"
    )
    for tool_id in TOOLS
}


_SKILL_RUNTIME_EVENTS = (
    "learning_skill_run_started", "learning_skill_run_advanced",
    "learning_skill_run_paused", "learning_skill_run_resumed",
    "learning_skill_verification_started", "learning_skill_run_completed",
)


def _skill_runtime(
    *states: SkillStateContract,
    turn_budget: int | None = None,
    calibration_axes: tuple[SkillCalibrationAxisContract, ...] = (),
    output_objects: tuple[str, ...] = ("LearningSkillRunTransition", "VerificationHandoff"),
    extra_event_types: tuple[str, ...] = (),
    required_context: tuple[str, ...] = (
        "scoped_learning_task", "learner_reply_signal", "answer_free_context_packet",
    ),
    knowledge_requirements: dict[str, Any] | None = None,
) -> SkillRuntimeContract:
    return SkillRuntimeContract(
        version="atomic-learning-skill-runtime-v6",
        bound_chat_modes=("learn",),
        initial_state=states[0].id,
        states=tuple(states),
        turn_budget=turn_budget or max(1, len(states) - 1),
        verification_required=True,
        required_context=required_context,
        input_objects=("LearningTask", "LearningSkillRun", "ContextPacket", "AgentMessage"),
        output_objects=output_objects,
        allowed_event_types=(*_SKILL_RUNTIME_EVENTS, *extra_event_types),
        evidence_policy=(
            "coaching turns and self-report are zero-target; only existing independently "
            "graded attempts, remediation and review may support capability evidence"
        ),
        failure_policy=(
            "missing, acknowledgement, skip, no-prior-knowledge and direct-explanation "
            "requests stay on the current state with bounded support; never auto-pass"
        ),
        eval_suite="learning-skill-dialogue-v2",
        knowledge_requirements=knowledge_requirements or {
            "required_slots": (
                "definition", "mechanism", "example", "boundary",
                "misconception", "assessment_basis",
            ),
            "minimum_authority_tiers": ("official", "curated", "academic", "learner_owned"),
            "freshness": "task_dependent",
            "minimum_coverage": 1.0,
            "formal_publish_requires_packet": True,
            "missing_behavior": "preserve_skill_progress_and_block_artifact_publication",
        },
        calibration_axes=calibration_axes,
    )


PEDAGOGICAL_SKILL_RUNTIMES = {
    "guided_explanation": _skill_runtime(
        SkillStateContract(
            "presenting_core_model", "建立核心模型", "模型", "guidance", "引导态",
            "建立一个可回答、可检查的最小心智模型。",
            "直接说明目标解决的问题、关键对象、核心关系与一个边界；不能用空泛追问代替知识起点。",
            "看最小例子", loop_instruction="只换表征、类比或反例，不增加新的知识层次。",
        ),
        SkillStateContract(
            "checking_minimal_example", "检查最小例子", "例子", "demonstration", "示范态",
            "把核心关系映射到一个表面不同的最小例子。",
            "给一个可逐项映射到核心模型的例子，只要求学生判断一个关键变化。",
            "用自己的话解释", loop_instruction="保持同一知识关系，缩小例子与待判断范围。",
        ),
        SkillStateContract(
            "repairing_explanation", "修补并重新表达", "修补", "teachback", "复述态",
            "根据回应修补一处理解，再由学生重组核心关系。",
            "只修正一个关键偏差，请学生用条件—机制—结果重新表达；复述不算掌握。",
            "进入独立验证", loop_instruction="把重述目标缩成一句因果关系，再让学生修订同一处。",
        ),
        SkillStateContract(
            "verification_ready", "准备独立验证", "验证", "independent", "验证态",
            "停止继续讲解，将任务交给无提示验证。",
            "明确引导和重述不是掌握证据，提供独立题或正式练习入口。",
            "开始独立验证", accepted_signals=(), can_loop=False, requires_learner_reply=False,
        ),
    ),
    "socratic_dialogue": _skill_runtime(
        SkillStateContract(
            "eliciting_prior_model", "建立可回答起点", "起点", "guidance", "引导态",
            "用最小支架暴露学习者当前直觉，而非要求凭空猜测。",
            "给必要事实与具体情境，每轮只问一个无需猜术语即可回答的问题。",
            "检验一个判断", loop_instruction="补一个事实或二选一情境，继续停留在同一判断附近。",
        ),
        SkillStateContract(
            "testing_assumption", "检验关键假设", "假设", "inquiry", "探究态",
            "用反例、边界或单变量变化检验当前判断。",
            "先回应已有推理，再只问一个能检验关键条件或因果方向的问题。",
            "连接理由与结论", loop_instruction="固定其余条件，把问题缩成一个可观察的变化。",
        ),
        SkillStateContract(
            "building_explanation", "连接理由与边界", "收束", "synthesis", "收束态",
            "让学习者把条件、机制与结论组成可检查解释。",
            "只要求用因为—所以—只有当收束推理，反馈一个关键连接。",
            "进入独立验证", loop_instruction="给三段式句架，只补缺失的一段后再完整表达。",
        ),
        SkillStateContract(
            "verification_ready", "准备独立验证", "验证", "independent", "验证态",
            "停止追问，将形成的推理交给新情境验证。",
            "明确普通对话不是掌握证明，提供不照搬当前表述的独立题入口。",
            "开始独立验证", accepted_signals=(), can_loop=False, requires_learner_reply=False,
        ),
    ),
    "feynman_dialogue": _skill_runtime(
        SkillStateContract(
            "awaiting_teach_back", "第一次自己的话复述", "初讲", "teachback", "复述态",
            "在有知识起点后取得第一版自己的话解释。",
            "若主题陌生先补三点以内的最小解释；随后只邀请一句自己的话复述。",
            "定位一个跳步", loop_instruction="缩小到一个关系并提供句架，不要求从空白完整复述。",
        ),
        SkillStateContract(
            "locating_gap", "定位一个关键跳步", "诊断", "diagnosis", "诊断态",
            "只定位一个含糊词、遗漏前提或因果跳步。",
            "先指出讲清楚的一点，再问一个能暴露最关键连接的问题。",
            "修订复述", loop_instruction="把跳步拆成更小前提；仍不会时直接补足前提。",
        ),
        SkillStateContract(
            "revising_explanation", "带着修正再讲", "修订", "revision", "修订态",
            "修订同一个关键跳步，并加入例子与边界。",
            "请学生不用术语重讲，加入一个例子和一个不适用边界；不做掌握判断。",
            "进入独立验证", loop_instruction="继续围绕同一跳步缩小范围，必要时给半成品改错。",
        ),
        SkillStateContract(
            "verification_ready", "准备独立验证", "验证", "independent", "验证态",
            "把复述诊断交给独立变式验证。",
            "说明复述只是诊断，提供一道不复用当前例子的独立验证。",
            "开始独立验证", accepted_signals=(), can_loop=False, requires_learner_reply=False,
        ),
        turn_budget=5,
        calibration_axes=(
            SkillCalibrationAxisContract(
                "audience_level", "讲给谁听", "控制语言与先备知识假设。",
                (
                    ("beginner", "零基础"), ("high_school", "高中"),
                    ("vocational", "高职"), ("undergraduate", "本科"),
                    ("graduate", "研究生"), ("professional", "从业者"),
                ),
                "undergraduate",
            ),
            SkillCalibrationAxisContract(
                "cognitive_demand", "说到多深", "控制本轮复述需要覆盖的认知动作。",
                (
                    ("define", "定义"), ("mechanism", "机制"),
                    ("boundary", "边界"), ("transfer", "迁移"),
                ),
                "mechanism",
            ),
            SkillCalibrationAxisContract(
                "scaffold_level", "给多少支架", "控制 Tutor 提供的帮助强度。",
                (
                    ("model", "完整示范"), ("guided", "引导"),
                    ("minimal", "少量提示"), ("none", "无提示"),
                ),
                "guided",
            ),
            SkillCalibrationAxisContract(
                "representation_mode", "怎么表达", "选择更适合当前知识的表征。",
                (
                    ("auto", "自动"), ("code", "代码"), ("visual", "可视化"),
                    ("analogy", "类比"), ("formal", "公式/形式化"),
                ),
                "auto",
            ),
        ),
        output_objects=(
            "LearningSkillRunTransition", "TeachBackDiagnostic", "VerificationHandoff",
        ),
        extra_event_types=(
            "learning_skill_calibration_updated", "learning_skill_teach_back_diagnostic_updated",
        ),
    ),
    "worked_example_fading": _skill_runtime(
        SkillStateContract(
            "studying_worked_example", "拆解完整示例", "示范", "demonstration", "示范态",
            "用子目标标注的小示例建立程序性步骤模型。",
            "给一个小而完整、按子目标分段的示例，解释每一步为什么服务于目标。",
            "补全最后一步", loop_instruction="恢复完整过程并缩小输入，不撤掉更多支架。",
        ),
        SkillStateContract(
            "completing_last_step", "补全最后一步", "末步", "practice", "练习态",
            "只撤去最后一个可检查动作，让学生完成并说明用途。",
            "保留前面步骤，只隐藏最后一步；一次只要求一个可检查产物。",
            "撤去更多支架", loop_instruction="给局部输入、输出形状或规则提示，仍由学生完成该步。",
        ),
        SkillStateContract(
            "solving_faded_example", "完成渐隐变式", "渐隐", "transfer", "迁移态",
            "在同结构新情境中只保留目标与起始条件。",
            "提供同结构新情境，只保留子目标标签和起始条件；提示必须显式记录。",
            "进入独立验证", loop_instruction="恢复一个相邻步骤，降低一次需保持的信息量。",
        ),
        SkillStateContract(
            "verification_ready", "准备独立验证", "验证", "independent", "验证态",
            "撤去示例与子目标标签，进入无提示变式验证。",
            "总结已独立完成的动作，明确训练不等于掌握，提供无提示变式入口。",
            "开始独立验证", accepted_signals=(), can_loop=False, requires_learner_reply=False,
        ),
    ),
    "learning_file_study": _skill_runtime(
        SkillStateContract(
            "selecting_learning_artifact", "选择学习文件", "选文件", "guidance", "引导态",
            "用极短直接介绍建立起点，然后把主体学习交给已有或待确认生成的完整讲义与练习。",
            "先用不超过三句话直接回答学习者当下问题，再读取工作区文件引用；优先复用已有文件，缺少时由 Harness 给出一次讲义+练习生成确认卡。聊天不展开完整课程、不列资源菜单；除非学习者明确要求外部资源，不搜索网页或视频。",
            "打开讲义", loop_instruction="缩小目标并只保留一个最相关文件；不为推进流程重复生成。",
        ),
        SkillStateContract(
            "reading_with_anchor", "带锚点阅读讲义", "读讲义", "demonstration", "阅读态",
            "在讲义或资料纸张中完成一个有明确位置和问题的阅读动作。",
            "精确读取当前文件，只指出一处阅读位置、一个核心关系和一个阅读后问题；正文留在纸张里。",
            "进入文件练习", loop_instruction="换一个段落锚点、图解或最小例子，不把整篇讲义搬进对话。",
        ),
        SkillStateContract(
            "practicing_in_file", "在练习纸张中作答", "做练习", "practice", "练习态",
            "把讲义中的关键关系交给答案隔离的正式练习。",
            "打开或生成一份与目标对齐的练习文件；对话只提供最小支架，学生必须在练习纸张中正式提交。",
            "复盘本次证据", loop_instruction="只针对当前卡点给一层提示或同构小题，答案继续隔离。",
        ),
        SkillStateContract(
            "verification_ready", "复盘并准备验证", "复盘", "independent", "验证态",
            "区分阅读、提示练习与独立证据，并将下一步交给正式验证或复习。",
            "引用已存在的作答结果和具体卡点做短复盘；没有 Attempt 时明确暂无证据，不得宣布掌握。",
            "开始独立验证", accepted_signals=(), can_loop=False, requires_learner_reply=False,
        ),
        required_context=(
            "scoped_learning_task", "learner_reply_signal", "answer_free_context_packet",
            "managed_learning_file_refs", "active_paper_artifact",
        ),
        output_objects=(
            "LearningSkillRunTransition", "PaperArtifactHandoff", "VerificationHandoff",
        ),
    ),
}


SKILLS = {
    item.id: item for item in (
        SkillContract("intent_and_handoff", "意图理解与跨空间交接", "tutor_agent",
                      ("tutor_context", "action_board", "evidence_ledger"),
                      "structured intent + auditable action/handoff", "Action Board"),
        SkillContract(
            "guided_explanation", "清晰讲解", "tutor_agent",
            ("tutor_context", "context_packet_assembler", "domain_knowledge_packet_compiler", "learning_skill_runtime",
             "learning_task_runtime", "learning_task_planner", "micro_learning_orchestrator",
             "deterministic_assessment", "deterministic_remediation", "review_scheduler"),
            "task-linked explanation -> example -> self-explanation -> verified workbench handoff",
            "deterministic SkillRun + LearningTask; explanation never counts as mastery",
            learner_selectable=True,
            description="先讲清核心，再用一个例子确认理解。",
            invocation_prompt=(
                "当前对话已由学习者选择“清晰讲解”技能。先直接解释当前问题的核心，"
                "控制在一个清晰层次；需要时给一个最小例子，最后最多留一个可选检查问题。"
                "不要把讲解或用户自述当作掌握证据。"
            ),
            aliases=("清晰讲解", "直接讲解", "讲解模式"),
            best_for=("陌生概念", "认知负荷较高", "需要先建立最小心智模型"),
            avoid_when=("学习者明确要求自己推导", "目标主要是程序性步骤练习"),
            atomic_task_capable=True,
            runtime=PEDAGOGICAL_SKILL_RUNTIMES["guided_explanation"],
        ),
        SkillContract(
            "socratic_dialogue", "苏格拉底追问", "tutor_agent",
            ("tutor_context", "context_packet_assembler", "domain_knowledge_packet_compiler", "learning_skill_runtime",
             "learning_task_runtime", "learning_task_planner", "micro_learning_orchestrator",
             "deterministic_assessment", "deterministic_remediation", "review_scheduler"),
            "task-linked bounded one-question-at-a-time dialogue -> verified workbench handoff",
            "deterministic SkillRun + LearningTask; learner may request a direct answer",
            learner_selectable=True,
            description="用连续的小问题，引导你自己推到答案。",
            invocation_prompt=(
                "当前对话已由学习者选择“苏格拉底追问”技能。不要一开始给出完整答案，也不能要求"
                "完全陌生的学习者从空白猜关键关系；先提供足够回答当前问题的最小知识支架和具体情境。"
                "每轮只问一个能推动思考的问题。若学习者说不会、不知道、跳过或只做确认，不得把它"
                "当成有效尝试或推进步骤，应留在当前步骤补支架；如果明确要求直接解释，应尊重选择并"
                "切换为简明说明。追问结果本身不是掌握证据。"
            ),
            aliases=("苏格拉底", "苏格拉底追问", "启发式提问"),
            best_for=("因果推理", "证明与不变量", "已有部分直觉但需要暴露假设"),
            avoid_when=("完全陌生且没有可调用的先备知识", "学习者明确要求直接解释"),
            atomic_task_capable=True,
            runtime=PEDAGOGICAL_SKILL_RUNTIMES["socratic_dialogue"],
        ),
        SkillContract(
            "feynman_dialogue", "费曼复述", "tutor_agent",
            ("tutor_context", "context_packet_assembler", "domain_knowledge_packet_compiler", "learning_skill_runtime",
             "learning_task_runtime", "learning_task_planner", "micro_learning_orchestrator",
             "teach_back_analyzer", "deterministic_assessment", "deterministic_remediation",
             "review_scheduler"),
            "task-linked bounded teach-back scaffold -> verified workbench handoff",
            "deterministic SkillRun + LearningTask; graded analyzer is required for evidence",
            learner_selectable=True,
            description="请你用自己的话讲一遍，再一起找出模糊处。",
            invocation_prompt=(
                "当前对话已由学习者选择“费曼复述”技能。严格读取 SkillRun 中的 calibration 和"
                "teach_back_diagnostic：按受众、认知要求、支架强度和表征方式组织本轮，不自行改写状态。"
                "若主题陌生，先给三点以内的最小解释和一个具体例子，再邀请复述。收到复述后先指出"
                "讲清楚的一点，只围绕诊断中的一个候选缺口追问或修订；候选缺口未经独立验证，不得"
                "当成事实。达到 verification_ready 后停止追加教学问题并交给独立变式。普通对话反馈"
                "不能宣布掌握；需要形成学习证据时，只能进入已登记的可验证微学习。"
            ),
            aliases=("费曼", "费曼学习", "费曼复述"),
            best_for=("查漏补缺", "组织概念关系", "已有接触后检验能否说清"),
            avoid_when=("尚未接触主题", "程序性任务只需要先看步骤示范"),
            atomic_task_capable=True,
            runtime=PEDAGOGICAL_SKILL_RUNTIMES["feynman_dialogue"],
        ),
        SkillContract(
            "worked_example_fading", "示例渐隐", "tutor_agent",
            ("tutor_context", "context_packet_assembler", "domain_knowledge_packet_compiler", "learning_skill_runtime",
             "learning_task_runtime", "learning_task_planner", "micro_learning_orchestrator",
             "deterministic_assessment", "deterministic_remediation", "review_scheduler"),
            "task-linked subgoal-labeled example -> faded completion -> independent verification",
            "deterministic backward-fading SkillRun + LearningTask; final evidence is independently graded",
            learner_selectable=True,
            description="先拆解一个完整示例，再逐步撤掉步骤让你独立完成。",
            invocation_prompt=(
                "当前对话已由学习者选择“示例渐隐”技能。围绕目标给出一个小而完整、按子目标分段的"
                "示例；随后优先从最后一步开始撤去答案，让学习者补全，再逐步增加独立部分。"
                "每轮只要求一个可检查动作；示例模仿或有提示完成不能作为独立掌握证据。"
            ),
            aliases=("示例渐隐", "渐隐示例", "带我做一遍", "先示范再让我做"),
            best_for=("代码与算法步骤", "配置和工具流程", "新手程序性问题求解"),
            avoid_when=("只需事实解释", "已经能独立完成且只需迁移验证"),
            atomic_task_capable=True,
            runtime=PEDAGOGICAL_SKILL_RUNTIMES["worked_example_fading"],
        ),
        SkillContract(
            "learning_file_study", "讲义与练习共学", "tutor_agent",
            ("tutor_context", "context_packet_assembler", "domain_knowledge_packet_compiler", "learning_skill_runtime",
             "learning_task_runtime", "learning_task_planner", "vnext_learning_workspace_reader",
             "active_learning_file_reader", "project_learning_file_reader",
             "project_learning_file_proposer", "learning_file_service",
             "teaching_contract_gate", "checkpoint_delivery_readiness", "learning_video_search", "learning_video_inspector",
             "assessment_blueprint_builder", "dynamic_practice_generator",
             "deterministic_assessment", "deterministic_remediation", "review_scheduler"),
            "task-linked file selection -> anchored lecture reading -> answer-safe practice paper -> evidence-aware verification handoff",
            "deterministic SkillRun + owned paper artifacts; generation is confirmed, answers stay isolated, only graded attempts support evidence",
            learner_selectable=True,
            description="让讲义负责承载内容、练习负责正式作答，对话负责带路和反馈。",
            invocation_prompt=(
                "当前对话已选择“讲义与练习共学”。初始回复先用不超过三句话直接介绍当前概念，随后立即"
                "查看现有讲义与练习；优先复用已有文件，缺少时由 Harness 形成讲义+练习生成确认卡并等待确认。"
                "学习者未明确要求外部资源时，不搜索网页或视频，不给资源选择菜单。讲义、练习和资料必须在纸张中打开，"
                "可以成为当前纸张的子纸张；聊天只给阅读锚点、最小支架和证据复盘，不复制整份文件。"
                "练习答案必须隔离，正式提交由 Practice Agent 确定性判定；阅读、生成和提示作答都不能宣布掌握。"
            ),
            aliases=("讲义与练习共学", "文件驱动学习", "用讲义带我学", "看讲义做练习"),
            best_for=("已有讲义或练习文件", "需要留下可复用学习材料", "希望阅读和正式作答连成闭环"),
            avoid_when=("只需一句事实解释", "没有明确原子目标", "当前任务无法形成可验证练习"),
            atomic_task_capable=True,
            runtime=PEDAGOGICAL_SKILL_RUNTIMES["learning_file_study"],
        ),
        SkillContract("checkpoint_tutoring", "关卡内统一教学协作", "tutor_agent",
                      ("checkpoint_context", "context_packet_assembler", "hierarchical_rag", "workspace_file_service"),
                      "checkpoint-scoped Tutor reply + internal design/practice handoff",
                      "immutable checkpoint session scope"),
        SkillContract("atomic_learning_loop", "可组合的原子学习任务闭环", "tutor_agent",
                      ("learning_task_runtime", "learning_task_planner", "learning_skill_runtime",
                       "managed_artifact_service", "deterministic_assessment",
                       "deterministic_remediation", "review_scheduler", "evidence_ledger"),
                      "resumable task -> adaptive plan -> persisted lecture/questions -> evidence-driven phases -> review handoff",
                      "task lifecycle is operational; new plans cannot inherit volatile content state from another task; content exposure, grading, mastery and review use distinct deterministic evidence"),
        SkillContract("verified_micro_learning", "可验证微学习闭环", "tutor_agent",
                      ("micro_learning_orchestrator", "content_generation", "teach_back_analyzer",
                       "deterministic_assessment", "deterministic_remediation", "review_scheduler",
                       "evidence_ledger"),
                      "resumable card -> teach-back -> verification -> remediation -> review run",
                      "deterministic workflow and existing assessment contracts"),
        SkillContract("feynman_teach_back", "费曼复述诊断", "practice_agent",
                      ("teach_back_analyzer", "deterministic_assessment", "evidence_ledger"),
                      "diagnostic coverage feedback; never a mastery upgrade",
                      "deterministic diagnostic threshold"),
        SkillContract("learning_path_planning", "来源约束的学习路线规划", "learning_design_agent",
                      ("vnext_learning_path_exact_reader", "vnext_learning_path_fuzzy_reader", "vnext_personal_path_node_proposer", "vnext_learning_path_planner",
                       "vnext_learning_path_plan_manager", "source_ingestion",
                       "repository_knowledge_domains", "hierarchical_rag", "content_generation"),
                      "inspectable long-term route proposal or project roadmap with goal, prerequisites, milestones and provenance",
                      "deterministic route proposal + explicit learner confirmation"),
        SkillContract("learning_resource_curation", "规划态学习资源策展", "learning_design_agent",
                      ("domain_knowledge_reader", "computer_knowledge_search", "web_evidence_reader", "learning_video_search", "learning_video_inspector",
                       "vnext_learning_path_exact_reader", "vnext_learning_path_fuzzy_reader", "source_ingestion"),
                      "goal-aligned resource proposal with coverage, authority tier, provenance and identified gaps",
                      "Skill chooses the comparison workflow; read/search tools only supply evidence"),
        SkillContract("project_apprenticeship_orchestration", "真实产物导向的项目学徒旅程", "tutor_agent",
                      ("project_workspace_reader", "project_source_reader", "project_learning_file_reader",
                       "project_roadmap_reader", "project_roadmap_proposer", "project_learning_file_proposer",
                       "learning_task_runtime", "learning_file_service", "five_kernel_retriever"),
                      "topic-locked project Tutor -> confirmed checkpoint DAG -> checkpoint LearningTasks -> managed files and evidence-safe practice",
                      "Tutor owns orchestration; Learning Design proposes; user confirms structure/artifacts; reducer alone owns five-kernel mutations"),
        SkillContract(
            "project_plugin_orchestration", "项目插件发现、运行与提案协调", "tutor_agent",
            ("discover_project_plugin_tools", "call_project_plugin_tool", "plugin_package_runtime", "plugin_process_runner", "plugin_action_proposer"),
            "enabled project plugin -> pinned read tool or validated workflow candidate -> optional core Action Board proposal",
            "deterministic host owns grants, version, validation, commit and confirmation; plugin Agents only generate candidates",
        ),
        SkillContract("role_capability_graphing", "岗位能力包生成、解释与迭代", "learning_design_agent",
                      ("role_capability_package_runtime", "role_capability_graph_reader", "role_capability_explainer", "role_capability_iteration_runtime", "project_source_reader", "discover_project_plugin_tools", "call_project_plugin_tool", "plugin_process_runner"),
                      "project-scoped immutable role package + evidence-bound explanation + validated semantic successor",
                      "Tutor derives a bounded bootstrap contract from an explicit role and owns conversational activation; Learning Design owns candidates; host owns idempotent validation/commit; snapshots never imply learner mastery"),
        SkillContract("evidence_grounded_teaching", "有来源的讲义与概念教学", "learning_design_agent",
                      ("hierarchical_rag", "content_generation", "process_animation", "teaching_contract_gate", "checkpoint_delivery_readiness", "learning_video_inspector"),
                      "structured teaching artifact; never mastery evidence", "artifact contract"),
        SkillContract("practice_verification", "代码实践与确定性验证", "practice_agent",
                      ("code_executor", "deterministic_assessment", "evidence_ledger"),
                      "graded LearningAttempt + evidence", "test/grading rules"),
        SkillContract(
            "assessment_blueprint_design", "练习蓝图与量表设计", "learning_design_agent",
            ("assessment_blueprint_builder", "practice_quality_inspector"),
            "versioned AssessmentBlueprint + Rubric draft with construct, item mix, success policy and evidence boundary",
            "Learning Design proposes; schema validator owns admissibility; Practice Agent owns deterministic grading",
            "vnext",
            description="把学习任务目标收紧为可测能力、题型组合、成功条件与评分量表；它是 playbook，不是教学方法。",
            best_for=("动态练习生成前", "诊断性检测", "迁移验证"),
            avoid_when=("没有正式学习任务或关卡", "无法确定性判题"),
        ),
        SkillContract(
            "dynamic_practice_loop", "动态练习与检测编排", "tutor_agent",
            ("assessment_blueprint_builder", "dynamic_practice_generator", "similar_practice_generator",
             "practice_quality_inspector", "deterministic_assessment",
             "deterministic_remediation", "review_scheduler", "evidence_ledger"),
            "target-skill blueprint -> validated uncalibrated set -> formal attempt -> remediation/variant/review handoff",
            "Tutor selects the bounded loop; Learning Design proposes items; deterministic validators and Practice Agent own quality and grading; reducer alone owns learner-state mutation",
            "vnext",
            description="围绕当前原子学习任务动态生成练习、诊断或同构变式，并把正式作答送入确定性判题、纠错与复习。",
            best_for=("概念检测", "程序执行追踪", "算法与代码变式", "迁移前练习"),
            avoid_when=("没有正式学习任务或项目关卡", "只需静态讲解", "题目答案无法确定性验证"),
            atomic_task_capable=True,
        ),
        SkillContract("remediation_loop", "答错—纠错—重做—变式—回写", "practice_agent",
                      ("deterministic_remediation", "deterministic_assessment", "evidence_ledger"),
                      "RemediationCase + ordered evidence chain", "RemediationStrategy", "fused"),
        SkillContract("spaced_review", "检索练习与可解释间隔复习", "practice_agent",
                      ("review_scheduler", "review_proficiency_projector", "review_context_reader",
                       "review_reflection_gateway", "deterministic_assessment", "deterministic_remediation", "evidence_ledger"),
                      "LearningTask review handoff + ReviewSchedule + graded retrieval evidence + inspectable D/S/R projection + concrete memory notes",
                      "review-policy-v1 + concept-proficiency-v1; deterministic evidence caps"),
        SkillContract("learner_memory_synthesis", "五核画像与可检查记忆", "tutor_agent",
                      ("five_kernel_reducer", "memory_graph", "kernel_head_projector",
                       "five_kernel_retriever", "context_packet_assembler"),
                      "versioned modules + bounded kernel heads + scoped ContextPacket + evidence-backed claims",
                      "deterministic reducer and ContextPolicy", "fused"),
        SkillContract("external_workflow_rendering", "星辰/Mock 教学内容适配", "learning_design_agent",
                      ("workflow_gateway", "workflow_validator"),
                      "validated content artifact; no direct kernel mutation", "LearnFlow contract", "companion"),
        SkillContract("workspace_file_management", "受控本地项目文件管理", "tutor_agent",
                      ("workspace_file_service", "evidence_ledger"),
                      "hash-bound diff proposal + explicit confirmation + operational event",
                      "WorkspaceOperation state machine"),
        SkillContract("managed_learning_file_playback", "讲义与练习专用播放器", "tutor_agent",
                      ("managed_artifact_service", "deterministic_assessment", "evidence_ledger"),
                      "versioned lecture, personal draft, annotation and formal assessment",
                      "database learning-object authority"),
        SkillContract("local_agent_delegation", "本地代码 Agent 双确认委派", "tutor_agent",
                      ("local_agent_broker", "workspace_file_service", "evidence_ledger"),
                      "isolated run events + tests + risk + hash-bound diff",
                      "deterministic profile selector and two confirmations"),
    )
}


SKILL_KINDS = {
    skill_id: (
        "pedagogical_method"
        if skill_id in {
            "guided_explanation", "socratic_dialogue", "feynman_dialogue",
            "worked_example_fading", "learning_file_study", "feynman_teach_back",
        }
        else "coordination_skill"
        if skill_id in {"intent_and_handoff", "checkpoint_tutoring", "project_plugin_orchestration"}
        else "playbook"
    )
    for skill_id in SKILLS
}


WORKBENCHES = {
    item.id: item for item in (
        WorkbenchContract("global_tutor", "Chat Tutor + Lightweight Workbench", "/agent/:sessionId", "tutor_agent",
                          ("coordinate_chat_mode", "use_learning_skill", "start_learning_skill_run", "advance_learning_skill_run",
                           "start_skill_verification", "start_micro_learning", "search_projects",
                           "draft_learning_project", "create_project", "manage_learning_tasks",
                           "plan_learning_task", "run_learning_task", "delete_conversation")),
        WorkbenchContract("vnext_chat", "LearnFlow Chat + Selection Follow-up Desk", "/chat/:conversationId", "tutor_agent",
                          ("coordinate_vnext_agent_turn", "search_computer_knowledge", "read_web_evidence", "search_learning_videos", "inspect_learning_video", "generate_learning_diagram", "generate_learning_animation", "open_selection_followup",
                           "run_vnext_learning_task", "run_vnext_learning_plan", "read_vnext_five_kernel_profile",
                           "read_vnext_learning_workspace",
                           "manage_domain_knowledge_sources", "read_domain_knowledge", "read_active_learning_file", "recommend_learning_resources",
                           "validate_teaching_contract", "read_checkpoint_delivery_readiness",
                           "attach_learning_file_to_chat", "design_assessment_blueprint", "generate_dynamic_practice", "generate_similar_practice", "inspect_practice_quality",
                           "read_review_context",
                           "lookup_vnext_learning_path_node", "search_vnext_learning_path_graph", "propose_vnext_personal_path_node",
                           "read_vnext_learning_path_graph", "plan_vnext_learning_path", "manage_vnext_learning_path_plan",
                           "read_personal_concept_graph",
                           "record_concept_self_report", "manage_vnext_personal_path_node"), "vnext"),
        WorkbenchContract("vnext_learning_path", "LearnFlow Learning Path Graph", "/learning-path", "tutor_agent",
                          ("lookup_vnext_learning_path_node", "search_vnext_learning_path_graph", "propose_vnext_personal_path_node",
                           "read_vnext_learning_path_graph", "plan_vnext_learning_path",
                           "manage_vnext_learning_path_plan", "manage_vnext_personal_path_node"), "vnext"),
        WorkbenchContract("vnext_profile", "LearnFlow Learner Profile", "/learner-profile", "tutor_agent",
                          ("read_vnext_five_kernel_profile", "read_vnext_learning_path_graph",
                           "read_personal_concept_graph", "record_concept_self_report",
                           "manage_learner_memory", "edit_vnext_five_kernel_profile"), "vnext"),
        WorkbenchContract("vnext_learning_files", "LearnFlow Learning File Library", "/learning-files", "tutor_agent",
                          ("generate_learning_files", "design_assessment_blueprint", "generate_dynamic_practice", "generate_similar_practice", "inspect_practice_quality", "open_learning_file", "attach_learning_file_to_chat"), "vnext"),
        WorkbenchContract("vnext_projects", "LearnFlow Project Library", "/projects", "tutor_agent",
                          ("create_project", "enter_project", "delete_project"), "vnext"),
        WorkbenchContract("vnext_lecture_file", "vNext Lecture File Workbench", "/files/lecture/:lectureId", "tutor_agent",
                          ("open_learning_file", "attach_learning_file_to_chat", "explain_selection"), "vnext"),
        WorkbenchContract("vnext_practice_file", "vNext Practice File Workbench", "/files/practice/:practiceRef", "tutor_agent",
                          ("open_learning_file", "attach_learning_file_to_chat", "inspect_practice_quality", "generate_similar_practice", "evaluate_attempt"), "vnext"),
        WorkbenchContract("learning_tasks", "Learning Task Queue", "/tasks", "tutor_agent",
                          ("manage_learning_tasks",)),
        WorkbenchContract("focused_learning", "Learning Artifact Workbench", "/learn/:runId", "tutor_agent",
                          ("continue_micro_learning", "analyze_teach_back", "evaluate_attempt",
                           "request_remediation_explanation", "retry_attempt",
                           "evaluate_transfer_variant", "plan_review_queue")),
        WorkbenchContract("project_tutor", "Project Tutor", "/projects/:projectId", "tutor_agent",
                          ("add_source", "read_project_roadmap", "revise_project_roadmap", "plan_learning_path", "apply_learning_path", "navigate_checkpoint",
                           "manage_project_conversations", "manage_learning_tasks", "plan_learning_task",
                           "run_learning_task", "generate_learning_files", "open_learning_file",
                           "attach_learning_file_to_chat", "delete_project"), "vnext"),
        WorkbenchContract(
            "plugin_surface_host", "Project Plugin Management Host", "/projects/:projectId", "tutor_agent",
            ("manage_project_plugin_instance", "run_project_plugin_workflow",
             "discover_project_plugin_tools", "call_project_plugin_tool", "propose_plugin_core_action"),
        ),
        WorkbenchContract("role_capability_plugin", "Role Capability Graph Chat Plugin", "/chat/:conversationId", "learning_design_agent",
                          ("generate_role_capability_package", "read_role_capability_graph", "explain_role_capability", "iterate_role_capability_package")),
        WorkbenchContract(
            "learning_task_plugin", "Learning Task Conversion Plugin Workspace",
            "/projects/:projectId/plugins/learning-task", "learning_design_agent",
            ("run_project_plugin_workflow", "discover_project_plugin_tools", "call_project_plugin_tool"),
        ),
        WorkbenchContract("lecture", "Checkpoint Tutor · Lecture", "/projects/:projectId/checkpoints/:checkpointId", "tutor_agent",
                          ("generate_lecture", "explain_selection", "generate_assessment")),
        WorkbenchContract("assessment", "Checkpoint Tutor · Assessment", "/projects/:projectId/checkpoints/:checkpointId/exercises", "tutor_agent",
                          ("evaluate_attempt", "retry_attempt", "evaluate_transfer_variant")),
        WorkbenchContract("remediation", "Remediation Panel", "RemediationPanel", "practice_agent",
                          ("request_remediation_explanation", "retry_attempt", "evaluate_transfer_variant"), "fused"),
        WorkbenchContract("review", "Global Review Workbench", "/review", "tutor_agent",
                          ("plan_review_queue", "read_review_context", "evaluate_review_attempt",
                           "evaluate_transfer_variant", "manage_review_item",
                           "record_review_reflection"), "vnext"),
        WorkbenchContract("learner_growth", "Learner Growth", "/growth", "tutor_agent", ()),
        WorkbenchContract("profile", "Learner Profile Legacy Redirect", "/profile", "tutor_agent", ()),
        WorkbenchContract("memory", "Inspectable Memory Legacy Redirect", "/memory", "tutor_agent", ()),
        WorkbenchContract("competition_demo", "Seeded Demo Entry", "/review", "tutor_agent",
                          ("plan_review_queue", "evaluate_review_attempt", "manage_review_item",
                           "evaluate_attempt", "request_remediation_explanation", "retry_attempt",
                           "evaluate_transfer_variant"), "fused"),
        WorkbenchContract("desktop_workspace", "Desktop File Workspace", "tauri://workspace", "tutor_agent",
                          ("link_project_workspace", "inspect_workspace_files", "propose_workspace_change", "apply_workspace_change", "open_managed_learning_artifact", "edit_managed_lecture", "annotate_learning_artifact", "delegate_local_agent_task", "inspect_local_agent_run", "cancel_local_agent_run", "apply_local_agent_result")),
        WorkbenchContract("xingchen_studio", "Xingchen Workflow Studio", "external", "learning_design_agent",
                          ("generate_lecture", "request_remediation_explanation"), "companion"),
    )
}


CAPABILITY_OWNERS = {
    "coordinate_chat_mode": ("tutor_agent", "chat_mode_runtime", "global_tutor"),
    "coordinate_vnext_agent_turn": ("tutor_agent", "vnext_agent_turn_runtime", "vnext_chat"),
    "search_computer_knowledge": ("learning_design_agent", "computer_knowledge_search", "vnext_chat"),
    "read_web_evidence": ("learning_design_agent", "web_evidence_reader", "vnext_chat"),
    "search_learning_videos": ("learning_design_agent", "learning_video_search", "vnext_chat"),
    "inspect_learning_video": ("learning_design_agent", "learning_video_inspector", "vnext_chat"),
    "generate_learning_diagram": ("learning_design_agent", "learning_diagram_generator", "vnext_chat"),
    "generate_learning_animation": ("learning_design_agent", "learning_animation_generator", "vnext_chat"),
    "open_selection_followup": ("tutor_agent", "selection_followup_context", "vnext_chat"),
    "run_vnext_learning_task": ("tutor_agent", "vnext_learning_task_runtime", "vnext_chat"),
    "run_vnext_learning_plan": ("tutor_agent", "vnext_learning_plan_runtime", "vnext_chat"),
    "read_vnext_five_kernel_profile": ("tutor_agent", "vnext_five_kernel_profile_reader", "vnext_chat"),
    "read_vnext_learning_workspace": ("tutor_agent", "vnext_learning_workspace_reader", "vnext_chat"),
    "manage_domain_knowledge_sources": ("tutor_agent", "source_ingestion", "vnext_chat"),
    "read_domain_knowledge": ("tutor_agent", "domain_knowledge_reader", "vnext_chat"),
    "read_active_learning_file": ("tutor_agent", "active_learning_file_reader", "vnext_chat"),
    "validate_teaching_contract": ("learning_design_agent", "teaching_contract_gate", "vnext_chat"),
    "read_checkpoint_delivery_readiness": ("learning_design_agent", "checkpoint_delivery_readiness", "vnext_chat"),
    "recommend_learning_resources": ("learning_design_agent", "domain_knowledge_reader", "vnext_chat"),
    "generate_learning_files": ("learning_design_agent", "learning_file_service", "vnext_learning_files"),
    "design_assessment_blueprint": ("learning_design_agent", "assessment_blueprint_builder", "vnext_chat"),
    "generate_dynamic_practice": ("learning_design_agent", "dynamic_practice_generator", "vnext_chat"),
    "generate_similar_practice": ("learning_design_agent", "similar_practice_generator", "vnext_chat"),
    "inspect_practice_quality": ("learning_design_agent", "practice_quality_inspector", "vnext_practice_file"),
    "open_learning_file": ("tutor_agent", "learning_file_service", "vnext_learning_files"),
    "attach_learning_file_to_chat": ("tutor_agent", "learning_file_service", "vnext_chat"),
    "read_review_context": ("tutor_agent", "review_context_reader", "vnext_chat"),
    "record_review_reflection": ("tutor_agent", "review_reflection_gateway", "review"),
    "read_vnext_learning_path_graph": ("tutor_agent", "vnext_learning_path_graph_reader", "vnext_chat"),
    "lookup_vnext_learning_path_node": ("tutor_agent", "vnext_learning_path_exact_reader", "vnext_chat"),
    "search_vnext_learning_path_graph": ("tutor_agent", "vnext_learning_path_fuzzy_reader", "vnext_chat"),
    "propose_vnext_personal_path_node": ("tutor_agent", "vnext_personal_path_node_proposer", "vnext_chat"),
    "plan_vnext_learning_path": ("learning_design_agent", "vnext_learning_path_planner", "vnext_chat"),
    "manage_vnext_learning_path_plan": ("tutor_agent", "vnext_learning_path_plan_manager", "vnext_learning_path"),
    "read_personal_concept_graph": ("tutor_agent", "personal_concept_graph_reader", "vnext_chat"),
    "record_concept_self_report": ("tutor_agent", "concept_self_report_gateway", "vnext_profile"),
    "manage_vnext_personal_path_node": ("tutor_agent", "vnext_personal_path_node_runtime", "vnext_learning_path"),
    "manage_learner_memory": ("tutor_agent", "learner_memory_manager", "vnext_profile"),
    "edit_vnext_five_kernel_profile": ("tutor_agent", "vnext_five_kernel_explicit_editor", "vnext_profile"),
    "delete_conversation": ("tutor_agent", "workspace_lifecycle", "global_tutor"),
    "manage_learning_tasks": ("tutor_agent", "learning_task_runtime", "learning_tasks"),
    "plan_learning_task": ("learning_design_agent", "learning_task_planner", "learning_tasks"),
    "run_learning_task": ("tutor_agent", "learning_task_runtime", "learning_tasks"),
    "use_learning_skill": ("tutor_agent", "tutor_context", "global_tutor"),
    "start_learning_skill_run": ("tutor_agent", "learning_skill_runtime", "global_tutor"),
    "advance_learning_skill_run": ("tutor_agent", "learning_skill_runtime", "global_tutor"),
    "start_skill_verification": ("tutor_agent", "learning_skill_runtime", "global_tutor"),
    "start_micro_learning": ("tutor_agent", "micro_learning_orchestrator", "global_tutor"),
    "continue_micro_learning": ("tutor_agent", "micro_learning_orchestrator", "focused_learning"),
    "analyze_teach_back": ("practice_agent", "teach_back_analyzer", "focused_learning"),
    "search_projects": ("tutor_agent", "action_board", "global_tutor"),
    "draft_learning_project": ("tutor_agent", "action_board", "global_tutor"),
    "revise_learning_project_proposal": ("tutor_agent", "action_board", "global_tutor"),
    "search_learning_resources": ("tutor_agent", "action_board", "project_tutor"),
    "create_project": ("tutor_agent", "action_board", "global_tutor"),
    "delete_project": ("tutor_agent", "workspace_lifecycle", "project_tutor"),
    "bootstrap_project": ("tutor_agent", "action_board", "global_tutor"),
    "enter_project": ("tutor_agent", "action_board", "project_tutor"),
    "add_source": ("tutor_agent", "source_ingestion", "project_tutor"),
    "read_project_roadmap": ("tutor_agent", "project_roadmap_reader", "project_tutor"),
    "revise_project_roadmap": ("tutor_agent", "project_roadmap_proposer", "project_tutor"),
    "discover_project_plugin_tools": ("tutor_agent", "discover_project_plugin_tools", "plugin_surface_host"),
    "call_project_plugin_tool": ("tutor_agent", "call_project_plugin_tool", "plugin_surface_host"),
    "manage_project_plugin_instance": ("tutor_agent", "plugin_package_runtime", "plugin_surface_host"),
    "run_project_plugin_workflow": ("tutor_agent", "plugin_process_runner", "plugin_surface_host"),
    "propose_plugin_core_action": ("tutor_agent", "plugin_action_proposer", "plugin_surface_host"),
    "generate_role_capability_package": ("learning_design_agent", "role_capability_package_runtime", "role_capability_plugin"),
    "read_role_capability_graph": ("learning_design_agent", "role_capability_graph_reader", "role_capability_plugin"),
    "explain_role_capability": ("learning_design_agent", "role_capability_explainer", "role_capability_plugin"),
    "iterate_role_capability_package": ("learning_design_agent", "role_capability_iteration_runtime", "role_capability_plugin"),
    "plan_learning_path": ("learning_design_agent", "content_generation", "project_tutor"),
    "apply_learning_path": ("tutor_agent", "action_board", "project_tutor"),
    "navigate_checkpoint": ("tutor_agent", "action_board", "project_tutor"),
    "manage_project_conversations": ("tutor_agent", "project_workspace_reader", "project_tutor"),
    "generate_lecture": ("learning_design_agent", "content_generation", "lecture"),
    "generate_assessment": ("learning_design_agent", "content_generation", "assessment"),
    "evaluate_attempt": ("practice_agent", "deterministic_assessment", "assessment"),
    "explain_selection": ("learning_design_agent", "content_generation", "lecture"),
    "advance_checkpoint": ("tutor_agent", "action_board", "assessment"),
    "request_remediation_explanation": ("practice_agent", "deterministic_remediation", "remediation"),
    "retry_attempt": ("practice_agent", "deterministic_assessment", "remediation"),
    "evaluate_transfer_variant": ("practice_agent", "deterministic_assessment", "remediation"),
    "plan_review_queue": ("tutor_agent", "review_scheduler", "review"),
    "evaluate_review_attempt": ("practice_agent", "deterministic_assessment", "review"),
    "manage_review_item": ("practice_agent", "review_scheduler", "review"),
    "record_task_outcome": ("tutor_agent", "task_runtime", "project_tutor"),
    "link_project_workspace": ("tutor_agent", "workspace_file_service", "desktop_workspace"),
    "inspect_workspace_files": ("tutor_agent", "workspace_file_service", "desktop_workspace"),
    "propose_workspace_change": ("tutor_agent", "workspace_file_service", "desktop_workspace"),
    "apply_workspace_change": ("tutor_agent", "workspace_file_service", "desktop_workspace"),
    "open_managed_learning_artifact": ("tutor_agent", "managed_artifact_service", "desktop_workspace"),
    "edit_managed_lecture": ("learning_design_agent", "managed_artifact_service", "desktop_workspace"),
    "annotate_learning_artifact": ("tutor_agent", "managed_artifact_service", "desktop_workspace"),
    "delegate_local_agent_task": ("tutor_agent", "local_agent_broker", "desktop_workspace"),
    "inspect_local_agent_run": ("tutor_agent", "local_agent_broker", "desktop_workspace"),
    "cancel_local_agent_run": ("tutor_agent", "local_agent_broker", "desktop_workspace"),
    "apply_local_agent_result": ("tutor_agent", "local_agent_broker", "desktop_workspace"),
}


def _event(event_id: str, capability: str, targets: tuple[str, ...], role: str,
           *, tool: str | None = None, workbench: str | None = None,
           origin: str = "learnflow") -> EventContract:
    owner, default_tool, default_workbench = CAPABILITY_OWNERS[capability]
    return EventContract(event_id, owner, capability, tool or default_tool,
                         workbench or default_workbench, targets, role, origin,
                         EVENT_SCHEMA_VERSION if targets else None,
                         f"reducer:{event_id}" if targets else None)


EVENTS = {
    item.id: item for item in (
        _event("chat_mode_entered", "coordinate_chat_mode", (), "operational_context"),
        _event("learning_action_segment_completed", "coordinate_chat_mode", ("structure", "knowledge", "value"), "learning_action_projection"),
        _event(
            "vnext_human_adaptation_requested",
            "coordinate_vnext_agent_turn",
            ("human",),
            "explicit_transient_adaptation",
            origin="vnext",
        ),
        _event("vnext_learning_task_created", "run_vnext_learning_task", (), "local_operational", origin="vnext"),
        _event("vnext_learning_task_started", "run_vnext_learning_task", (), "local_operational", origin="vnext"),
        _event("vnext_learning_task_phase_entered", "run_vnext_learning_task", (), "local_operational", origin="vnext"),
        _event("vnext_learning_skill_step_entered", "run_vnext_learning_task", (), "local_operational", origin="vnext"),
        _event("vnext_learning_skill_looped", "run_vnext_learning_task", (), "local_support_signal", origin="vnext"),
        _event("vnext_learning_task_learner_replied", "run_vnext_learning_task", (), "local_interaction", origin="vnext"),
        _event("vnext_learning_support_requested", "run_vnext_learning_task", (), "local_support_signal", origin="vnext"),
        _event("vnext_learning_skill_selected", "run_vnext_learning_task", (), "local_operational", origin="vnext"),
        _event("vnext_learning_task_paused", "run_vnext_learning_task", (), "local_operational", origin="vnext"),
        _event("vnext_learning_task_resumed", "run_vnext_learning_task", (), "local_operational", origin="vnext"),
        _event("vnext_learning_task_completed", "run_vnext_learning_task", (), "local_operational_milestone", origin="vnext"),
        _event("vnext_learning_plan_started", "run_vnext_learning_plan", (), "local_operational", origin="vnext"),
        _event("vnext_learning_plan_note_captured", "run_vnext_learning_plan", (), "local_interaction", origin="vnext"),
        _event("vnext_project_seed_ready", "run_vnext_learning_plan", (), "local_operational_milestone", origin="vnext"),
        _event("vnext_direction_plan_ready", "run_vnext_learning_plan", (), "local_operational_milestone", origin="vnext"),
        _event("vnext_value_claim_proposed", "run_vnext_learning_plan", (), "local_proposal", origin="vnext"),
        _event("vnext_value_claim_proposal_accepted", "run_vnext_learning_plan", ("value",), "learner_confirmed_goal", origin="vnext"),
        _event("vnext_value_claim_proposal_rejected", "run_vnext_learning_plan", (), "local_rejection", origin="vnext"),
        _event("vnext_value_claim_proposal_revision_requested", "run_vnext_learning_plan", (), "local_revision_request", origin="vnext"),
        _event("vnext_learning_plan_closed", "run_vnext_learning_plan", (), "local_operational_milestone", origin="vnext"),
        _event("vnext_learning_path_node_status_set", "manage_vnext_personal_path_node", ("structure", "knowledge"), "learner_self_report_for_navigation", origin="vnext"),
        _event("vnext_personal_path_node_added", "manage_vnext_personal_path_node", ("structure", "value"), "learner_confirmed_structure_overlay", origin="vnext"),
        _event("vnext_personal_path_node_removed", "manage_vnext_personal_path_node", ("structure", "value"), "learner_confirmed_structure_overlay_removal", origin="vnext"),
        _event("vnext_learning_path_plan_committed", "manage_vnext_learning_path_plan", ("structure", "value"), "learner_confirmed_long_term_route", origin="vnext"),
        _event("vnext_learning_path_plan_revised", "manage_vnext_learning_path_plan", ("structure", "value"), "learner_confirmed_route_revision", origin="vnext"),
        _event("vnext_learning_path_plan_archived", "manage_vnext_learning_path_plan", ("structure", "value"), "learner_confirmed_route_archive", origin="vnext"),
        _event("learner_concept_statement_recorded", "record_concept_self_report", (), "raw_learner_self_report", origin="vnext"),
        _event("learner_concept_observation_recorded", "record_concept_self_report", ("knowledge",), "unverified_concept_history", origin="vnext"),
        _event("learner_concept_relation_recorded", "record_concept_self_report", ("structure",), "unverified_concept_relation", origin="vnext"),
        _event("memory_correction_confirmed", "manage_learner_memory", KERNEL_NAMES, "learner_confirmation", tool="learner_memory_manager", workbench="vnext_profile"),
        _event("memory_correction_added", "manage_learner_memory", KERNEL_NAMES, "learner_correction", tool="learner_memory_manager", workbench="vnext_profile"),
        _event("memory_correction_retracted", "manage_learner_memory", KERNEL_NAMES, "learner_retraction", tool="learner_memory_manager", workbench="vnext_profile"),
        _event("memory_archived", "manage_learner_memory", (), "projection_archive", tool="learner_memory_manager", workbench="vnext_profile"),
        _event("memory_restored", "manage_learner_memory", (), "projection_restore", tool="learner_memory_manager", workbench="vnext_profile"),
        _event("conversation_deleted", "delete_conversation", (), "confirmed_workspace_removal"),
        _event("learning_task_created", "manage_learning_tasks", (), "operational"),
        _event("learning_task_accepted", "manage_learning_tasks", (), "confirmed_operational"),
        _event("learning_task_replanned", "plan_learning_task", (), "plan_revision"),
        _event("learning_task_started", "run_learning_task", (), "operational"),
        _event("learning_task_paused", "run_learning_task", (), "operational"),
        _event("learning_task_resumed", "run_learning_task", (), "operational"),
        _event("learning_task_phase_completed", "run_learning_task", (), "operational_milestone"),
        _event("learning_task_materialized", "run_learning_task", (), "artifact_handoff"),
        _event("learning_task_knowledge_blocked", "run_learning_task", (), "knowledge_gate_block", origin="vnext"),
        _event("knowledge_source_added", "manage_domain_knowledge_sources", (), "artifact_ingest", origin="vnext"),
        _event("knowledge_source_processed", "manage_domain_knowledge_sources", (), "artifact_indexed", origin="vnext"),
        _event("web_evidence_captured", "manage_domain_knowledge_sources", (), "temporary_versioned_evidence", origin="vnext"),
        _event("project_knowledge_baseline_proposed", "manage_domain_knowledge_sources", (), "source_baseline_proposal", origin="vnext"),
        _event("project_knowledge_baseline_confirmed", "manage_domain_knowledge_sources", (), "confirmed_source_baseline", origin="vnext"),
        _event("knowledge_source_health_changed", "manage_domain_knowledge_sources", (), "source_integrity_state", origin="vnext"),
        _event("learning_file_generated", "generate_learning_files", (), "artifact", origin="vnext"),
        _event("assessment_blueprint_proposed", "design_assessment_blueprint", (), "validated_assessment_proposal", tool="assessment_blueprint_builder", workbench="vnext_chat", origin="vnext"),
        _event("practice_file_generated", "generate_dynamic_practice", (), "validated_uncalibrated_artifact", tool="dynamic_practice_generator", workbench="vnext_chat", origin="vnext"),
        _event("practice_variant_generated", "generate_similar_practice", (), "validated_uncalibrated_artifact", tool="similar_practice_generator", workbench="vnext_chat", origin="vnext"),
        _event("practice_quality_inspected", "inspect_practice_quality", (), "artifact_quality_observation", tool="practice_quality_inspector", workbench="vnext_practice_file", origin="vnext"),
        _event("learning_file_opened", "open_learning_file", (), "artifact_access", origin="vnext"),
        _event("learning_file_attached_to_chat", "attach_learning_file_to_chat", (), "context_attachment", origin="vnext"),
        _event("learning_task_completed", "run_learning_task", (), "operational_milestone"),
        _event("learning_task_canceled", "manage_learning_tasks", (), "operational"),
        _event("learning_skill_selected", "use_learning_skill", (), "operational"),
        _event("learning_skill_run_started", "start_learning_skill_run", (), "operational"),
        _event("learning_skill_run_advanced", "advance_learning_skill_run", (), "operational"),
        _event("learning_skill_run_paused", "advance_learning_skill_run", (), "operational"),
        _event("learning_skill_run_resumed", "advance_learning_skill_run", (), "operational"),
        _event("learning_skill_calibration_updated", "advance_learning_skill_run", (), "operational_calibration"),
        _event("learning_skill_teach_back_diagnostic_updated", "advance_learning_skill_run", (), "unverified_diagnostic"),
        _event("learning_skill_verification_started", "start_skill_verification", (), "operational_handoff"),
        _event("learning_skill_run_completed", "advance_learning_skill_run", (), "operational_milestone"),
        _event("micro_learning_started", "start_micro_learning", ("structure", "value"), "confirmed_goal"),
        _event("learning_card_generated", "start_micro_learning", (), "artifact"),
        _event("micro_learning_card_viewed", "continue_micro_learning", ("knowledge",), "exposure"),
        _event("teach_back_analyzed", "analyze_teach_back", ("knowledge", "practice"), "diagnosis"),
        _event("micro_learning_paused", "continue_micro_learning", (), "operational"),
        _event("micro_learning_resumed", "continue_micro_learning", (), "operational"),
        _event("micro_learning_completed", "continue_micro_learning", (), "operational_milestone"),
        _event("registration_profile_completed", "draft_learning_project", ("knowledge", "human", "value"), "self_report"),
        _event("profile_updated", "edit_vnext_five_kernel_profile", ("knowledge", "human", "value"), "self_report", tool="vnext_five_kernel_explicit_editor", workbench="vnext_profile"),
        _event("career_goal_confirmed", "edit_vnext_five_kernel_profile", ("value",), "confirmed_goal", tool="vnext_five_kernel_explicit_editor", workbench="vnext_profile"),
        _event("user_message", "draft_learning_project", KERNEL_NAMES, "interaction"),
        _event("project_proposal_created", "draft_learning_project", ("structure", "value", "practice"), "proposal"),
        _event("project_proposal_revised", "revise_learning_project_proposal", KERNEL_NAMES, "proposal"),
        _event("project_proposal_user_edited", "revise_learning_project_proposal", KERNEL_NAMES, "explicit_edit"),
        _event("project_proposal_accepted", "create_project", ("structure", "value"), "confirmed_action"),
        _event("project_created", "create_project", ("structure", "value"), "action_result"),
        _event("project_deleted", "delete_project", (), "confirmed_workspace_removal"),
        _event("project_selected", "enter_project", ("structure",), "navigation"),
        _event("source_added", "add_source", ("structure", "practice"), "artifact"),
        _event("source_processed", "add_source", ("structure", "practice"), "artifact"),
        _event("project_source_removed", "add_source", (), "confirmed_source_removal", origin="vnext"),
        _event("plugin_instance_enabled", "manage_project_plugin_instance", (), "plugin_lifecycle", origin="plugin_host"),
        _event("plugin_instance_disabled", "manage_project_plugin_instance", (), "plugin_lifecycle", origin="plugin_host"),
        _event("plugin_release_upgraded", "manage_project_plugin_instance", (), "plugin_lifecycle", origin="plugin_host"),
        _event("plugin_workflow_completed", "run_project_plugin_workflow", (), "plugin_run_audit", origin="plugin_host"),
        _event("plugin_snapshot_committed", "run_project_plugin_workflow", (), "versioned_domain_artifact", origin="plugin_host"),
        _event("plugin_action_proposed", "propose_plugin_core_action", (), "confirmation_required_proposal", origin="plugin_host"),
        _event("role_capability_package_generated", "generate_role_capability_package", (), "versioned_domain_artifact", origin="role_capability_plugin"),
        _event("role_capability_snapshot_iterated", "iterate_role_capability_package", (), "versioned_domain_artifact", origin="role_capability_plugin"),
        _event("roadmap_discussed", "plan_learning_path", ("structure",), "proposal"),
        _event("roadmap_applied", "apply_learning_path", ("structure",), "confirmed_action"),
        _event("roadmap_revised", "revise_project_roadmap", ("structure",), "confirmed_action", origin="vnext"),
        _event("project_free_conversation_created", "manage_project_conversations", (), "operational_context", origin="vnext"),
        _event("checkpoint_entered", "navigate_checkpoint", ("structure",), "navigation"),
        _event("lecture_generated", "generate_lecture", ("knowledge",), "exposure"),
        _event("lecture_viewed", "generate_lecture", ("knowledge",), "exposure"),
        _event("assessment_generated", "generate_assessment", (), "artifact"),
        _event("explanation_requested", "explain_selection", ("knowledge", "human"), "assistance"),
        _event("code_review_requested", "explain_selection", ("practice", "human"), "assistance", workbench="assessment"),
        _event("concept_attempt_evaluated", "evaluate_attempt", ("knowledge", "practice", "structure", "human"), "graded_attempt_with_optional_explicit_reflection"),
        _event("exercise_attempt_evaluated", "evaluate_attempt", ("knowledge", "practice"), "graded_attempt"),
        _event("remediation_started", "request_remediation_explanation", ("knowledge", "human", "practice"), "diagnosis", origin="fused"),
        _event("remediation_mode_rejected", "request_remediation_explanation", ("human", "knowledge"), "preference_evidence", origin="fused"),
        _event("remediation_explanation_requested", "request_remediation_explanation", ("human", "knowledge"), "assistance", origin="fused"),
        _event("remediation_retry_evaluated", "retry_attempt", ("knowledge", "practice"), "graded_retry", origin="fused"),
        _event("remediation_variant_evaluated", "evaluate_transfer_variant", ("knowledge", "practice"), "transfer_evidence", origin="fused"),
        _event("remediation_completed", "evaluate_transfer_variant", ("knowledge", "human", "practice"), "evidence_writeback", origin="fused"),
        _event("review_attempt_evaluated", "evaluate_review_attempt", ("knowledge", "practice"), "spaced_retrieval"),
        _event("review_reflection_recorded", "record_review_reflection", ("knowledge",), "learner_self_report"),
        _event("review_item_skipped", "manage_review_item", (), "operational"),
        _event("review_item_deferred", "manage_review_item", (), "operational"),
        _event("review_item_suspended", "manage_review_item", (), "operational"),
        _event("review_item_resumed", "manage_review_item", (), "operational"),
        _event("project_completed", "advance_checkpoint", ("structure", "value", "practice"), "milestone"),
        _event("workspace_linked", "link_project_workspace", (), "operational"),
        _event("workspace_change_applied", "apply_workspace_change", (), "operational"),
        _event("local_agent_started", "delegate_local_agent_task", (), "operational"),
        _event("local_agent_completed", "inspect_local_agent_run", (), "operational"),
        _event("local_agent_canceled", "cancel_local_agent_run", (), "operational"),
        _event("local_agent_result_applied", "apply_local_agent_result", (), "operational"),
        _event("task_completed", "record_task_outcome", (), "operational"),
        _event("task_failed", "record_task_outcome", ("structure",), "operational_failure"),
        _event("tool_failed", "record_task_outcome", ("structure",), "operational_failure"),
    )
}


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


_PYTHON_BINDING_TARGETS = {
    "py:action_board.execute": ("app.services.tutor_service", "execute_action"),
    "py:plugin.package.load": ("app.services.plugin_packages", "load_plugin_package"),
    "py:plugin.release.import": ("app.services.plugin_host", "import_plugin_release"),
    "py:plugin.instance.enable": ("app.services.plugin_host", "enable_plugin_instance"),
    "py:plugin.instance.update": ("app.services.plugin_host", "update_plugin_instance"),
    "py:plugin.workflow.execute": ("app.services.plugin_host", "execute_plugin_operation"),
    "py:plugin.role_capability_agent_package": (
        "app.services.role_capability_agent_package", "run_role_capability_workflow",
    ),
    "py:plugin.learning_task_agent_package": (
        "app.services.learning_task_agent_package", "run_learning_task_workflow",
    ),
    "py:workflow.learning_task.generate": (
        "app.services.learning_task_conversion_xfyun", "generate_xingchen_learning_task",
    ),
    "py:plugin.tool.discover": ("app.services.plugin_host", "discover_plugin_tools"),
    "py:plugin.surfaces.read": ("app.services.plugin_host", "plugin_surfaces"),
    "py:plugin.host_port.call": ("app.services.plugin_host_ports", "call_plugin_host_port"),
    "py:plugin.process.broker": ("app.services.plugin_runner", "PluginProcessBroker"),
    "py:tutor.process_turn": ("app.services.tutor_service", "process_turn"),
    "py:tutor.context": ("app.services.tutor_service", "get_session_state_summary"),
    "py:tutor.search_projects": ("app.services.tutor_service", "search_learning_projects"),
    "py:tutor.draft_project": ("app.services.tutor_service", "draft_learning_project"),
    "py:tutor.finalize_task": ("app.services.tutor_service", "finalize_action_for_task"),
    "py:chat_modes.classify": ("app.services.chat_modes", "classify_chat_mode"),
    "py:teaching_contract.evaluate": ("app.services.teaching_contract", "evaluate_teaching_contract"),
    "py:source_version.ensure": ("app.services.domain_knowledge", "ensure_source_version"),
    "py:domain_packet.compile": ("app.services.domain_knowledge", "compile_domain_knowledge_packet"),
    "py:source_integrity.inspect": ("app.services.domain_knowledge", "inspect_source_chunks"),
    "py:delivery_readiness.read": ("app.services.delivery_readiness", "checkpoint_delivery_readiness"),
    "py:checkpoint.context": ("app.services.checkpoint_context", "build_checkpoint_tutor_context"),
    "py:source.processor": ("app.services.chunker", "SourceProcessor"),
    "py:source.domains": ("app.services.source_knowledge", "derive_source_knowledge_domains"),
    "py:roadmap.agent": ("app.services.roadmap_agent", "RoadmapAgent"),
    "py:lecture.agent": ("app.services.lecture_agent", "LectureAgent"),
    "py:concept.agent": ("app.services.concept_agent", "ConceptAgent"),
    "py:exercise.agent": ("app.services.exercise_agent", "ExerciseAgent"),
    "py:animation.agent": ("app.services.animation_agent", "AnimationAgent"),
    "py:code.execute": ("app.services.code_executor", "execute_code"),
    "py:assessment.create": ("app.services.assessment_design", "create_assessment_blueprint"),
    "py:practice.create": ("app.services.dynamic_practice", "create_practice_set"),
    "py:practice.grade": ("app.services.dynamic_practice", "grade_structured_response"),
    "py:remediation.strategy": ("app.services.remediation", "RemediationStrategy"),
    "py:review.schedule": ("app.services.review", "apply_assessment_result"),
    "py:review.context": ("app.services.review", "build_review_tutor_context"),
    "py:review.proficiency": ("app.services.review_proficiency", "build_concept_proficiency"),
    "py:evidence.record": ("app.services.learning_runtime", "record_event"),
    "py:reducer.reduce": ("app.services.learning_runtime", "_reduce_event"),
    "py:memory_graph.create": ("app.services.memory_graph", "create_facts_for_mutation"),
    "py:kernel_head.refresh": ("app.services.five_kernel_context", "refresh_kernel_head"),
    "py:five_kernel.context": ("app.services.five_kernel_context", "build_five_kernel_context"),
    "py:learning_skill.prepare": ("app.services.learning_skill_runtime", "prepare_learning_skill_turn"),
    "py:learning_skill.create": ("app.services.learning_skill_runtime", "create_learning_skill_run"),
    "py:learning_task.reconcile": ("app.services.learning_tasks", "reconcile_learning_task"),
    "py:learning_task.plan": ("app.services.learning_tasks", "generate_learning_task_plan"),
    "py:micro_learning.create": ("app.services.micro_learning", "create_micro_learning_run"),
    "py:micro_learning.analyze": ("app.services.micro_learning", "analyze_teach_back"),
    "py:workspace.delete_conversation": ("app.services.workspace_lifecycle", "delete_conversation_workspace"),
    "py:workspace.delete_project": ("app.services.workspace_lifecycle", "delete_project_workspace"),
    "py:workspace.scan": ("app.services.workspace_files", "scan_workspace_tree"),
    "py:local_agent.create": ("app.services.local_agent_broker", "create_run_for_action"),
    "py:demo.seed": ("app.services.demo_seed", "seed_competition_demo"),
    "py:demo.grade_seeded_code": ("app.services.demo_code_grader", "grade_seeded_demo_code"),
    "py:task.manager": ("app.services.task_manager", "TaskManager"),
    "py:personal_concept_graph.build": ("app.services.personal_concept_graph", "build_personal_concept_graph"),
    "py:profile.growth": ("app.services.profile", "growth_projection"),
    "py:project_resources.search": ("app.services.project_proposals", "start_resource_search"),
}


_PYTHON_MEMBER_BINDING_TARGETS = {
    f"py:learning_skill_runtime:{skill_id}": (
        "app.services.learning_skill_runtime", "RUNTIME_SKILL_IDS", skill_id,
    )
    for skill_id in (
        "guided_explanation", "socratic_dialogue", "feynman_dialogue",
        "worked_example_fading", "learning_file_study",
    )
} | {
    f"host-interface:{interface_id}": (
        "app.services.plugin_host", "HOST_PORT_POLICIES", interface_id,
    )
    for interface_id in HOST_INTERFACES
}


_API_BINDING_TARGETS = {
    "api:plugins.publishers.create": ("app.api.plugins", "/admin/plugin-publishers", "POST", "create_plugin_publisher"),
    "api:plugins.releases.import": ("app.api.plugins", "/admin/plugin-releases/import", "POST", "import_plugin_release_bundle"),
    "api:plugins.instances.list": ("app.api.plugins", "/projects/{project_id}/plugin-instances", "GET", "list_project_plugin_instances"),
    "api:plugins.instances.enable": ("app.api.plugins", "/projects/{project_id}/plugin-instances/{plugin_id}", "PUT", "put_project_plugin_instance"),
    "api:plugins.instances.patch": ("app.api.plugins", "/projects/{project_id}/plugin-instances/{plugin_id}", "PATCH", "patch_project_plugin_instance"),
    "api:plugins.workflows.run": ("app.api.plugins", "/projects/{project_id}/plugin-instances/{plugin_id}/workflows/{workflow_id}/runs", "POST", "run_project_plugin_workflow"),
    "api:plugins.runs.read": ("app.api.plugins", "/plugin-runs/{run_id}", "GET", "get_plugin_run"),
    "api:plugins.snapshots.list": ("app.api.plugins", "/projects/{project_id}/plugin-instances/{plugin_id}/snapshots", "GET", "list_plugin_snapshots"),
    "api:plugins.objects.list": ("app.api.plugins", "/projects/{project_id}/plugin-instances/{plugin_id}/objects", "GET", "list_plugin_objects"),
    "api:plugins.objects.read": ("app.api.plugins", "/projects/{project_id}/plugin-instances/{plugin_id}/objects/{object_id:path}", "GET", "get_plugin_object"),
    "api:plugins.surfaces.list": ("app.api.plugins", "/projects/{project_id}/plugin-surfaces", "GET", "list_project_plugin_surfaces"),
    "api:plugins.tools.discover": ("app.api.plugins", "/projects/{project_id}/plugin-tools", "GET", "discover_project_plugin_tools"),
    "api:plugins.tools.call": ("app.api.plugins", "/projects/{project_id}/plugin-tools/{qualified_tool_id}/calls", "POST", "call_project_plugin_tool"),
    "api:agent.sync_vnext_session": ("app.api.agent", "/agent/sessions/{session_id}/vnext", "PUT", "sync_vnext_session"),
    "api:agent.start_skill_run": ("app.api.agent", "/agent/sessions/{session_id}/skill-runs", "POST", "start_learning_skill_run"),
    "api:agent.advance_skill_turn": ("app.api.agent", "/agent/sessions/{session_id}/skill-runs/{run_id}/turns", "POST", "advance_learning_skill_turn"),
    "api:agent.skill_action": ("app.api.agent", "/agent/sessions/{session_id}/skill-runs/{run_id}/actions", "POST", "update_learning_skill_run"),
    "api:agent.tutor_turn": ("app.api.agent", "/agent/sessions/{session_id}/turns", "POST", "tutor_turn"),
    "api:agent.visual_plan": ("app.api.agent", "/agent/sessions/{session_id}/visual-plans", "POST", "plan_visual_for_desktop"),
    "api:agent.delete_session": ("app.api.agent", "/agent/sessions/{session_id}", "DELETE", "delete_session"),
    "api:agent.patch_proposal": ("app.api.agent", "/agent/project-proposals/{proposal_id}", "PATCH", "patch_project_proposal"),
    "api:agent.accept_proposal": ("app.api.agent", "/agent/project-proposals/{proposal_id}/accept", "POST", "accept_project_proposal"),
    "api:learner_state.workspace": ("app.api.learner_state", "/learner-state/agent-workspace-context", "GET", "get_agent_workspace_context"),
    "api:learner_state.event": ("app.api.learner_state", "/learner-state/events", "POST", "sync_learner_event"),
    "api:learner_state.context": ("app.api.learner_state", "/learner-state/context", "GET", "get_learner_context"),
    "api:learner_state.concept_graph": ("app.api.learner_state", "/learner-state/concept-graph", "GET", "get_personal_concept_graph"),
    "api:learner_state.concept_statement": ("app.api.learner_state", "/learner-state/concept-graph/statements", "POST", "record_concept_statement"),
    "api:learner_state.path_status": ("app.api.learner_state", "/learner-state/learning-path/status", "POST", "set_learning_path_status"),
    "api:learner_state.personal_node": ("app.api.learner_state", "/learner-state/learning-path/personal-nodes", "POST", "add_personal_learning_path_node"),
    "api:learner_state.path_plan": ("app.api.learner_state", "/learner-state/learning-path/plans", "POST", "commit_learning_path_plan"),
    "api:learner_state.value_claim": ("app.api.learner_state", "/learner-state/value-claims/confirm", "POST", "confirm_value_claim"),
    "api:knowledge_library.context": ("app.api.knowledge_library", "/knowledge-library/context", "GET", "read_library_context"),
    "api:knowledge_library.web_evidence": ("app.api.knowledge_library", "/knowledge-library/web-evidence", "POST", "capture_web_evidence"),
    "api:knowledge_library.add_url": ("app.api.knowledge_library", "/knowledge-library/sources/url", "POST", "add_library_url"),
    "api:learning_files.list": ("app.api.learning_files", "/learning-files", "GET", "list_learning_files"),
    "api:learning_files.generate": ("app.api.learning_files", "/learning-files/tasks/{task_id}/generate", "POST", "generate_task_learning_files"),
    "api:learning_files.practice_generate": ("app.api.learning_files", "/learning-files/practice/generate", "POST", "generate_dynamic_practice_file"),
    "api:learning_files.quality": ("app.api.learning_files", "/learning-files/practice/{practice_ref}/quality", "POST", "inspect_dynamic_practice_quality"),
    "api:learning_files.open": ("app.api.learning_files", "/learning-files/{kind}/{ref}/opened", "POST", "record_learning_file_opened"),
    "api:learning_files.attach": ("app.api.learning_files", "/learning-files/{kind}/{ref}/attached", "POST", "record_learning_file_attached"),
    "api:vnext_projects.list": ("app.api.vnext_projects", "/vnext-projects", "GET", "list_vnext_projects"),
    "api:vnext_projects.create": ("app.api.vnext_projects", "/vnext-projects", "POST", "create_vnext_project"),
    "api:vnext_projects.context": ("app.api.vnext_projects", "/vnext-projects/{project_id}/agent-context", "GET", "get_project_agent_context"),
    "api:vnext_projects.baseline": ("app.api.vnext_projects", "/vnext-projects/{project_id}/knowledge-baseline", "GET", "read_project_knowledge_baseline"),
    "api:vnext_projects.baseline_propose": ("app.api.vnext_projects", "/vnext-projects/{project_id}/knowledge-baseline/proposals", "POST", "propose_project_knowledge_baseline"),
    "api:vnext_projects.baseline_confirm": ("app.api.vnext_projects", "/vnext-projects/{project_id}/knowledge-baseline/{packet_id}/confirm", "POST", "confirm_project_knowledge_baseline"),
    "api:vnext_projects.source_health": ("app.api.vnext_projects", "/vnext-projects/{project_id}/sources/{source_id}/health", "POST", "update_project_source_health"),
    "api:vnext_projects.apply_roadmap": ("app.api.vnext_projects", "/vnext-projects/{project_id}/roadmap/apply", "POST", "apply_vnext_roadmap"),
    "api:vnext_projects.revise_roadmap": ("app.api.vnext_projects", "/vnext-projects/{project_id}/roadmap", "PUT", "revise_vnext_roadmap"),
    "api:vnext_projects.create_session": ("app.api.vnext_projects", "/vnext-projects/{project_id}/sessions", "POST", "create_project_free_session"),
    "api:role_capability.read": ("app.api.role_capability", "/role-capability/projects/{project_id}", "GET", "read_role_capability_package"),
    "api:role_capability.generate": ("app.api.role_capability", "/role-capability/projects/{project_id}/generate", "POST", "generate_role_capability_package"),
    "api:role_capability.explain": ("app.api.role_capability", "/role-capability/projects/{project_id}/explain", "POST", "explain_role_capability_package"),
    "api:role_capability.iterate": ("app.api.role_capability", "/role-capability/projects/{project_id}/iterate", "POST", "iterate_role_capability_package"),
    "api:assessment_blueprint.propose": ("app.api.assessment_design", "/assessment-blueprints", "POST", "propose_assessment_blueprint"),
    "api:memory.feedback": ("app.api.memory", "/memory/claims/{claim_id}/feedback", "POST", "submit_claim_feedback"),
    "api:profile.update": ("app.api.profile", "/profile", "PATCH", "update_profile"),
    "api:profile.growth": ("app.api.profile", "/profile/growth", "GET", "get_growth"),
    "api:projects.create": ("app.api.projects", "/projects", "POST", "create_project"),
    "api:projects.delete": ("app.api.projects", "/projects/{project_id}", "DELETE", "delete_project"),
    "api:projects.add_source": ("app.api.projects", "/projects/{project_id}/sources", "POST", "add_source"),
    "api:projects.roadmap": ("app.api.projects", "/projects/{project_id}/roadmap", "GET", "get_roadmap"),
    "api:learning_tasks.list": ("app.api.learning_tasks", "/learning-tasks", "GET", "list_learning_tasks"),
    "api:learning_tasks.create": ("app.api.learning_tasks", "/learning-tasks", "POST", "create_task"),
    "api:learning_tasks.action": ("app.api.learning_tasks", "/learning-tasks/{task_id}/actions", "POST", "task_action"),
    "api:learning_tasks.replan": ("app.api.learning_tasks", "/learning-tasks/{task_id}/replan", "POST", "replan_task"),
    "api:micro_learning.create": ("app.api.micro_learning", "/micro-learning/runs", "POST", "create_run"),
    "api:micro_learning.advance": ("app.api.micro_learning", "/micro-learning/runs/{run_id}/advance", "POST", "advance"),
    "api:micro_learning.teach_back": ("app.api.micro_learning", "/micro-learning/runs/{run_id}/teach-back", "POST", "teach_back"),
    "api:review.context": ("app.api.review", "/review/agent-context", "GET", "review_agent_context"),
    "api:review.reflection": ("app.api.review", "/review/items/{schedule_id}/reflections", "POST", "record_review_reflection"),
    "api:review.submit": ("app.api.review", "/review/items/{schedule_id}/submit", "POST", "submit_review_item"),
    "api:review.defer": ("app.api.review", "/review/items/{schedule_id}/defer", "POST", "defer_review_item"),
    "api:remediation.explain": ("app.api.remediation", "/remediation/{case_id}/explanations", "POST", "change_remediation_explanation"),
    "api:remediation.variant": ("app.api.remediation", "/remediation/{case_id}/variant/submit", "POST", "evaluate_remediation_variant"),
    "api:phase2.generate_lecture": ("app.api.phase2", "/checkpoints/{checkpoint_id}/lecture/generate", "POST", "generate_lecture_task"),
    "api:phase2.ask": ("app.api.phase2", "/checkpoints/{checkpoint_id}/ask", "POST", "ask_question"),
    "api:phase2.put_lecture": ("app.api.phase2", "/checkpoints/{checkpoint_id}/lecture", "PUT", "put_lecture"),
    "api:phase3.generate_concepts": ("app.api.phase3", "/checkpoints/{checkpoint_id}/concepts/generate", "POST", "generate_concepts"),
    "api:phase3.submit_concept": ("app.api.phase3", "/checkpoints/{checkpoint_id}/concepts/{question_id}/submit", "POST", "submit_concept"),
    "api:phase3.submit_exercise": ("app.api.phase3", "/exercises/{exercise_id}/submit", "POST", "submit_exercise"),
    "api:workspace.link": ("app.api.workspace", "/projects/{project_id}/workspace/link", "POST", "link_workspace"),
    "api:workspace.tree": ("app.api.workspace", "/projects/{project_id}/workspace/tree", "GET", "workspace_tree"),
    "api:workspace.propose": ("app.api.workspace", "/projects/{project_id}/workspace/operations/propose", "POST", "propose_workspace_operation"),
    "api:workspace.confirm": ("app.api.workspace", "/projects/{project_id}/workspace/operations/{operation_id}/confirm", "POST", "confirm_workspace_operation"),
    "api:local_agent.inspect": ("app.api.local_agent", "/local-agent/runs/{run_id}", "GET", "get_local_agent_run"),
    "api:local_agent.cancel": ("app.api.local_agent", "/local-agent/runs/{run_id}/cancel", "POST", "cancel_local_agent_run"),
    "api:local_agent.apply": ("app.api.local_agent", "/local-agent/runs/{run_id}/apply", "POST", "apply_local_agent_run"),
    "api:demo.status": ("app.api.auth", "/demo/status", "GET", "competition_demo_status"),
}


_FRONTEND_HANDLER_TARGETS = {
    "frontend:agent_runtime.run": ("frontend/server/agent-runtime.ts", "runTutorAgentTurn", ""),
    "frontend:visual.generate": ("frontend/server/learning-visual-spec.ts", "generateLearningVisual", ""),
    "frontend:paper.ancestors": ("frontend/src/paper-workbench.ts", "paperAncestorChain", ""),
    "frontend:learning.create": ("frontend/src/learning.ts", "createLearningTask", ""),
    "frontend:planning.create": ("frontend/src/planning.ts", "createLearningPlan", ""),
    "frontend:path.read": ("frontend/src/learning-path-graph.ts", "readLearningPathGraph", ""),
    "frontend:path.lookup": ("frontend/src/learning-path-graph.ts", "lookupLearningPathGraph", ""),
    "frontend:path.search": ("frontend/src/learning-path-graph.ts", "searchLearningPathGraph", ""),
    "frontend:path.propose_node": ("frontend/src/learning-path-graph.ts", "buildPersonalNodeProposal", ""),
    "frontend:path.plan": ("frontend/src/learning-path-graph.ts", "buildLearningPathPlanProposal", ""),
    "frontend:profile.read": ("frontend/src/five-kernel-profile.ts", "readFiveKernelProfile", ""),
    "frontend:desktop.runtime": ("frontend/src/runtime-client.ts", "initializeRuntimeClient", ""),
    **{
        f"frontend:tool:{tool_name}": (
            "frontend/server/tool-runtime.ts", "executeTutorAgentTool", tool_name,
        )
        for tool_name in (
            "read_learner_context", "read_learning_workspace", "read_domain_knowledge",
            "read_active_learning_file", "read_project_workspace", "read_project_sources",
            "read_project_learning_file", "read_project_roadmap", "propose_project_roadmap",
            "propose_project_learning_files", "search_computer_knowledge", "read_web_evidence",
            "read_role_capability_graph", "explain_role_capability",
            "discover_project_plugin_tools", "call_project_plugin_tool",
            "search_learning_videos", "inspect_learning_video", "generate_learning_diagram",
            "generate_learning_animation", "design_assessment_blueprint",
            "generate_dynamic_practice", "generate_similar_practice", "inspect_practice_quality",
            "lookup_learning_path_node", "search_learning_path_graph",
            "propose_personal_path_node", "read_review_context",
        )
    },
}


_FRONTEND_COMPONENT_TARGETS = {
    "workbench:vnext_chat": ("frontend/src/main.tsx", "App", "/chat/"),
    "workbench:vnext_learning_path": ("frontend/src/LearningPathPage.tsx", "LearningPathPage", "/learning-path"),
    "workbench:vnext_profile": ("frontend/src/LearnerProfilePage.tsx", "LearnerProfilePage", "/learner-profile"),
    "workbench:vnext_learning_files": ("frontend/src/LearningFilesPage.tsx", "LearningFilesPage", "/learning-files"),
    "workbench:vnext_projects": ("frontend/src/ProjectsPage.tsx", "ProjectsPage", "/projects"),
    "workbench:vnext_lecture_file": ("frontend/src/LectureFilePage.tsx", "LectureFilePage", "/files/lecture/"),
    "workbench:vnext_practice_file": ("frontend/src/PracticeFilePage.tsx", "PracticeFilePage", "/files/practice/"),
    "workbench:learning_tasks": ("frontend/src/LearningTasksPage.tsx", "LearningTasksPage", "/tasks"),
    "workbench:project_tutor": ("frontend/src/ProjectWorkspacePage.tsx", "ProjectWorkspacePage", "/projects/"),
    "workbench:plugin_surface_host": ("frontend/src/ProjectPluginManager.tsx", "ProjectPluginManager", "/projects/"),
    "workbench:role_capability_plugin": ("frontend/src/RoleCapabilityChatPlugin.tsx", "RoleCapabilityChatPlugin", "/chat/"),
    "workbench:learning_task_plugin": ("frontend/src/LearningTaskPluginWorkspace.tsx", "LearningTaskPluginWorkspace", "/projects/"),
    "workbench:review": ("frontend/src/ReviewWorkbenchPage.tsx", "ReviewWorkbenchPage", "/review"),
    "workbench:competition_demo": ("frontend/src/ReviewWorkbenchPage.tsx", "ReviewWorkbenchPage", "/review"),
    "workbench:desktop_workspace": ("frontend/src/main.tsx", "App", ""),
}


_REPOSITORY_FILE_TARGETS = {
    "plugin-manifest:role_capability_graph": "plugins/role_capability_graph/manifest.json",
    "plugin-manifest:learning_task_conversion": "plugins/learning_task_conversion/manifest.json",
}


IMPLEMENTATION_BINDINGS = {
    **{
        binding_id: ImplementationBinding(
            binding_id, "python_symbol", module=module, symbol=symbol,
        )
        for binding_id, (module, symbol) in _PYTHON_BINDING_TARGETS.items()
    },
    **{
        binding_id: ImplementationBinding(
            binding_id, "python_collection_member", module=module,
            symbol=symbol, member=member,
        )
        for binding_id, (module, symbol, member) in _PYTHON_MEMBER_BINDING_TARGETS.items()
    },
    **{
        binding_id: ImplementationBinding(
            binding_id, "api_route", module=module, symbol="router",
            route=route, method=method, endpoint=endpoint,
        )
        for binding_id, (module, route, method, endpoint) in _API_BINDING_TARGETS.items()
    },
    **{
        binding_id: ImplementationBinding(
            binding_id, "frontend_handler", path=path, symbol=symbol, member=member,
        )
        for binding_id, (path, symbol, member) in _FRONTEND_HANDLER_TARGETS.items()
    },
    **{
        binding_id: ImplementationBinding(
            binding_id, "frontend_component", path=path, symbol=symbol, route=route,
        )
        for binding_id, (path, symbol, route) in _FRONTEND_COMPONENT_TARGETS.items()
    },
    **{
        binding_id: ImplementationBinding(
            binding_id, "repository_file", path=path,
        )
        for binding_id, path in _REPOSITORY_FILE_TARGETS.items()
    },
    **{
        event.reducer_binding: ImplementationBinding(
            event.reducer_binding or "", "reducer_event",
            module="app.services.learning_runtime", symbol="REDUCER_EVENT_TYPES",
            member=event.id,
        )
        for event in EVENTS.values() if event.reducer_binding
    },
}


_TOOL_BINDING_IDS = {
    "action_board": ("py:action_board.execute",),
    "workflow_gateway": ("py:workflow.learning_task.generate",),
    "plugin_package_runtime": (
        "py:plugin.package.load", "py:plugin.release.import",
        "py:plugin.instance.enable", "py:plugin.instance.update",
        "api:plugins.releases.import", "api:plugins.instances.enable",
        "api:plugins.instances.patch",
    ),
    "plugin_process_runner": (
        "py:plugin.process.broker", "py:plugin.workflow.execute",
        "api:plugins.workflows.run",
    ),
    "discover_project_plugin_tools": (
        "py:plugin.tool.discover", "api:plugins.tools.discover",
        "frontend:tool:discover_project_plugin_tools",
    ),
    "call_project_plugin_tool": (
        "py:plugin.workflow.execute", "api:plugins.tools.call",
        "frontend:tool:call_project_plugin_tool",
    ),
    "plugin_action_proposer": ("py:plugin.host_port.call",),
    "tutor_context": ("py:tutor.context",),
    "chat_mode_runtime": ("py:chat_modes.classify",),
    "vnext_agent_turn_runtime": ("frontend:agent_runtime.run",),
    "vnext_chat_session_store": ("api:agent.sync_vnext_session",),
    "computer_knowledge_search": ("frontend:tool:search_computer_knowledge",),
    "web_evidence_reader": ("frontend:tool:read_web_evidence",),
    "learning_video_search": ("frontend:tool:search_learning_videos",),
    "learning_video_inspector": ("frontend:tool:inspect_learning_video",),
    "teaching_contract_gate": ("py:teaching_contract.evaluate",),
    "source_version_runtime": ("py:source_version.ensure",),
    "domain_knowledge_packet_compiler": ("py:domain_packet.compile", "api:knowledge_library.web_evidence"),
    "source_integrity_monitor": ("py:source_integrity.inspect", "api:vnext_projects.source_health"),
    "checkpoint_delivery_readiness": ("py:delivery_readiness.read",),
    "safe_visual_generation": ("frontend:visual.generate", "api:agent.visual_plan"),
    "learning_diagram_generator": ("frontend:tool:generate_learning_diagram",),
    "learning_animation_generator": ("frontend:tool:generate_learning_animation",),
    "selection_followup_context": ("frontend:paper.ancestors",),
    "vnext_learning_task_runtime": ("py:learning_skill.prepare",),
    "vnext_learning_plan_runtime": ("frontend:planning.create",),
    "vnext_five_kernel_profile_reader": ("py:five_kernel.context",),
    "vnext_learning_workspace_reader": ("api:learner_state.workspace",),
    "domain_knowledge_reader": ("api:knowledge_library.context",),
    "learning_file_service": ("api:learning_files.list",),
    "active_learning_file_reader": ("frontend:tool:read_active_learning_file",),
    "assessment_blueprint_builder": ("py:assessment.create",),
    "dynamic_practice_generator": ("py:practice.create",),
    "similar_practice_generator": ("frontend:tool:generate_similar_practice",),
    "practice_quality_inspector": ("api:learning_files.quality",),
    "project_workspace_reader": ("api:vnext_projects.context",),
    "project_source_reader": ("frontend:tool:read_project_sources",),
    "project_learning_file_reader": ("frontend:tool:read_project_learning_file",),
    "project_roadmap_reader": ("frontend:tool:read_project_roadmap",),
    "project_roadmap_proposer": ("frontend:tool:propose_project_roadmap",),
    "project_learning_file_proposer": ("frontend:tool:propose_project_learning_files",),
    "role_capability_package_runtime": ("api:role_capability.generate",),
    "role_capability_graph_reader": ("frontend:tool:read_role_capability_graph", "api:role_capability.read"),
    "role_capability_explainer": ("frontend:tool:explain_role_capability", "api:role_capability.explain"),
    "role_capability_iteration_runtime": ("api:role_capability.iterate",),
    "vnext_learning_path_graph_reader": ("frontend:path.read",),
    "vnext_learning_path_exact_reader": ("frontend:path.lookup",),
    "vnext_learning_path_fuzzy_reader": ("frontend:path.search",),
    "vnext_personal_path_node_proposer": ("frontend:path.propose_node",),
    "vnext_learning_path_planner": ("frontend:path.plan",),
    "vnext_learning_path_plan_manager": ("api:learner_state.path_plan",),
    "personal_concept_graph_reader": ("api:learner_state.concept_graph",),
    "concept_self_report_gateway": ("api:learner_state.concept_statement",),
    "vnext_personal_path_node_runtime": ("api:learner_state.path_status", "api:learner_state.personal_node"),
    "learner_memory_manager": ("api:memory.feedback",),
    "vnext_five_kernel_explicit_editor": ("api:profile.update", "api:learner_state.value_claim"),
    "workspace_lifecycle": ("py:workspace.delete_conversation", "py:workspace.delete_project"),
    "checkpoint_context": ("py:checkpoint.context",),
    "source_ingestion": ("py:source.processor",),
    "repository_knowledge_domains": ("py:source.domains",),
    "hierarchical_rag": ("py:lecture.agent",),
    "content_generation": ("py:roadmap.agent", "py:lecture.agent", "py:concept.agent", "py:exercise.agent"),
    "micro_learning_orchestrator": ("py:micro_learning.create",),
    "learning_skill_runtime": ("py:learning_skill.create",),
    "learning_task_runtime": ("py:learning_task.reconcile",),
    "learning_task_planner": ("py:learning_task.plan",),
    "teach_back_analyzer": ("py:micro_learning.analyze",),
    "process_animation": ("py:animation.agent",),
    "code_executor": ("py:code.execute",),
    "deterministic_assessment": ("py:practice.grade",),
    "deterministic_remediation": ("py:remediation.strategy",),
    "review_scheduler": ("py:review.schedule",),
    "review_proficiency_projector": ("py:review.proficiency",),
    "review_context_reader": ("py:review.context",),
    "review_reflection_gateway": ("api:review.reflection",),
    "evidence_ledger": ("py:evidence.record",),
    "five_kernel_reducer": ("py:reducer.reduce",),
    "memory_graph": ("py:memory_graph.create",),
    "kernel_head_projector": ("py:kernel_head.refresh",),
    "five_kernel_retriever": ("py:five_kernel.context",),
    "context_packet_assembler": ("py:five_kernel.context",),
    "seeded_demo": ("py:demo.seed", "py:demo.grade_seeded_code", "api:demo.status"),
    "task_runtime": ("py:task.manager",),
    "workspace_file_service": ("py:workspace.scan",),
    "managed_artifact_service": ("api:phase2.put_lecture",),
    "local_agent_broker": ("py:local_agent.create",),
}


_OPTIONAL_TOOL_NOTES = {
    "workflow_validator": "No workflow builder or validator implementation exists in this repository.",
}


_DEPRECATED_TOOL_NOTES = {
    "role_capability_package_runtime": (
        "Compatibility alias; generation is implemented by the generic plugin workflow host."
    ),
    "role_capability_graph_reader": (
        "Compatibility alias; Tutor discovers the namespaced read_graph tool at runtime."
    ),
    "role_capability_explainer": (
        "Compatibility alias; Tutor discovers the namespaced explain tool at runtime."
    ),
    "role_capability_iteration_runtime": (
        "Compatibility alias; iteration is implemented by the generic plugin workflow host."
    ),
}


TOOL_PUBLICATIONS = {
    tool_id: PublicationContract(
        (
            "optional_unimplemented" if tool_id in _OPTIONAL_TOOL_NOTES
            else "deprecated" if tool_id in _DEPRECATED_TOOL_NOTES
            else "implemented"
        ),
        (
            () if tool_id in _OPTIONAL_TOOL_NOTES
            else _TOOL_BINDING_IDS.get(tool_id, ())
        ),
        _OPTIONAL_TOOL_NOTES.get(tool_id, _DEPRECATED_TOOL_NOTES.get(tool_id, "")),
    )
    for tool_id in TOOLS
}


_SKILL_BINDING_IDS = {
    "intent_and_handoff": ("py:tutor.process_turn",),
    "external_workflow_rendering": ("py:workflow.learning_task.generate",),
    **{
        skill_id: (f"py:learning_skill_runtime:{skill_id}",)
        for skill_id in (
            "guided_explanation", "socratic_dialogue", "feynman_dialogue",
            "worked_example_fading", "learning_file_study",
        )
    },
    "checkpoint_tutoring": ("py:checkpoint.context",),
    "atomic_learning_loop": ("py:learning_task.reconcile",),
    "verified_micro_learning": ("py:micro_learning.create",),
    "feynman_teach_back": ("py:micro_learning.analyze",),
    "learning_path_planning": ("frontend:path.plan", "py:roadmap.agent"),
    "learning_resource_curation": ("frontend:agent_runtime.run", "frontend:tool:search_computer_knowledge"),
    "project_apprenticeship_orchestration": ("api:vnext_projects.context", "api:vnext_projects.apply_roadmap"),
    "project_plugin_orchestration": (
        "py:plugin.tool.discover", "py:plugin.workflow.execute",
        "py:plugin.host_port.call", "api:plugins.tools.discover",
        "api:plugins.tools.call",
    ),
    "role_capability_graphing": (
        "plugin-manifest:role_capability_graph", "py:plugin.role_capability_agent_package",
        "py:plugin.workflow.execute",
        "api:plugins.workflows.run", "api:plugins.tools.call",
    ),
    "evidence_grounded_teaching": ("py:lecture.agent",),
    "practice_verification": ("api:phase3.submit_concept", "api:phase3.submit_exercise"),
    "assessment_blueprint_design": ("py:assessment.create",),
    "dynamic_practice_loop": ("py:practice.create", "py:practice.grade"),
    "remediation_loop": ("py:remediation.strategy",),
    "spaced_review": ("py:review.schedule", "py:review.proficiency"),
    "learner_memory_synthesis": ("py:memory_graph.create", "py:five_kernel.context"),
    "workspace_file_management": ("api:workspace.link", "api:workspace.confirm"),
    "managed_learning_file_playback": ("api:learning_files.list", "api:phase2.put_lecture"),
    "local_agent_delegation": ("py:local_agent.create", "api:local_agent.apply"),
}


SKILL_PUBLICATIONS = {
    skill_id: PublicationContract(
        "implemented",
        _SKILL_BINDING_IDS.get(skill_id, ()),
        "",
    )
    for skill_id in SKILLS
}


_WORKBENCH_LIFECYCLES = {
    "global_tutor": ("deprecated", "Replaced by the canonical /chat/:conversationId frontend."),
    "focused_learning": ("optional_unimplemented", "The /learn/:runId frontend surface is not routed by the canonical frontend."),
    "lecture": ("deprecated", "The legacy checkpoint lecture surface is replaced by project and lecture-file workbenches."),
    "assessment": ("deprecated", "The legacy checkpoint assessment surface is replaced by practice-file and review workbenches."),
    "remediation": ("deprecated", "Remediation is integrated into practice and review; no standalone RemediationPanel component is published."),
    "learner_growth": ("optional_unimplemented", "The /growth frontend surface is not routed by the canonical frontend."),
    "profile": ("deprecated", "Legacy /profile redirect is not a canonical frontend workbench."),
    "memory": ("deprecated", "Legacy /memory redirect is not a canonical frontend workbench."),
    "xingchen_studio": ("optional_unimplemented", "No Xingchen Studio runtime or repository-owned route exists."),
}


WORKBENCH_PUBLICATIONS = {
    workbench_id: PublicationContract(
        _WORKBENCH_LIFECYCLES.get(workbench_id, ("implemented", ""))[0],
        (
            () if workbench_id in _WORKBENCH_LIFECYCLES
            else (f"workbench:{workbench_id}",)
        ),
        _WORKBENCH_LIFECYCLES.get(workbench_id, ("implemented", ""))[1],
    )
    for workbench_id in WORKBENCHES
}


_OPTIONAL_CAPABILITY_NOTES = {
    "recommend_learning_resources": "No standalone recommendation handler commits this declared capability; the underlying readers remain available.",
    "search_learning_resources": "No Action Board execution branch or dedicated API route implements this capability.",
}


CAPABILITY_PUBLICATIONS = {
    capability: PublicationContract(
        "optional_unimplemented" if capability in _OPTIONAL_CAPABILITY_NOTES else "implemented",
        (
            () if capability in _OPTIONAL_CAPABILITY_NOTES
            else TOOL_PUBLICATIONS[tool].bindings
        ),
        _OPTIONAL_CAPABILITY_NOTES.get(capability, ""),
    )
    for capability, (_, tool, _) in CAPABILITY_OWNERS.items()
}


EVENT_PUBLICATIONS = {
    event.id: PublicationContract(
        CAPABILITY_PUBLICATIONS[event.capability].lifecycle,
        tuple(dict.fromkeys((
            *CAPABILITY_PUBLICATIONS[event.capability].bindings,
            *((event.reducer_binding,) if event.reducer_binding else ()),
        ))),
        CAPABILITY_PUBLICATIONS[event.capability].note,
    )
    for event in EVENTS.values()
}


HOST_INTERFACE_PUBLICATIONS = {
    interface_id: PublicationContract(
        "implemented", (f"host-interface:{interface_id}",),
    )
    for interface_id in HOST_INTERFACES
}


PLUGIN_PUBLICATIONS = {
    "role_capability_graph": PublicationContract(
        "implemented",
        (
            "plugin-manifest:role_capability_graph",
            "py:plugin.role_capability_agent_package",
            "py:plugin.workflow.execute",
            "workbench:plugin_surface_host",
            "workbench:role_capability_plugin",
        ),
    ),
    "learning_task_conversion": PublicationContract(
        "implemented",
        (
            "plugin-manifest:learning_task_conversion",
            "py:plugin.learning_task_agent_package",
            "py:plugin.workflow.execute",
            "workbench:plugin_surface_host",
            "workbench:learning_task_plugin",
        ),
    ),
}


PUBLICATIONS = {
    "tools": TOOL_PUBLICATIONS,
    "skills": SKILL_PUBLICATIONS,
    "workbenches": WORKBENCH_PUBLICATIONS,
    "capabilities": CAPABILITY_PUBLICATIONS,
    "events": EVENT_PUBLICATIONS,
    "host_interfaces": HOST_INTERFACE_PUBLICATIONS,
    "plugins": PLUGIN_PUBLICATIONS,
}


def _frontend_symbol_pattern(symbol: str) -> re.Pattern[str]:
    escaped = re.escape(symbol)
    return re.compile(
        rf"\b(?:export\s+)?(?:default\s+)?(?:async\s+)?"
        rf"(?:function|class|const)\s+{escaped}\b"
    )


def _binding_failure(
    binding: ImplementationBinding,
    source_cache: dict[str, str],
) -> str | None:
    try:
        if binding.kind in {"python_symbol", "python_collection_member", "reducer_event"}:
            module = importlib.import_module(binding.module)
            target: Any = module
            for part in binding.symbol.split("."):
                target = getattr(target, part)
            if binding.kind in {"python_collection_member", "reducer_event"}:
                if binding.member not in target:
                    return f"{binding.module}.{binding.symbol} does not declare {binding.member}"
            return None
        if binding.kind == "api_route":
            module = importlib.import_module(binding.module)
            router = getattr(module, binding.symbol)
            endpoint = getattr(module, binding.endpoint)
            for route in router.routes:
                if (
                    getattr(route, "path", None) == binding.route
                    and binding.method.upper() in (getattr(route, "methods", set()) or set())
                    and getattr(route, "endpoint", None) is endpoint
                ):
                    return None
            return (
                f"{binding.module}.{binding.endpoint} is not bound to "
                f"{binding.method.upper()} {binding.route}"
            )
        if binding.kind in {"frontend_handler", "frontend_component"}:
            path = _REPOSITORY_ROOT / binding.path
            if not path.is_file():
                return f"frontend source does not exist: {binding.path}"
            source = source_cache.setdefault(binding.path, path.read_text(encoding="utf-8"))
            if not _frontend_symbol_pattern(binding.symbol).search(source):
                return f"frontend symbol {binding.symbol} is missing from {binding.path}"
            if binding.member and not re.search(
                rf"(['\"])({re.escape(binding.member)})\1", source,
            ):
                return f"frontend handler {binding.symbol} does not declare {binding.member}"
            if binding.route and binding.route not in source:
                # Route ownership lives in main.tsx, while lazily loaded page
                # components remain independently inspectable.
                route_source_path = "frontend/src/main.tsx"
                route_source = source_cache.setdefault(
                    route_source_path,
                    (_REPOSITORY_ROOT / route_source_path).read_text(encoding="utf-8"),
                )
                if binding.route not in route_source:
                    return f"frontend route marker {binding.route} is not wired in main.tsx"
            return None
        if binding.kind == "repository_file":
            path = _REPOSITORY_ROOT / binding.path
            if not path.is_file():
                return f"repository file does not exist: {binding.path}"
            return None
        return f"unknown implementation binding kind: {binding.kind}"
    except Exception as exc:  # Validation must report a broken binding, not fail the endpoint.
        return f"{binding.kind} binding could not be resolved: {exc}"


def implementation_binding_failures() -> dict[str, str]:
    failures: dict[str, str] = {}
    source_cache: dict[str, str] = {}
    for binding_id, binding in IMPLEMENTATION_BINDINGS.items():
        failure = _binding_failure(binding, source_cache)
        if failure:
            failures[binding_id] = failure
    return failures


def publication_available(
    category: str,
    item_id: str,
    *,
    binding_failures: dict[str, str] | None = None,
) -> bool:
    publication = PUBLICATIONS[category][item_id]
    if publication.lifecycle != "implemented":
        return False
    failures = binding_failures if binding_failures is not None else implementation_binding_failures()
    return all(binding_id not in failures for binding_id in publication.bindings)


def _publication_fields(
    category: str,
    item_id: str,
    binding_failures: dict[str, str],
) -> dict[str, Any]:
    publication = PUBLICATIONS[category][item_id]
    return {
        "lifecycle": publication.lifecycle,
        "binding_ids": list(publication.bindings),
        "available": publication_available(
            category, item_id, binding_failures=binding_failures,
        ),
        "lifecycle_note": publication.note,
    }


def capability_manifest(
    binding_failures: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    failures = binding_failures if binding_failures is not None else implementation_binding_failures()
    result = []
    for capability, spec in sorted(ACTION_BOARD.items()):
        owner, tool, workbench = CAPABILITY_OWNERS.get(capability, ("unassigned", "unassigned", "unassigned"))
        row = asdict(spec)
        row.update({"owner_agent": owner, "tool": tool, "workbench": workbench})
        row.update(_publication_fields("capabilities", capability, failures))
        result.append(row)
    return result


def selectable_learning_skill_manifest() -> list[dict[str, Any]]:
    """Return the learner-facing portion of registered conversational skills."""
    result = []
    for skill in SKILLS.values():
        if (
            not skill.learner_selectable
            or SKILL_PUBLICATIONS[skill.id].lifecycle != "implemented"
        ):
            continue
        result.append({
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "best_for": list(skill.best_for),
            "avoid_when": list(skill.avoid_when),
            "atomic_task_capable": skill.atomic_task_capable,
            "spec_version": skill.spec_version,
            "runtime": asdict(skill.runtime) if skill.runtime else None,
        })
    return result


def learning_skill_runtime_contract(skill_id: str) -> SkillRuntimeContract | None:
    skill = selectable_learning_skill(skill_id)
    return skill.runtime if skill else None


def frontend_learning_skill_manifest() -> dict[str, Any]:
    """Deterministic frontend projection generated from the registry authority."""
    return {
        "schema_version": SKILL_SPEC_VERSION,
        "registry_version": FRONTEND_SKILL_MANIFEST_REGISTRY_VERSION,
        "generated_from": "backend/app/services/architecture_registry.py",
        "skills": {
            item["id"]: item
            for item in selectable_learning_skill_manifest()
        },
    }


def chat_mode_manifest() -> list[dict[str, Any]]:
    """Return the four coarse Tutor postures shown by Chat workbenches."""
    return [asdict(item) for item in CHAT_MODES.values()]


def tool_manifest(
    binding_failures: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return tool contracts with their Agent-interface role and exposure policy."""
    failures = binding_failures if binding_failures is not None else implementation_binding_failures()
    result = []
    for tool in TOOLS.values():
        row = asdict(tool)
        row.update({
            "interface_role": TOOL_INTERFACE_ROLES[tool.id],
            "model_exposure": TOOL_MODEL_EXPOSURE[tool.id],
        })
        row.update(_publication_fields("tools", tool.id, failures))
        result.append(row)
    return result


def skill_manifest(
    binding_failures: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return skills without conflating local pedagogy with multi-capability playbooks."""
    failures = binding_failures if binding_failures is not None else implementation_binding_failures()
    result = []
    for skill in SKILLS.values():
        row = asdict(skill)
        row["skill_kind"] = SKILL_KINDS[skill.id]
        row.update(_publication_fields("skills", skill.id, failures))
        result.append(row)
    return result


def workbench_manifest(
    binding_failures: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    failures = binding_failures if binding_failures is not None else implementation_binding_failures()
    result = []
    for workbench in WORKBENCHES.values():
        row = asdict(workbench)
        row.update(_publication_fields("workbenches", workbench.id, failures))
        result.append(row)
    return result


def event_manifest(
    binding_failures: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    failures = binding_failures if binding_failures is not None else implementation_binding_failures()
    result = []
    for event in EVENTS.values():
        row = asdict(event)
        row.update(_publication_fields("events", event.id, failures))
        result.append(row)
    return result


def host_interface_manifest(
    binding_failures: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    failures = binding_failures if binding_failures is not None else implementation_binding_failures()
    result = []
    for interface in HOST_INTERFACES.values():
        row = asdict(interface)
        row.update(_publication_fields("host_interfaces", interface.id, failures))
        result.append(row)
    return result


def plugin_contract_manifest(
    binding_failures: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    failures = binding_failures if binding_failures is not None else implementation_binding_failures()
    result = []
    for contract in PLUGIN_CONTRACTS.values():
        row = asdict(contract)
        row["namespace"] = f"plugin:{contract.id}"
        row.update(_publication_fields("plugins", contract.id, failures))
        result.append(row)
    return result


def selectable_learning_skill(skill_id: str | None) -> SkillContract | None:
    skill = SKILLS.get(str(skill_id or "").strip())
    return skill if skill and skill.learner_selectable else None


def detect_learning_skill(message: str) -> SkillContract | None:
    """Resolve only explicit natural-language requests to switch teaching method."""
    normalized = "".join(str(message or "").lower().split())
    if not any(marker in normalized for marker in ("用", "切换", "选择", "换成", "按照")):
        return None
    for skill in SKILLS.values():
        if skill.learner_selectable and any(
            "".join(alias.lower().split()) in normalized for alias in skill.aliases
        ):
            return skill
    return None


def _plugin_contract_manifest_issues(contract: PluginContract) -> list[str]:
    path = _REPOSITORY_ROOT / contract.manifest_path
    if not path.is_file():
        return [f"plugin contract manifest is missing: {contract.id}"]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"plugin contract manifest is unreadable: {contract.id}: {exc}"]
    if not isinstance(manifest, dict):
        return [f"plugin contract manifest must be an object: {contract.id}"]
    errors = [
        f"plugin contract projection invalid: {contract.id}: {issue}"
        for issue in validate_plugin_manifest_projection(manifest)
    ]
    actual = {
        "package_protocol": str(manifest.get("protocol") or ""),
        "id": str(manifest.get("plugin_id") or ""),
        "release_version": str(manifest.get("version") or ""),
        "owner_agent": str(manifest.get("owner") or ""),
        "scope": str(manifest.get("scope") or ""),
        "object_types": tuple(str(item) for item in manifest.get("object_types", [])),
        "host_interfaces": tuple(str(item) for item in manifest.get("host_ports", [])),
        "workflows": tuple(_plugin_local_ids(manifest, "workflows")),
        "tools": tuple(_plugin_local_ids(manifest, "tools")),
        "skills": tuple(_plugin_local_ids(manifest, "skills")),
        "surface_slots": tuple(
            str(item.get("slot") or "")
            for item in _plugin_manifest_items(manifest, "surfaces")
        ),
        "events": tuple(_plugin_local_ids(manifest, "events")),
        "kernel_allow_list": tuple(str(item) for item in manifest.get("kernel_allow_list", [])),
    }
    expected = {
        field: getattr(contract, field)
        for field in actual
    }
    for field, expected_value in expected.items():
        if actual[field] != expected_value:
            errors.append(f"plugin contract differs from manifest: {contract.id}:{field}")
    return errors


def validate_registry() -> list[str]:
    errors: list[str] = []
    if len(AGENTS) != 3:
        errors.append("exactly three primary agent contracts are required")
    if tuple(CHAT_MODES) != ("free", "explain", "learn", "plan"):
        errors.append("chat mode registry must preserve the four coarse Tutor modes")
    for mode in CHAT_MODES.values():
        if mode.owner_agent not in AGENTS or set(mode.skills) - set(SKILLS):
            errors.append(f"invalid chat mode contract: {mode.id}")
    if tuple(KERNELS) != KERNEL_NAMES:
        errors.append("kernel registry must preserve the canonical five-kernel order")
    for capability in ACTION_BOARD:
        if capability not in CAPABILITY_OWNERS:
            errors.append(f"capability has no owner binding: {capability}")
    for capability, (agent, tool, workbench) in CAPABILITY_OWNERS.items():
        if capability not in ACTION_BOARD:
            errors.append(f"owner binding references unknown capability: {capability}")
        if agent not in AGENTS or tool not in TOOLS or workbench not in WORKBENCHES:
            errors.append(f"invalid capability binding: {capability}")
    direct_writers = {tool.id for tool in TOOLS.values() if tool.writes_kernels}
    if direct_writers != {"five_kernel_reducer"}:
        errors.append("five_kernel_reducer must be the only direct KernelState writer")
    if set(TOOL_INTERFACE_ROLES) != set(TOOLS):
        errors.append("every tool contract must have exactly one interface role")
    if set(TOOL_MODEL_EXPOSURE) != set(TOOLS):
        errors.append("every tool contract must have a model exposure policy")
    if any(
        exposure == "vnext_native" and TOOL_INTERFACE_ROLES[tool_id] != "aci_tool"
        for tool_id, exposure in TOOL_MODEL_EXPOSURE.items()
    ):
        errors.append("only ACI tools may be exposed as native model tools")
    if any(
        TOOL_INTERFACE_ROLES.get(tool_id) != "aci_tool"
        or TOOL_MODEL_EXPOSURE.get(tool_id) != "vnext_native"
        for tool_id in ("discover_project_plugin_tools", "call_project_plugin_tool")
    ):
        errors.append("generic plugin discovery and call tools must be model-visible ACI tools")
    if any(
        TOOL_MODEL_EXPOSURE.get(tool_id) != "not_model_callable"
        for tool_id in (
            "role_capability_package_runtime", "role_capability_graph_reader",
            "role_capability_explainer", "role_capability_iteration_runtime",
        )
    ):
        errors.append("legacy role capability tools must not be model callable")
    if set(SKILL_KINDS) != set(SKILLS):
        errors.append("every skill contract must have exactly one skill kind")
    publication_items = {
        "tools": set(TOOLS),
        "skills": set(SKILLS),
        "workbenches": set(WORKBENCHES),
        "capabilities": set(ACTION_BOARD),
        "events": set(EVENTS),
        "host_interfaces": set(HOST_INTERFACES),
        "plugins": set(PLUGIN_CONTRACTS),
    }
    if set(PUBLICATIONS) != set(publication_items):
        errors.append(
            "publication registry must cover tools, skills, workbenches, capabilities, "
            "events, Host Interfaces and plugins"
        )
    for category, expected_ids in publication_items.items():
        publications = PUBLICATIONS.get(category, {})
        if set(publications) != expected_ids:
            errors.append(f"publication registry does not exactly cover {category}")
        for item_id, publication in publications.items():
            if publication.lifecycle not in LIFECYCLE_STATES:
                errors.append(f"invalid publication lifecycle: {category}:{item_id}")
            if publication.lifecycle == "implemented" and not publication.bindings:
                errors.append(f"implemented publication lacks binding: {category}:{item_id}")
            if publication.lifecycle != "implemented" and not publication.note:
                errors.append(f"non-implemented publication lacks lifecycle note: {category}:{item_id}")
            for binding_id in publication.bindings:
                if binding_id not in IMPLEMENTATION_BINDINGS:
                    errors.append(
                        f"publication references unknown implementation binding: "
                        f"{category}:{item_id}:{binding_id}"
                    )
    binding_requirements = {
        "python_symbol": ("module", "symbol"),
        "python_collection_member": ("module", "symbol", "member"),
        "api_route": ("module", "symbol", "method", "route", "endpoint"),
        "frontend_handler": ("path", "symbol"),
        "frontend_component": ("path", "symbol"),
        "repository_file": ("path",),
        "reducer_event": ("module", "symbol", "member"),
    }
    for binding_id, binding in IMPLEMENTATION_BINDINGS.items():
        if binding.id != binding_id:
            errors.append(f"implementation binding key/id mismatch: {binding_id}")
        requirements = binding_requirements.get(binding.kind)
        if requirements is None:
            errors.append(f"invalid implementation binding kind: {binding_id}:{binding.kind}")
            continue
        if any(not getattr(binding, field) for field in requirements):
            errors.append(f"implementation binding lacks required fields: {binding_id}")
    for event in EVENTS.values():
        if event.owner_agent not in AGENTS or event.capability not in ACTION_BOARD:
            errors.append(f"invalid event owner/capability: {event.id}")
        if event.tool not in TOOLS or event.workbench not in WORKBENCHES:
            errors.append(f"invalid event tool/workbench: {event.id}")
        if set(event.kernel_targets) - set(KERNEL_NAMES):
            errors.append(f"invalid event kernel target: {event.id}")
        publication = EVENT_PUBLICATIONS[event.id]
        if publication.lifecycle != CAPABILITY_PUBLICATIONS[event.capability].lifecycle:
            errors.append(f"event lifecycle differs from capability lifecycle: {event.id}")
        if event.kernel_targets:
            if event.payload_version != EVENT_SCHEMA_VERSION:
                errors.append(f"targeted event lacks current payload version: {event.id}")
            if not event.reducer_binding:
                errors.append(f"targeted event lacks reducer binding: {event.id}")
            else:
                reducer_binding = IMPLEMENTATION_BINDINGS.get(event.reducer_binding)
                if (
                    not reducer_binding
                    or reducer_binding.kind != "reducer_event"
                    or reducer_binding.member != event.id
                ):
                    errors.append(f"invalid reducer binding for targeted event: {event.id}")
                if event.reducer_binding not in publication.bindings:
                    errors.append(f"event publication omits reducer binding: {event.id}")
        elif event.payload_version or event.reducer_binding:
            errors.append(f"zero-target event must not declare a reducer binding: {event.id}")
    for interface_id, interface in HOST_INTERFACES.items():
        if interface.id != interface_id:
            errors.append(f"Host Interface key/id mismatch: {interface_id}")
        if interface.mode not in {"read", "host_mediated", "proposal", "event_gateway"}:
            errors.append(f"invalid Host Interface mode: {interface_id}")
        if not interface.write_boundary:
            errors.append(f"Host Interface lacks write boundary: {interface_id}")
    for plugin_id, contract in PLUGIN_CONTRACTS.items():
        if contract.id != plugin_id:
            errors.append(f"plugin contract key/id mismatch: {plugin_id}")
        if contract.package_protocol != PLUGIN_PACKAGE_PROTOCOL:
            errors.append(f"plugin contract uses unknown package protocol: {plugin_id}")
        if contract.owner_agent not in AGENTS or contract.scope != "project":
            errors.append(f"invalid plugin owner or scope: {plugin_id}")
        if set(contract.host_interfaces) - set(HOST_INTERFACES):
            errors.append(f"plugin contract references unknown Host Interfaces: {plugin_id}")
        if set(contract.kernel_allow_list) - set(KERNEL_NAMES):
            errors.append(f"plugin contract references unknown Kernels: {plugin_id}")
        errors.extend(_plugin_contract_manifest_issues(contract))
    for workbench in WORKBENCHES.values():
        if set(workbench.capabilities) - set(ACTION_BOARD):
            errors.append(f"workbench references unknown capability: {workbench.id}")
    for skill in SKILLS.values():
        if skill.owner_agent not in AGENTS or set(skill.tools) - set(TOOLS):
            errors.append(f"invalid skill contract: {skill.id}")
        kind = SKILL_KINDS.get(skill.id)
        if skill.learner_selectable and kind != "pedagogical_method":
            errors.append(f"learner-selectable skill must be a pedagogical method: {skill.id}")
        if skill.learner_selectable:
            runtime = skill.runtime
            if not runtime or runtime.version != "atomic-learning-skill-runtime-v6":
                errors.append(f"learner-selectable skill lacks atomic runtime: {skill.id}")
                continue
            requirements = dict(runtime.knowledge_requirements or {})
            if not requirements.get("required_slots") or not requirements.get("formal_publish_requires_packet"):
                errors.append(f"learner-selectable skill lacks knowledge requirements: {skill.id}")
            if not 0 < float(requirements.get("minimum_coverage") or 0) <= 1:
                errors.append(f"invalid skill knowledge coverage: {skill.id}")
            state_ids = [state.id for state in runtime.states]
            if len(state_ids) != len(set(state_ids)) or runtime.initial_state not in state_ids:
                errors.append(f"invalid skill state graph: {skill.id}")
            if not state_ids or state_ids[-1] != "verification_ready":
                errors.append(f"skill must end in verification_ready: {skill.id}")
            if set(runtime.bound_chat_modes) - set(CHAT_MODES):
                errors.append(f"skill binds unknown chat mode: {skill.id}")
            if set(runtime.allowed_event_types) - set(EVENTS):
                errors.append(f"skill references unknown event: {skill.id}")
            if runtime.turn_budget < max(1, len(runtime.states) - 1):
                errors.append(f"skill turn budget cannot be shorter than valid transitions: {skill.id}")
            for axis in runtime.calibration_axes:
                option_ids = [option[0] for option in axis.options]
                if len(option_ids) != len(set(option_ids)) or axis.default not in option_ids:
                    errors.append(f"invalid skill calibration axis: {skill.id}:{axis.id}")
    return errors


def validate_implementation(
    binding_failures: dict[str, str] | None = None,
) -> list[str]:
    """Resolve implementation bindings independently from registry schema checks."""
    failures = binding_failures if binding_failures is not None else implementation_binding_failures()
    errors: list[str] = []
    missing_reducer_export = [
        binding_id
        for binding_id, failure in failures.items()
        if (
            IMPLEMENTATION_BINDINGS[binding_id].kind == "reducer_event"
            and "has no attribute 'REDUCER_EVENT_TYPES'" in failure
        )
    ]
    if missing_reducer_export:
        event_ids = {
            IMPLEMENTATION_BINDINGS[binding_id].member
            for binding_id in missing_reducer_export
        }
        examples = [
            event_id
            for event_id in ("project_proposal_accepted", "project_completed")
            if event_id in event_ids
        ]
        suffix = f" (including {', '.join(examples)})" if examples else ""
        errors.append(
            "app.services.learning_runtime does not export REDUCER_EVENT_TYPES; "
            f"cannot verify reducer handlers for {len(event_ids)} targeted events{suffix}"
        )
    skipped = set(missing_reducer_export)
    for binding_id, failure in sorted(failures.items()):
        if binding_id not in skipped:
            errors.append(f"{binding_id}: {failure}")
    return errors


def registry_validation_report(
    binding_failures: dict[str, str] | None = None,
) -> dict[str, Any]:
    schema_issues = validate_registry()
    implementation_issues = validate_implementation(binding_failures)
    issues = [*schema_issues, *implementation_issues]
    return {
        "schema_valid": not schema_issues,
        "implementation_valid": not implementation_issues,
        "valid": not issues,
        "schema_issues": schema_issues,
        "implementation_issues": implementation_issues,
        "issues": issues,
        # Backward-compatible alias used by existing demo and validation clients.
        "errors": issues,
    }


def normalize_event_provenance(
    event_type: str,
    source: str,
    provenance: dict[str, Any] | None,
) -> dict[str, Any]:
    result = dict(provenance or {})
    contract = EVENTS.get(event_type)
    result.update({
        "event_schema": EVENT_SCHEMA_VERSION,
        "architecture_registry": REGISTRY_VERSION,
        "contract_id": contract.id if contract else f"unclassified:{event_type}",
        "source_system": source,
    })
    if contract:
        result.update({
            "owner_agent": contract.owner_agent,
            "capability": contract.capability,
            "tool": contract.tool,
            "workbench": contract.workbench,
            "kernel_targets": list(contract.kernel_targets),
            "evidence_role": contract.evidence_role,
        })
    return result


def registry_manifest() -> dict[str, Any]:
    binding_failures = implementation_binding_failures()
    validation = registry_validation_report(binding_failures)
    capabilities = capability_manifest(binding_failures)
    payload = {
        "version": REGISTRY_VERSION,
        "event_schema": EVENT_SCHEMA_VERSION,
        "lifecycle_states": list(LIFECYCLE_STATES),
        "authority": {
            "kernel_source_of_truth": "EvidenceEvent ledger",
            "kernel_write_path": "EvidenceEvent -> five_kernel_reducer -> KernelMutation",
            "memory_projection": "KernelMutation -> MemoryFact -> versioned MemoryModule -> MemoryClaim",
            "module_versioning": "immutable snapshots; evidence closure + delta facts; REFINES/SUPERSEDES; one active version",
            "memory_consolidation": "enabled async worker; startup queue reconciliation; deterministic offline/provider-failure fallback",
            "context_read_path": "ContextPolicy -> KernelHead + scoped Memory Graph -> ContextPacket",
            "external_workflow_role": "optional content adapter; never strategy or kernel authority",
            "plugin_host_authority": "Agent Package -> project-scoped instance -> immutable snapshot -> indexed PluginObjectRef; deterministic host alone grants ports, validates candidates and commits successors",
            "plugin_execution_boundary": "official product plugins run as in-process Agent Packages; optional third-party trusted_signed_process remains operator-enabled and explicitly has no filesystem/network/secrets/CPU/memory isolation",
            "plugin_state_boundary": "external plugin events are namespaced and zero-target; core changes are Action Board proposals; no plugin receives a Kernel or ORM write interface",
            "learning_task_projection": "task lifecycle is operational; phases advance only from managed artifacts, scoped attempts and review schedules",
            "teaching_delivery_projection": "DomainBrief -> versioned SourceVersion evidence -> DomainKnowledgePacket -> TeachingContentBrief -> lecture/practice; formal publication blocks on critical knowledge gaps while learner Knowledge remains a separate answer-free design hint",
            "domain_knowledge_authority": "Source identity + immutable SourceVersion/Chunk history -> scoped DomainKnowledgePacket; this source-truth plane is read-only to learner kernels and cannot imply mastery",
            "chat_mode_authority": "deterministic Tutor posture in AgentSession context; never a fourth Agent or mastery source",
            "learning_action_projection": "completed non-free chat segment -> registered EvidenceEvent -> reducer -> scoped Memory Graph facts",
            "interactive_model_latency": "wall-clock budgets with deterministic fallback; one shared Tutor deadline across structured and plain attempts",
            "vnext_learning_task_projection": "browser interaction -> formal AgentSession + LearningSkillRun + linked LearningTask; browser cache is projection/offline fallback and lifecycle never mastery evidence",
            "vnext_learning_substate_projection": "guided_learning main state -> bound learning skill -> formal LearningSkillRun state; browser events only mirror the formal state or serve explicit offline fallback",
            "vnext_learning_graph_alignment": "official course graph + personal course overlay + personal concept graph + source knowledge domains + confirmed path plan are joined only by explicit non-mastery alignment records",
            "vnext_learning_plan_projection": "planning intent -> proposal -> explicit learner decision; accepted Value changes enter the formal EvidenceEvent reducer",
            "vnext_learning_path_projection": "versioned official course DAG + formal learner overlay events -> Structure/Value reference projection; Knowledge only records self-reported exposure and never mastery",
            "vnext_learning_path_retrieval": "exact id/title/alias lookup -> conditional deterministic fuzzy rank fusion -> ambiguity clarification or structured-evidence personal-node proposal; model-supplied URLs are rejected and proposal remains zero-target until learner confirmation",
            "vnext_agent_turn_runtime": "typed ContextEnvelope -> bounded model/tool loop -> deterministic final-state verifier -> structured AgentTurnTrace; model receives only registered read/artifact ACI tools",
            "vnext_chat_session_authority": "learner-owned AgentSession + idempotent AgentMessage are the cross-browser ordinary-chat authority; localStorage keeps drafts, tabs and paper layout only; persistence never implies learning evidence",
            "frontend_authority": "frontend/ is the only product frontend; former vNext stable IDs remain compatibility identifiers, not a second runtime; web and Tauri use the same build and formal API contracts",
            "tool_ontology": "ACI tools are Agent-callable affordances; harness, projection, policy and adapter objects are service-side infrastructure",
            "skill_ontology": "pedagogical methods define local teaching transitions; playbooks compose capabilities; coordination skills manage handoff",
            "skill_spec_authority": "SkillSpec v3 with knowledge_requirements in architecture_registry.py -> backend runtime + generated frontend manifest; no handwritten frontend workflow copy",
            "assessment_design_authority": "AssessmentBlueprint + Rubric are versioned learner-scoped proposals; generation is zero-target and deterministic grading remains Practice Agent authority",
        },
        "agents": [asdict(item) for item in AGENTS.values()],
        "chat_modes": [asdict(item) for item in CHAT_MODES.values()],
        "kernels": [asdict(item) for item in KERNELS.values()],
        "host_interfaces": host_interface_manifest(binding_failures),
        "plugins": plugin_contract_manifest(binding_failures),
        "capabilities": capabilities,
        "available_capabilities": [
            item["capability"] for item in capabilities if item["available"]
        ],
        "tools": tool_manifest(binding_failures),
        "skills": skill_manifest(binding_failures),
        "workbenches": workbench_manifest(binding_failures),
        "important_events": event_manifest(binding_failures),
        "implementation_bindings": [
            {
                **asdict(binding),
                "valid": binding_id not in binding_failures,
                "issue": binding_failures.get(binding_id),
            }
            for binding_id, binding in sorted(IMPLEMENTATION_BINDINGS.items())
        ],
        "schema_valid": validation["schema_valid"],
        "implementation_valid": validation["implementation_valid"],
        "valid": validation["valid"],
        "schema_issues": validation["schema_issues"],
        "implementation_issues": validation["implementation_issues"],
        "issues": validation["issues"],
        "errors": validation["errors"],
        # Backward-compatible alias retained for registry consumers.
        "validation_errors": validation["issues"],
    }
    digest_input = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["digest"] = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return payload
