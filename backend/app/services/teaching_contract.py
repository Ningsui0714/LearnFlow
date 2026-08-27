"""Deterministic teaching-contract gates for checkpoint learning artifacts.

The contract lives in ``Checkpoint.learning_contract``.  This module does not
create a second authority: it normalizes legacy fields, reports bounded gaps,
and always produces an answer-safe minimum teaching artifact when generation
cannot satisfy the contract.
"""

from __future__ import annotations

from typing import Any, Iterable


TEACHING_CONTRACT_SCHEMA = "learnflow.teaching-contract.v1"
TEACHING_GATE_POLICY = "teaching-contract-gate.v1"


def _text(value: Any, limit: int = 1600) -> str:
    return " ".join(str(value or "").split())[:limit]


def _texts(values: Any, *, limit: int = 8, item_limit: int = 500) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return list(dict.fromkeys(
        item for item in (_text(value, item_limit) for value in values[:limit]) if item
    ))


def _source_refs(values: Any) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    if values in (None, ""):
        return normalized, errors
    if not isinstance(values, list):
        return [], ["source_refs 必须是列表"]
    for index, value in enumerate(values[:20]):
        if isinstance(value, int) and value > 0:
            normalized.append({"type": "chunk", "id": value})
            continue
        if not isinstance(value, dict):
            errors.append(f"source_refs[{index}] 不是合法引用")
            continue
        ref_type = _text(value.get("type"), 40)
        ref_id = value.get("id")
        if not ref_type or not isinstance(ref_id, (int, str)) or not str(ref_id).strip():
            errors.append(f"source_refs[{index}] 缺少 type 或 id")
            continue
        normalized.append({"type": ref_type, "id": ref_id})
    return normalized, errors


def normalize_teaching_contract(
    contract: Any,
    *,
    objective: str = "",
    outcomes: Iterable[str] = (),
) -> dict[str, Any]:
    raw = dict(contract) if isinstance(contract, dict) else {}
    normalized_outcomes = _texts(raw.get("outcomes") or raw.get("exit_criteria") or list(outcomes))
    refs, ref_errors = _source_refs(raw.get("source_refs"))
    normalized = {
        **raw,
        "schema_version": TEACHING_CONTRACT_SCHEMA,
        "objective": _text(raw.get("objective") or objective, 1600),
        "outcomes": normalized_outcomes,
        "must_preserve": _texts(raw.get("must_preserve")),
        "avoid": _texts(raw.get("avoid")),
        "source_refs": refs,
    }
    # Preserve the established roadmap/task API while making the new contract
    # readable by old clients.
    normalized["exit_criteria"] = _texts(raw.get("exit_criteria") or normalized_outcomes)
    normalized["teaching_gate"] = evaluate_teaching_contract(normalized, ref_errors=ref_errors)
    return normalized


def evaluate_teaching_contract(
    contract: Any,
    *,
    ref_errors: Iterable[str] = (),
) -> dict[str, Any]:
    if not isinstance(contract, dict):
        return {
            "policy_version": TEACHING_GATE_POLICY,
            "status": "fallback_ready",
            "hard_errors": ["learning_contract 不是可解析对象"],
            "gaps": ["缺少教学目标", "缺少可检查学习结果"],
            "max_model_revisions": 1,
        }
    hard_errors = list(ref_errors)
    if contract.get("scope_violation") is True:
        hard_errors.append("教学内容越过当前关卡 scope")
    if contract.get("answer_leakage") is True:
        hard_errors.append("教学内容包含独立验证答案")
    gaps: list[str] = []
    if not _text(contract.get("objective")):
        gaps.append("缺少教学目标")
    if not _texts(contract.get("outcomes") or contract.get("exit_criteria")):
        gaps.append("缺少可检查学习结果")
    if not _texts(contract.get("must_preserve")):
        gaps.append("未声明必须保留的核心事实")
    if not contract.get("source_refs"):
        gaps.append("当前没有可定位来源")
    status = "fallback_ready" if hard_errors else "ready_with_gaps" if gaps else "ready"
    return {
        "policy_version": TEACHING_GATE_POLICY,
        "status": status,
        "hard_errors": hard_errors,
        "gaps": gaps,
        "max_model_revisions": 1,
    }


def build_fallback_section(
    contract: Any,
    *,
    checkpoint_title: str,
    failure_reason: str = "",
) -> dict[str, Any]:
    normalized = normalize_teaching_contract(contract, objective=checkpoint_title)
    objective = normalized["objective"] or f"理解并完成：{checkpoint_title}"
    outcomes = normalized["outcomes"] or normalized["exit_criteria"]
    preserved = normalized["must_preserve"]
    core_fact = preserved[0] if preserved else (
        outcomes[0] if outcomes else f"先明确“{checkpoint_title}”的输入、关键过程与可检查输出。"
    )
    gap = _text(failure_reason, 500) or "当前生成内容不足，已切换到确定性最小讲解。"
    next_action = outcomes[0] if outcomes else "用自己的话写出目标、输入和预期输出，再进入正式练习。"
    content = (
        f"## 学习目标\n\n{objective}\n\n"
        f"## 核心事实\n\n{core_fact}\n\n"
        "## 最小示例\n\n"
        f"把“{checkpoint_title}”写成三栏：已知输入 → 关键步骤 → 可验证输出。"
        "先填一条最有把握的内容，再标出尚未确认的部分。\n\n"
        f"## 下一步\n\n{next_action}\n\n"
        f"> **当前缺口：** {gap} 这份降级讲解只保证学习可以继续，不表示已经掌握。"
    )
    return {
        "title": f"{checkpoint_title} · 最小讲解",
        "content": content,
        "keywords": [],
        "questions": ["请指出这个主题的输入、关键步骤和可验证输出分别是什么？"],
        "source_file": "",
        "source_heading": "",
        "cited_chunks": [],
        "delivery_state": "fallback_ready",
        "mastery_inference": False,
    }


def ensure_teaching_sections(
    sections: Any,
    *,
    contract: Any,
    checkpoint_title: str,
    failure_reason: str = "",
) -> list[dict[str, Any]]:
    normalized_contract = normalize_teaching_contract(contract, objective=checkpoint_title)
    if normalized_contract["teaching_gate"]["status"] == "fallback_ready":
        return [build_fallback_section(
            normalized_contract,
            checkpoint_title=checkpoint_title,
            failure_reason="；".join(normalized_contract["teaching_gate"]["hard_errors"]),
        )]
    valid = [dict(item) for item in (sections or []) if isinstance(item, dict) and _text(item.get("content"))]
    return valid or [build_fallback_section(
        normalized_contract,
        checkpoint_title=checkpoint_title,
        failure_reason=failure_reason,
    )]
