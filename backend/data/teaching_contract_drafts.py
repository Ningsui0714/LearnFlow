"""待专业审核的教学契约草案。

草案只为审核和内容建设提供结构，不由运行时正式讲义读取。通过来源、内容、
练习和实操 Rubric 的人工审核后，才可迁移到 ``teaching_contract.py`` 的正式契约。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DRAFT_REVIEW_STATUS = "draft_pending_expert_review"

TEACHING_CONTRACT_DRAFTS: dict[str, dict[str, Any]] = {
    "ai-python": {
        "teaching_contract_id": "DRAFT-TC-ai-python-v1",
        "contract_version": "draft-v1",
        "knowledge_point_id": "ai-python",
        "knowledge_point_name": "Python、数据结构与科学计算基础",
        "scope": "高职计算机信息技术专业群 · 人工智能技术应用基础模块",
        "review": {
            "status": DRAFT_REVIEW_STATUS,
            "reviewer": None,
            "note": "仅完成教学结构草案；需由课程负责人核验对应 Python 版本、来源定位、示例可运行性和 Rubric。",
        },
        "source_bundle": {
            "status": "pending",
            "sources": [
                {
                    "document_id": "SRC-PYTHON-TUTORIAL",
                    "source_type": "official_document",
                    "source": "Python 官方教程",
                    "source_url": "https://docs.python.org/zh-cn/3/tutorial/",
                    "locator": "数据结构、控制流、函数、模块与输入输出章节",
                }
            ],
        },
        "concepts": [
            {
                "concept_id": "ai-python.sequence-mapping",
                "title": "序列与映射的选择",
                "boundary": "只覆盖 list、tuple、dict 的基本用途和数据访问；不扩展到性能调优或第三方容器。",
            },
            {
                "concept_id": "ai-python.function",
                "title": "函数封装与数据处理步骤",
                "boundary": "只覆盖输入、处理、输出的最小函数；不引入面向对象设计。",
            },
            {
                "concept_id": "ai-python.numeric-boundary",
                "title": "科学计算的输入与结果边界",
                "boundary": "只覆盖数据格式检查、缺失值意识和结果核验；不讲具体机器学习算法。",
            },
        ],
        "outcomes": [
            {
                "outcome_id": "OUT-ai-python-01",
                "statement": "能根据数据访问方式选择 list、tuple 或 dict。",
                "completion_criteria": "针对三个给定小场景说明选择理由，并写出一次正确访问。",
            },
            {
                "outcome_id": "OUT-ai-python-02",
                "statement": "能把一段数据清洗操作封装为最小函数。",
                "completion_criteria": "函数有明确输入和返回值，且能处理一个已声明的异常或空值情形。",
            },
            {
                "outcome_id": "OUT-ai-python-03",
                "statement": "能说明处理结果需要核验的至少一项边界。",
                "completion_criteria": "能指出数据类型、缺失值或结果范围中的一项检查，并给出检查方法。",
            },
        ],
        "required_assets": {
            "knowledge_blocks": ["concept", "steps", "example"],
            "assessment": "待建立经审核的基础练习题与唯一答案规则。",
            "practical_rubric": "待建立函数正确性、输入边界、结果核验和代码可读性的四维 Rubric。",
            "error_patterns": "待收集索引越界、可变默认参数、缺失值遗漏和数据类型误判等真实错误模式。",
        },
    }
}


def get_teaching_contract_draft(module_id: str) -> dict[str, Any] | None:
    draft = TEACHING_CONTRACT_DRAFTS.get(str(module_id or "").strip())
    return deepcopy(draft) if draft else None
