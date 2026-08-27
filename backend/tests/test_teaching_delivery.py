from app.services.delivery_readiness import project_delivery_readiness
from app.services.teaching_contract import (
    build_fallback_section,
    ensure_teaching_sections,
    normalize_teaching_contract,
)


def test_teaching_contract_normalizes_legacy_fields_without_blocking_delivery():
    contract = normalize_teaching_contract(
        {"exit_criteria": ["能解释生成器暂停与恢复"]},
        objective="理解 Python generator",
    )
    assert contract["objective"] == "理解 Python generator"
    assert contract["outcomes"] == ["能解释生成器暂停与恢复"]
    assert contract["exit_criteria"] == contract["outcomes"]
    assert contract["teaching_gate"]["status"] == "ready_with_gaps"
    assert contract["teaching_gate"]["max_model_revisions"] == 1


def test_teaching_contract_hard_error_still_returns_answer_safe_fallback():
    contract = normalize_teaching_contract({
        "objective": "理解闭包",
        "outcomes": ["能解释自由变量"],
        "answer_leakage": True,
    })
    assert contract["teaching_gate"]["status"] == "fallback_ready"
    section = build_fallback_section(contract, checkpoint_title="闭包")
    assert section["delivery_state"] == "fallback_ready"
    assert section["mastery_inference"] is False
    assert "学习目标" in section["content"]
    assert "当前缺口" in section["content"]
    gated = ensure_teaching_sections([{"title": "unsafe", "content": "看似有效"}], contract=contract, checkpoint_title="闭包")
    assert len(gated) == 1
    assert gated[0]["delivery_state"] == "fallback_ready"


def test_delivery_readiness_is_monotonic_object_projection_not_learning_status():
    outline = project_delivery_readiness({})
    assert outline["overall"] == "outline_only"
    assert outline["mastery_inference"] is False

    content = project_delivery_readiness({
        "published_lecture_sections": 2,
        "learning_task_count": 1,
    })
    assert content["overall"] == "guided_learning_ready"

    practice = project_delivery_readiness({
        "published_lecture_sections": 2,
        "learning_task_count": 1,
        "concept_question_count": 2,
        "deterministic_answer_count": 2,
    })
    assert practice["overall"] == "practice_ready"

    verified = project_delivery_readiness({
        "processed_source_chunks": 4,
        "published_lecture_sections": 2,
        "learning_task_count": 1,
        "concept_question_count": 2,
        "deterministic_answer_count": 2,
        "active_blueprint_count": 1,
        "active_rubric_count": 1,
    })
    assert verified["overall"] == "verification_ready"
    assert verified["gaps"] == []
