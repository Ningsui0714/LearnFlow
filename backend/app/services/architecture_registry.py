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


REGISTRY_VERSION = "2026-08-24.5"
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
class KernelContract:
    id: str
    question: str
    short_term_keys: tuple[str, ...]
    long_term_rule: str
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


KERNELS = {
    item.id: item for item in (
        KernelContract("structure", "学习者走到哪里，怎样离开与返回",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["structure"])),
                       "Only stable path patterns and confirmed project structure may consolidate."),
        KernelContract("knowledge", "对哪个知识点理解到什么程度",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["knowledge"])),
                       "Mastery and misconception require graded or explicitly correctable evidence."),
        KernelContract("human", "当前怎样教更合适",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["human"])),
                       "Preferences consolidate after explicit confirmation or cross-session evidence."),
        KernelContract("value", "为什么学，什么更值得投入",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["value"])),
                       "Long-term goals require explicit learner confirmation."),
        KernelContract("practice", "能否独立做出来",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["practice"])),
                       "Independent and transfer attempts outrank assisted completion."),
    )
}


TOOLS = {
    item.id: item for item in (
        ToolContract("action_board", "Action Board", "tutor_agent", "learnflow", "transaction",
                     KERNEL_NAMES, (), "EvidenceEvent"),
        ToolContract("tutor_context", "Tutor Context Assembler", "tutor_agent", "learnflow", "read",
                     KERNEL_NAMES),
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
                "当前对话已由学习者选择“苏格拉底追问”技能。不要一开始给出完整答案；"
                "先判断学习者当前推理位置，每轮只问一个能推动思考的问题，并根据回答继续。"
                "如果学习者明确要求直接解释，应尊重选择并切换为简明说明。追问结果本身不是掌握证据。"
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
                      ("source_ingestion", "repository_knowledge_domains", "hierarchical_rag", "content_generation"),
                      "roadmap proposal with checkpoint dependencies and provenance", "confirmed proposal"),
        SkillContract("evidence_grounded_teaching", "有来源的讲义与概念教学", "learning_design_agent",
                      ("hierarchical_rag", "content_generation", "process_animation"),
                      "structured teaching artifact; never mastery evidence", "artifact contract"),
        SkillContract("practice_verification", "代码实践与确定性验证", "practice_agent",
                      ("code_executor", "deterministic_assessment", "evidence_ledger"),
                      "graded LearningAttempt + evidence", "test/grading rules"),
        SkillContract("remediation_loop", "答错—纠错—重做—变式—回写", "practice_agent",
                      ("deterministic_remediation", "deterministic_assessment", "evidence_ledger"),
                      "RemediationCase + ordered evidence chain", "RemediationStrategy", "fused"),
        SkillContract("spaced_review", "检索练习与可解释间隔复习", "practice_agent",
                      ("review_scheduler", "deterministic_assessment", "deterministic_remediation", "evidence_ledger"),
                      "QuestionLearningState + ReviewSchedule + graded review evidence",
                      "review-policy-v1"),
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


WORKBENCHES = {
    item.id: item for item in (
        WorkbenchContract("global_tutor", "Global Tutor", "/agent/:sessionId", "tutor_agent",
                          ("use_learning_skill", "start_learning_skill_run", "advance_learning_skill_run",
                           "start_skill_verification", "start_micro_learning", "search_projects",
                           "draft_learning_project", "create_project", "manage_learning_tasks",
                           "plan_learning_task", "run_learning_task")),
        WorkbenchContract("learning_tasks", "Learning Task Queue", "/tasks", "tutor_agent",
                          ("manage_learning_tasks", "plan_learning_task", "run_learning_task")),
        WorkbenchContract("focused_learning", "Focused Learning", "/learn/:runId", "tutor_agent",
                          ("continue_micro_learning", "analyze_teach_back", "evaluate_attempt",
                           "request_remediation_explanation", "retry_attempt",
                           "evaluate_transfer_variant", "plan_review_queue")),
        WorkbenchContract("project_tutor", "Project Tutor", "/projects/:projectId", "tutor_agent",
                          ("add_source", "plan_learning_path", "apply_learning_path", "navigate_checkpoint",
                           "manage_learning_tasks", "plan_learning_task", "run_learning_task")),
        WorkbenchContract("lecture", "Checkpoint Tutor · Lecture", "/projects/:projectId/checkpoints/:checkpointId", "tutor_agent",
                          ("generate_lecture", "explain_selection", "generate_assessment")),
        WorkbenchContract("assessment", "Checkpoint Tutor · Assessment", "/projects/:projectId/checkpoints/:checkpointId/exercises", "tutor_agent",
                          ("evaluate_attempt", "retry_attempt", "evaluate_transfer_variant")),
        WorkbenchContract("remediation", "Remediation Panel", "RemediationPanel", "practice_agent",
                          ("request_remediation_explanation", "retry_attempt", "evaluate_transfer_variant"), "fused"),
        WorkbenchContract("review", "Global Review Workbench", "/review", "tutor_agent",
                          ("plan_review_queue", "evaluate_review_attempt", "manage_review_item")),
        WorkbenchContract("learner_growth", "Learner Growth", "/growth", "tutor_agent", ()),
        WorkbenchContract("profile", "Learner Profile Legacy Redirect", "/profile", "tutor_agent", ()),
        WorkbenchContract("memory", "Inspectable Memory Legacy Redirect", "/memory", "tutor_agent", ()),
        WorkbenchContract("competition_demo", "Seeded Demo Entry", "/demo", "tutor_agent",
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
    "bootstrap_project": ("tutor_agent", "action_board", "global_tutor"),
    "enter_project": ("tutor_agent", "action_board", "project_tutor"),
    "add_source": ("tutor_agent", "source_ingestion", "project_tutor"),
    "plan_learning_path": ("learning_design_agent", "content_generation", "project_tutor"),
    "apply_learning_path": ("tutor_agent", "action_board", "project_tutor"),
    "navigate_checkpoint": ("tutor_agent", "action_board", "project_tutor"),
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
        _event("learning_task_created", "manage_learning_tasks", (), "operational"),
        _event("learning_task_accepted", "manage_learning_tasks", (), "confirmed_operational"),
        _event("learning_task_replanned", "plan_learning_task", (), "plan_revision"),
        _event("learning_task_started", "run_learning_task", (), "operational"),
        _event("learning_task_paused", "run_learning_task", (), "operational"),
        _event("learning_task_resumed", "run_learning_task", (), "operational"),
        _event("learning_task_phase_completed", "run_learning_task", (), "operational_milestone"),
        _event("learning_task_materialized", "run_learning_task", (), "artifact_handoff"),
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
        _event("registration_profile_completed", "draft_learning_project", ("human", "value"), "self_report"),
        _event("profile_updated", "draft_learning_project", ("human", "value"), "self_report", workbench="profile"),
        _event("career_goal_confirmed", "draft_learning_project", ("value",), "confirmed_goal", workbench="profile"),
        _event("user_message", "draft_learning_project", KERNEL_NAMES, "interaction"),
        _event("project_proposal_created", "draft_learning_project", ("structure", "value", "practice"), "proposal"),
        _event("project_proposal_revised", "revise_learning_project_proposal", KERNEL_NAMES, "proposal"),
        _event("project_proposal_user_edited", "revise_learning_project_proposal", KERNEL_NAMES, "explicit_edit"),
        _event("project_proposal_accepted", "create_project", ("structure", "value"), "confirmed_action"),
        _event("project_created", "create_project", ("structure", "value"), "action_result"),
        _event("project_selected", "enter_project", ("structure",), "navigation"),
        _event("source_added", "add_source", ("structure", "practice"), "artifact"),
        _event("source_processed", "add_source", ("structure", "practice"), "artifact"),
        _event("roadmap_discussed", "plan_learning_path", ("structure",), "proposal"),
        _event("roadmap_applied", "apply_learning_path", ("structure",), "confirmed_action"),
        _event("checkpoint_entered", "navigate_checkpoint", ("structure",), "navigation"),
        _event("lecture_generated", "generate_lecture", ("knowledge",), "exposure"),
        _event("lecture_viewed", "generate_lecture", ("knowledge",), "exposure"),
        _event("assessment_generated", "generate_assessment", (), "artifact"),
        _event("explanation_requested", "explain_selection", ("knowledge", "human"), "assistance"),
        _event("code_review_requested", "explain_selection", ("practice", "human"), "assistance", workbench="assessment"),
        _event("concept_attempt_evaluated", "evaluate_attempt", ("knowledge", "practice"), "graded_attempt"),
        _event("exercise_attempt_evaluated", "evaluate_attempt", ("knowledge", "practice"), "graded_attempt"),
        _event("remediation_started", "request_remediation_explanation", ("knowledge", "human", "practice"), "diagnosis", origin="fused"),
        _event("remediation_mode_rejected", "request_remediation_explanation", ("human", "knowledge"), "preference_evidence", origin="fused"),
        _event("remediation_explanation_requested", "request_remediation_explanation", ("human", "knowledge"), "assistance", origin="fused"),
        _event("remediation_retry_evaluated", "retry_attempt", ("knowledge", "practice"), "graded_retry", origin="fused"),
        _event("remediation_variant_evaluated", "evaluate_transfer_variant", ("knowledge", "practice"), "transfer_evidence", origin="fused"),
        _event("remediation_completed", "evaluate_transfer_variant", ("knowledge", "human", "practice"), "evidence_writeback", origin="fused"),
        _event("review_attempt_evaluated", "evaluate_review_attempt", ("knowledge", "practice"), "spaced_retrieval"),
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
            "interactive_model_latency": "wall-clock budgets with deterministic fallback; one shared Tutor deadline across structured and plain attempts",
        },
        "agents": [asdict(item) for item in AGENTS.values()],
        "kernels": [asdict(item) for item in KERNELS.values()],
        "capabilities": capability_manifest(),
        "tools": [asdict(item) for item in TOOLS.values()],
        "skills": [asdict(item) for item in SKILLS.values()],
        "workbenches": [asdict(item) for item in WORKBENCHES.values()],
        "important_events": [asdict(item) for item in EVENTS.values()],
        "validation_errors": validate_registry(),
    }
    digest_input = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["digest"] = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return payload
