"""Executable architecture authority for LearnFlow.

This registry is deliberately boring: it does not route requests or let an
LLM select policy. It defines ownership and contracts so agents, tools,
workbenches and evidence events can be inspected and checked for drift.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from app.services.action_board import ACTION_BOARD


REGISTRY_VERSION = "2026-08-27.2"
EVENT_SCHEMA_VERSION = "learnflow.evidence.v1"
KERNEL_NAMES = ("structure", "knowledge", "human", "value", "practice")

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
        "pace_preference", "format_preference", "support_need",
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


TOOLS = {
    item.id: item for item in (
        ToolContract("action_board", "Action Board", "tutor_agent", "learnflow", "transaction",
                     KERNEL_NAMES, (), "EvidenceEvent"),
        ToolContract("tutor_context", "Tutor Context Assembler", "tutor_agent", "learnflow", "read",
                     KERNEL_NAMES),
        ToolContract("chat_mode_runtime", "Deterministic Chat Mode Runtime", "tutor_agent", "learnflow", "orchestration",
                     KERNEL_NAMES, (), "AgentSession context + registered EvidenceEvent only"),
        ToolContract("vnext_agent_turn_runtime", "vNext Bounded Agent Turn Graph", "tutor_agent", "vnext", "orchestration",
                     KERNEL_NAMES, (), "typed ContextEnvelope -> bounded observe/act/observe loop -> structured AgentTurnTrace; read-only model tools and no direct learner-state write"),
        ToolContract("vnext_chat_session_store", "vNext Cross-browser Chat Session Store", "tutor_agent", "vnext", "adapter",
                     (), (), "learner-owned AgentSession + idempotent AgentMessage projection; browser cache is non-authoritative and persistence creates no learning evidence"),
        ToolContract("computer_knowledge_search", "Explanation-oriented Computer Knowledge Search", "learning_design_agent", "vnext", "read",
                     (), (), "intent/facet plan -> tiered source adapters -> deterministic rerank -> bounded untrusted evidence bundle"),
        ToolContract("safe_visual_generation", "Safe Learning Visual Generator", "learning_design_agent", "vnext", "artifact",
                     (), (), "validated graph plan -> sanitized static SVG or deterministic SVG frames"),
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
        ToolContract("project_learning_file_proposer", "Project Learning File Generation Proposal Tool", "learning_design_agent", "vnext", "proposal",
                     ("knowledge", "human"), (), "checkpoint LearningTask + available sources -> lecture/practice generation proposal; user-triggered materialization and no mastery inference"),
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
        ToolContract("code_executor", "Sandboxed Code Executor", "practice_agent", "learnflow", "assessment"),
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
        "action_board", "computer_knowledge_search", "safe_visual_generation",
        "vnext_five_kernel_profile_reader", "vnext_learning_workspace_reader", "vnext_learning_path_exact_reader", "vnext_learning_path_fuzzy_reader", "vnext_personal_path_node_proposer", "domain_knowledge_reader",
        "review_context_reader", "review_reflection_gateway",
        "vnext_learning_path_planner", "vnext_learning_path_plan_manager",
        "personal_concept_graph_reader", "concept_self_report_gateway",
        "vnext_personal_path_node_runtime", "learner_memory_manager",
        "vnext_five_kernel_explicit_editor", "workspace_lifecycle", "source_ingestion",
        "repository_knowledge_domains", "hierarchical_rag", "content_generation",
        "teach_back_analyzer", "process_animation", "code_executor",
        "deterministic_assessment", "evidence_ledger", "five_kernel_retriever",
        "workspace_file_service", "managed_artifact_service", "learning_file_service", "local_agent_broker",
        "dynamic_practice_generator", "similar_practice_generator", "practice_quality_inspector",
        "project_workspace_reader", "project_source_reader", "project_learning_file_reader",
        "project_roadmap_reader", "project_roadmap_proposer", "project_learning_file_proposer",
    }},
    **{tool_id: "harness" for tool_id in {
        "tutor_context", "chat_mode_runtime", "vnext_agent_turn_runtime", "vnext_learning_path_graph_reader",
        "selection_followup_context", "vnext_learning_task_runtime",
        "vnext_learning_plan_runtime", "micro_learning_orchestrator",
        "learning_skill_runtime", "learning_task_runtime", "learning_task_planner",
        "checkpoint_context", "context_packet_assembler", "task_runtime", "seeded_demo",
    }},
    **{tool_id: "projection" for tool_id in {
        "review_scheduler", "review_proficiency_projector", "five_kernel_reducer", "memory_graph", "kernel_head_projector",
    }},
    "deterministic_remediation": "policy",
    "vnext_chat_session_store": "adapter",
    "workflow_gateway": "adapter",
    "workflow_validator": "adapter",
}

# Exposure is intentionally narrower than the ACI catalog. vNext currently gives
# the model five read/artifact capabilities; proposal and write tools stay behind
# deterministic orchestration and explicit learner confirmation.
TOOL_MODEL_EXPOSURE = {
    tool_id: (
        "vnext_native"
        if tool_id in {
            "computer_knowledge_search", "safe_visual_generation",
            "vnext_five_kernel_profile_reader", "vnext_learning_workspace_reader", "vnext_learning_path_exact_reader", "vnext_learning_path_fuzzy_reader", "vnext_personal_path_node_proposer", "domain_knowledge_reader",
            "review_context_reader", "project_workspace_reader", "project_source_reader",
            "project_learning_file_reader", "project_roadmap_reader", "project_roadmap_proposer", "project_learning_file_proposer",
            "dynamic_practice_generator", "similar_practice_generator", "practice_quality_inspector",
        }
        else "agent_mediated"
        if TOOL_INTERFACE_ROLES.get(tool_id) == "aci_tool"
        else "not_model_callable"
    )
    for tool_id in TOOLS
}


SKILLS = {
    item.id: item for item in (
        SkillContract("intent_and_handoff", "意图理解与跨空间交接", "tutor_agent",
                      ("tutor_context", "action_board", "evidence_ledger"),
                      "structured intent + auditable action/handoff", "Action Board"),
        SkillContract(
            "guided_explanation", "清晰讲解", "tutor_agent",
            ("tutor_context", "context_packet_assembler", "learning_skill_runtime",
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
        ),
        SkillContract(
            "socratic_dialogue", "苏格拉底追问", "tutor_agent",
            ("tutor_context", "context_packet_assembler", "learning_skill_runtime",
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
        ),
        SkillContract(
            "feynman_dialogue", "费曼复述", "tutor_agent",
            ("tutor_context", "context_packet_assembler", "learning_skill_runtime",
             "learning_task_runtime", "learning_task_planner", "micro_learning_orchestrator",
             "teach_back_analyzer", "deterministic_assessment", "deterministic_remediation",
             "review_scheduler"),
            "task-linked bounded teach-back scaffold -> verified workbench handoff",
            "deterministic SkillRun + LearningTask; graded analyzer is required for evidence",
            learner_selectable=True,
            description="请你用自己的话讲一遍，再一起找出模糊处。",
            invocation_prompt=(
                "当前对话已由学习者选择“费曼复述”技能。请让学习者先用自己的话解释目标概念；"
                "收到复述后，先指出讲清楚的一点，再定位最关键的一处模糊或跳步，并只追问一个问题。"
                "普通对话反馈不能宣布掌握；需要形成学习证据时，只能建议进入已登记的可验证微学习。"
            ),
            aliases=("费曼", "费曼学习", "费曼复述"),
            best_for=("查漏补缺", "组织概念关系", "已有接触后检验能否说清"),
            avoid_when=("尚未接触主题", "程序性任务只需要先看步骤示范"),
            atomic_task_capable=True,
        ),
        SkillContract(
            "worked_example_fading", "示例渐隐", "tutor_agent",
            ("tutor_context", "context_packet_assembler", "learning_skill_runtime",
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
                      ("domain_knowledge_reader", "computer_knowledge_search",
                       "vnext_learning_path_exact_reader", "vnext_learning_path_fuzzy_reader", "source_ingestion"),
                      "goal-aligned resource proposal with coverage, authority tier, provenance and identified gaps",
                      "Skill chooses the comparison workflow; read/search tools only supply evidence"),
        SkillContract("project_apprenticeship_orchestration", "真实产物导向的项目学徒旅程", "tutor_agent",
                      ("project_workspace_reader", "project_source_reader", "project_learning_file_reader",
                       "project_roadmap_reader", "project_roadmap_proposer", "project_learning_file_proposer",
                       "learning_task_runtime", "learning_file_service", "five_kernel_retriever"),
                      "topic-locked project Tutor -> confirmed checkpoint DAG -> checkpoint LearningTasks -> managed files and evidence-safe practice",
                      "Tutor owns orchestration; Learning Design proposes; user confirms structure/artifacts; reducer alone owns five-kernel mutations"),
        SkillContract("evidence_grounded_teaching", "有来源的讲义与概念教学", "learning_design_agent",
                      ("hierarchical_rag", "content_generation", "process_animation"),
                      "structured teaching artifact; never mastery evidence", "artifact contract"),
        SkillContract("practice_verification", "代码实践与确定性验证", "practice_agent",
                      ("code_executor", "deterministic_assessment", "evidence_ledger"),
                      "graded LearningAttempt + evidence", "test/grading rules"),
        SkillContract(
            "dynamic_practice_loop", "动态练习与检测编排", "tutor_agent",
            ("dynamic_practice_generator", "similar_practice_generator",
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
            "worked_example_fading", "feynman_teach_back",
        }
        else "coordination_skill"
        if skill_id in {"intent_and_handoff", "checkpoint_tutoring"}
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
                          ("coordinate_vnext_agent_turn", "search_computer_knowledge", "generate_learning_visual", "open_selection_followup",
                           "run_vnext_learning_task", "run_vnext_learning_plan", "read_vnext_five_kernel_profile",
                           "read_vnext_learning_workspace",
                           "manage_domain_knowledge_sources", "read_domain_knowledge", "recommend_learning_resources",
                           "attach_learning_file_to_chat", "generate_dynamic_practice", "generate_similar_practice", "inspect_practice_quality",
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
                          ("generate_learning_files", "generate_dynamic_practice", "generate_similar_practice", "inspect_practice_quality", "open_learning_file", "attach_learning_file_to_chat"), "vnext"),
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
    "generate_learning_visual": ("learning_design_agent", "safe_visual_generation", "vnext_chat"),
    "open_selection_followup": ("tutor_agent", "selection_followup_context", "vnext_chat"),
    "run_vnext_learning_task": ("tutor_agent", "vnext_learning_task_runtime", "vnext_chat"),
    "run_vnext_learning_plan": ("tutor_agent", "vnext_learning_plan_runtime", "vnext_chat"),
    "read_vnext_five_kernel_profile": ("tutor_agent", "vnext_five_kernel_profile_reader", "vnext_chat"),
    "read_vnext_learning_workspace": ("tutor_agent", "vnext_learning_workspace_reader", "vnext_chat"),
    "manage_domain_knowledge_sources": ("tutor_agent", "source_ingestion", "vnext_chat"),
    "read_domain_knowledge": ("tutor_agent", "domain_knowledge_reader", "vnext_chat"),
    "recommend_learning_resources": ("learning_design_agent", "domain_knowledge_reader", "vnext_chat"),
    "generate_learning_files": ("learning_design_agent", "learning_file_service", "vnext_learning_files"),
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
                         workbench or default_workbench, targets, role, origin)


EVENTS = {
    item.id: item for item in (
        _event("chat_mode_entered", "coordinate_chat_mode", (), "operational_context"),
        _event("learning_action_segment_completed", "coordinate_chat_mode", ("structure", "knowledge", "value"), "learning_action_projection"),
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
        _event("knowledge_source_added", "manage_domain_knowledge_sources", (), "artifact_ingest", origin="vnext"),
        _event("knowledge_source_processed", "manage_domain_knowledge_sources", (), "artifact_indexed", origin="vnext"),
        _event("learning_file_generated", "generate_learning_files", (), "artifact", origin="vnext"),
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


def capability_manifest() -> list[dict[str, Any]]:
    result = []
    for capability, spec in sorted(ACTION_BOARD.items()):
        owner, tool, workbench = CAPABILITY_OWNERS.get(capability, ("unassigned", "unassigned", "unassigned"))
        row = asdict(spec)
        row.update({"owner_agent": owner, "tool": tool, "workbench": workbench})
        result.append(row)
    return result


def selectable_learning_skill_manifest() -> list[dict[str, Any]]:
    """Return the learner-facing portion of registered conversational skills."""
    return [
        {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "best_for": list(skill.best_for),
            "avoid_when": list(skill.avoid_when),
            "atomic_task_capable": skill.atomic_task_capable,
        }
        for skill in SKILLS.values()
        if skill.learner_selectable
    ]


def chat_mode_manifest() -> list[dict[str, Any]]:
    """Return the four coarse Tutor postures shown by Chat workbenches."""
    return [asdict(item) for item in CHAT_MODES.values()]


def tool_manifest() -> list[dict[str, Any]]:
    """Return tool contracts with their Agent-interface role and exposure policy."""
    result = []
    for tool in TOOLS.values():
        row = asdict(tool)
        row.update({
            "interface_role": TOOL_INTERFACE_ROLES[tool.id],
            "model_exposure": TOOL_MODEL_EXPOSURE[tool.id],
        })
        result.append(row)
    return result


def skill_manifest() -> list[dict[str, Any]]:
    """Return skills without conflating local pedagogy with multi-capability playbooks."""
    result = []
    for skill in SKILLS.values():
        row = asdict(skill)
        row["skill_kind"] = SKILL_KINDS[skill.id]
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
    if set(SKILL_KINDS) != set(SKILLS):
        errors.append("every skill contract must have exactly one skill kind")
    for event in EVENTS.values():
        if event.owner_agent not in AGENTS or event.capability not in ACTION_BOARD:
            errors.append(f"invalid event owner/capability: {event.id}")
        if event.tool not in TOOLS or event.workbench not in WORKBENCHES:
            errors.append(f"invalid event tool/workbench: {event.id}")
        if set(event.kernel_targets) - set(KERNEL_NAMES):
            errors.append(f"invalid event kernel target: {event.id}")
    for skill in SKILLS.values():
        if skill.owner_agent not in AGENTS or set(skill.tools) - set(TOOLS):
            errors.append(f"invalid skill contract: {skill.id}")
    return errors


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
    payload = {
        "version": REGISTRY_VERSION,
        "event_schema": EVENT_SCHEMA_VERSION,
        "authority": {
            "kernel_source_of_truth": "EvidenceEvent ledger",
            "kernel_write_path": "EvidenceEvent -> five_kernel_reducer -> KernelMutation",
            "memory_projection": "KernelMutation -> MemoryFact -> versioned MemoryModule -> MemoryClaim",
            "module_versioning": "immutable snapshots; evidence closure + delta facts; REFINES/SUPERSEDES; one active version",
            "memory_consolidation": "enabled async worker; startup queue reconciliation; deterministic offline/provider-failure fallback",
            "context_read_path": "ContextPolicy -> KernelHead + scoped Memory Graph -> ContextPacket",
            "external_workflow_role": "optional content adapter; never strategy or kernel authority",
            "learning_task_projection": "task lifecycle is operational; phases advance only from managed artifacts, scoped attempts and review schedules",
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
        },
        "agents": [asdict(item) for item in AGENTS.values()],
        "chat_modes": [asdict(item) for item in CHAT_MODES.values()],
        "kernels": [asdict(item) for item in KERNELS.values()],
        "capabilities": capability_manifest(),
        "tools": tool_manifest(),
        "skills": skill_manifest(),
        "workbenches": [asdict(item) for item in WORKBENCHES.values()],
        "important_events": [asdict(item) for item in EVENTS.values()],
        "validation_errors": validate_registry(),
    }
    digest_input = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["digest"] = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return payload
