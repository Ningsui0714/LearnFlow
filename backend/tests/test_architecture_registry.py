from app.services.action_board import ACTION_BOARD
from app.services.architecture_registry import (
    AGENTS,
    CAPABILITY_OWNERS,
    EVENTS,
    KERNEL_NAMES,
    SKILLS,
    TOOLS,
    WORKBENCHES,
    normalize_event_provenance,
    registry_manifest,
    selectable_learning_skill_manifest,
    validate_registry,
)


def test_registry_has_three_agents_five_kernels_and_no_drift():
    assert len(AGENTS) == 3
    assert KERNEL_NAMES == ("structure", "knowledge", "human", "value", "practice")
    assert set(ACTION_BOARD) == set(CAPABILITY_OWNERS)
    assert validate_registry() == []
    manifest = registry_manifest()
    assert manifest["validation_errors"] == []
    assert len(manifest["digest"]) == 64
    assert manifest["authority"]["memory_projection"] == (
        "KernelMutation -> MemoryFact -> versioned MemoryModule -> MemoryClaim"
    )
    assert "one active version" in manifest["authority"]["module_versioning"]
    assert "startup queue reconciliation" in manifest["authority"]["memory_consolidation"]


def test_remediation_events_have_standard_authority_provenance():
    expected = {
        "remediation_started",
        "remediation_mode_rejected",
        "remediation_explanation_requested",
        "remediation_retry_evaluated",
        "remediation_variant_evaluated",
        "remediation_completed",
    }
    assert expected <= set(EVENTS)
    provenance = normalize_event_provenance(
        "remediation_completed", "assessment", {"provider": "local"},
    )
    assert provenance["owner_agent"] == "practice_agent"
    assert provenance["tool"] == "deterministic_assessment"
    assert provenance["kernel_targets"] == ["knowledge", "human", "practice"]
    assert provenance["provider"] == "local"


def test_background_task_events_are_registered_with_their_actual_authority():
    assert {"source_processed", "assessment_generated", "task_completed", "task_failed"} <= set(EVENTS)
    assert normalize_event_provenance("source_processed", "task", {})["kernel_targets"] == [
        "structure", "practice",
    ]
    assert normalize_event_provenance("assessment_generated", "task", {})["kernel_targets"] == []
    failure = normalize_event_provenance("task_failed", "task", {})
    assert failure["tool"] == "task_runtime"
    assert failure["kernel_targets"] == ["structure"]


def test_review_workbench_is_registered_without_new_kernel_writer():
    assert "review" in WORKBENCHES
    assert "spaced_review" in SKILLS
    assert "review_scheduler" in TOOLS
    assert {
        "plan_review_queue", "evaluate_review_attempt", "manage_review_item",
    } <= set(ACTION_BOARD)
    assert CAPABILITY_OWNERS["plan_review_queue"][0] == "tutor_agent"
    assert CAPABILITY_OWNERS["evaluate_review_attempt"][0] == "practice_agent"
    assert EVENTS["review_attempt_evaluated"].kernel_targets == (
        "knowledge", "practice",
    )
    for event_type in {
        "review_item_skipped", "review_item_deferred",
        "review_item_suspended", "review_item_resumed",
    }:
        assert EVENTS[event_type].kernel_targets == ()
    assert {
        tool.id for tool in TOOLS.values() if tool.writes_kernels
    } == {"five_kernel_reducer"}


def test_focused_micro_learning_reuses_existing_agent_and_evidence_authority():
    assert "focused_learning" in WORKBENCHES
    assert {"verified_micro_learning", "feynman_teach_back"} <= set(SKILLS)
    assert {"micro_learning_orchestrator", "teach_back_analyzer"} <= set(TOOLS)
    assert {
        "start_micro_learning", "continue_micro_learning", "analyze_teach_back",
    } <= set(ACTION_BOARD)
    assert CAPABILITY_OWNERS["start_micro_learning"][0] == "tutor_agent"
    assert CAPABILITY_OWNERS["analyze_teach_back"][0] == "practice_agent"
    assert EVENTS["teach_back_analyzed"].kernel_targets == ("knowledge", "practice")
    assert EVENTS["micro_learning_completed"].kernel_targets == ()
    assert len(AGENTS) == 3
    assert {
        tool.id for tool in TOOLS.values() if tool.writes_kernels
    } == {"five_kernel_reducer"}


def test_conversational_learning_skills_are_registered_without_mastery_side_effects():
    assert {
        "guided_explanation", "socratic_dialogue", "feynman_dialogue",
    } == {item["id"] for item in selectable_learning_skill_manifest()}
    assert "use_learning_skill" in ACTION_BOARD
    assert CAPABILITY_OWNERS["use_learning_skill"] == (
        "tutor_agent", "tutor_context", "global_tutor",
    )
    assert EVENTS["learning_skill_selected"].kernel_targets == ()
    assert WORKBENCHES["global_tutor"].surface == "/agent/:sessionId"
    assert "use_learning_skill" in WORKBENCHES["global_tutor"].capabilities
    assert len(AGENTS) == 3


def test_learner_growth_is_an_additive_read_only_workbench():
    growth = WORKBENCHES["learner_growth"]
    assert growth.surface == "/growth"
    assert growth.owner_agent == "tutor_agent"
    assert growth.capabilities == ()
    assert {"profile", "memory"} <= set(WORKBENCHES)
    assert {
        tool.id for tool in TOOLS.values() if tool.writes_kernels
    } == {"five_kernel_reducer"}
