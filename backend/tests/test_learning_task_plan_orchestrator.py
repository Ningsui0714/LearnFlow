from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.learning_task_plan_orchestrator import (
    build_planning_analysis,
    replan_analysis,
)


def _run() -> dict:
    run_id = "run_1234567890abcdef1234567890abcdef"
    fingerprint = "c" * 64
    packages = [
        ("wp_contract", "task_contract_compiler", [], "task_contract"),
        ("wp_evidence", "evidence_explorer", ["wp_contract"], "evidence_ledger"),
        ("wp_candidates", "candidate_planner", ["wp_contract", "wp_evidence"], "candidate_set"),
        ("wp_review", "critic_committee", ["wp_candidates"], "critic_report"),
        ("wp_publish", "artifact_publisher", ["wp_review"], "delivery_bundle"),
    ]
    return {
        "schema_version": "learning-work-task-agent-state-v1",
        "run_id": run_id,
        "phase": "PLAN_READY",
        "status": "active",
        "checkpoint_version": 2,
        "task_contract": {
            "raw_input": "部署企业园区网络并完成连通性验收",
            "input_level": "single_work_task",
            "semantic_fingerprint": fingerprint,
        },
        "plan": {
            "schema_version": "learning-work-task-plan-v1",
            "run_id": run_id,
            "plan_version": 2,
            "goal": "将企业园区网络部署任务转化为可执行、可验收的学习型工作任务。",
            "task_contract_fingerprint": fingerprint,
            "success_criteria": ["语义不变", "步骤可执行", "结果可验收"],
            "unknowns": [],
            "work_packages": [{
                "package_id": package_id,
                "agent_role": role,
                "objective": f"完成 {package_id} 对应的受控规划活动。",
                "depends_on": dependencies,
                "allowed_tools": ["task_database"],
                "expected_artifact": artifact,
                "completion_condition": f"{artifact} 已生成并通过结构校验。",
            } for package_id, role, dependencies, artifact in packages],
            "repair_budget": 2,
            "stop_conditions": ["出现安全或权限冲突时停止并请求人工确认。"],
        },
        "state": {"phase": "PLAN_READY"},
        "next_actions": ["进入证据探索"],
    }


def test_builds_hierarchy_candidates_critics_and_critical_path():
    analysis = build_planning_analysis(_run())

    assert analysis["planning_status"] == "planned_not_executed"
    assert analysis["decision"]["code"] == "SELECT_CANDIDATE"
    assert len(analysis["candidates"]) == 3
    assert len(analysis["critics"]) == 6
    assert analysis["critical_path"] == [
        "wp_contract", "wp_evidence", "wp_candidates", "wp_review", "wp_publish",
    ]
    assert analysis["metrics"]["hierarchy_nodes"] >= 20
    assert all(candidate["hard_gate_passed"] for candidate in analysis["candidates"])


def test_blocking_unknown_prevents_candidate_selection():
    run = _run()
    run["plan"]["unknowns"] = [{
        "unknown_id": "acceptance",
        "question": "现场最终采用什么连通性验收阈值？",
        "required_evidence": "official_or_upstream",
        "blocking": True,
    }]

    analysis = build_planning_analysis(run)

    assert analysis["planning_status"] == "needs_evidence"
    assert analysis["decision"]["code"] == "REQUEST_EVIDENCE"
    assert analysis["decision"]["selected_candidate_id"] is None
    assert not any(candidate["hard_gate_passed"] for candidate in analysis["candidates"])


def test_local_replan_only_changes_target_and_descendants():
    run = _run()
    analysis = build_planning_analysis(run)

    revised = replan_analysis(
        run,
        analysis,
        target_package_id="wp_candidates",
        failure_code="mapping_conflict",
        observation="知识技能映射与真实作业步骤不一致，需要局部重算。",
        expected_analysis_version=1,
    )

    revision = revised["revision_history"][-1]
    assert revised["analysis_version"] == 2
    assert revised["planning_status"] == "replanned_not_executed"
    assert revised["repair_budget_remaining"] == 1
    assert revision["affected_package_ids"] == [
        "wp_candidates", "wp_review", "wp_publish",
    ]
    assert revision["preserved_package_ids"] == ["wp_contract", "wp_evidence"]
    assert revised["decision"]["code"] == "SELECT_CANDIDATE"

    with pytest.raises(ValueError, match="版本已变化"):
        replan_analysis(
            deepcopy(run),
            revised,
            target_package_id="wp_candidates",
            failure_code="mapping_conflict",
            observation="重复提交旧版本。",
            expected_analysis_version=1,
        )
