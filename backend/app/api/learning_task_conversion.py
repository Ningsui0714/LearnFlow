"""LearnFlow-facing API for the岗位典型工作任务转化 adapter."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import re
import hmac
from hashlib import sha256
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.config import settings
from app.models.learning import (
    AgentMessage, AgentSession, EvidenceEvent, Learner, UserAccount,
)
from app.services.auth import CurrentLearner, get_current_learner
from app.services.learning_task_conversion_gateway import (
    LearningTaskConversionError,
    LearningTaskConversionGateway,
)
from app.services.learning_task_conversion_xfyun import (
    XfyunLearningTaskWorkflowClient,
    XfyunWorkflowConfigError,
    XfyunWorkflowError,
)
from app.services.learning_task_direct_plan import (
    LearningTaskDirectPlanError,
    LearningTaskDirectPlanGenerator,
)
from app.services.personalized_learning_handoff import (
    PersonalizedLearningHandoffClient,
    PersonalizedLearningHandoffConfigError,
    PersonalizedLearningHandoffError,
    scoped_personalized_learning_entry_id,
)
from app.services.learning_runtime import record_event


router = APIRouter(
    prefix="/learning-task-conversion",
    tags=["岗位典型工作任务转化集成"],
)

_SPECULATIVE_REPAIR_HEAD_START_SECONDS = 5.0


class LearningTaskGenerationRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    session_id: int | None = Field(default=None, ge=1)
    client_turn_id: str | None = Field(default=None, min_length=3, max_length=120)


class LearningTaskIntegrationRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    student_id: str = Field(default="", max_length=120)


class LearningTaskIntegrationLaunchRequest(BaseModel):
    student_id: str = Field(
        min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$",
    )


class PersonalizedLearningResultRequest(BaseModel):
    schema_version: str = Field(
        pattern=r"^personalized-learning-result-v1$",
    )
    entry_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    project_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    knowledge_point_id: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$",
    )
    result_type: str = Field(pattern=r"^assessment_completed$")
    result_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    formal_evidence: bool = False
    summary: dict[str, Any] = Field(default_factory=dict)


def _require_learning_task_integration(request: Request) -> None:
    configured = settings.learning_task_conversion_integration_token.strip()
    supplied = request.headers.get("x-learning-task-conversion-token", "").strip()
    if configured:
        if supplied and hmac.compare_digest(supplied, configured):
            return
        raise HTTPException(status_code=401, detail="学习型任务转化服务凭据无效")
    host = request.client.host if request.client else ""
    if settings.dev_test_login_enabled and host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return
    raise HTTPException(status_code=503, detail="学习型任务转化服务接口尚未配置")


def _knowledge_handoff_entry(
    bundle: dict[str, Any],
    task_card_id: str,
    knowledge_id: str,
) -> dict[str, Any]:
    """Build the smallest complete handoff for one personalized-learning focus."""

    task_envelope = bundle.get("task")
    work_task = (
        task_envelope.get("work_task")
        if isinstance(task_envelope, dict)
        else None
    )
    if not isinstance(work_task, dict):
        raise LearningTaskConversionError(
            "个性化学习交接缺少学习型工作任务",
            status_code=422,
        )

    knowledge_points = work_task.get("knowledge_points") or []
    knowledge = next(
        (
            item for item in knowledge_points
            if isinstance(item, dict)
            and str(item.get("knowledge_id") or "") == knowledge_id
        ),
        None,
    )
    if knowledge is None:
        raise LearningTaskConversionError(
            "当前学习型任务中不存在该知识点",
            status_code=404,
        )

    source_steps = [
        step for step in work_task.get("task_steps") or []
        if isinstance(step, dict)
        and knowledge_id in {
            str(value) for value in step.get("knowledge_point_ids") or []
        }
    ]
    if not source_steps:
        raise LearningTaskConversionError(
            "该知识点没有可追溯的任务步骤映射",
            status_code=422,
        )

    skill_ids = {
        str(skill_id)
        for step in source_steps
        for skill_id in step.get("skill_point_ids") or []
        if str(skill_id).strip()
    }
    skill_ids.update(
        str(skill_id)
        for skill_id in knowledge.get("related_skill_ids") or []
        if str(skill_id).strip()
    )
    related_skills = [
        skill for skill in work_task.get("skill_points") or []
        if isinstance(skill, dict)
        and str(skill.get("skill_id") or "") in skill_ids
    ]

    explicit_relations = [
        relation for relation in bundle.get("strong_relationships") or []
        if isinstance(relation, dict)
        and str(relation.get("knowledge_id") or "") == knowledge_id
    ]
    if explicit_relations:
        relationships = []
        for relation in explicit_relations:
            raw_requested_steps = relation.get("applies_to_steps") or []
            if not isinstance(raw_requested_steps, (list, tuple, set)):
                raw_requested_steps = [raw_requested_steps]
            requested_steps = {
                str(value).strip()
                for value in raw_requested_steps
                if str(value).strip()
            }
            explicit_step_id = str(relation.get("step_id") or "").strip()
            matched_steps = [
                step for step in source_steps
                if (
                    (explicit_step_id and str(step.get("step_id") or "") == explicit_step_id)
                    or bool(
                        requested_steps.intersection({
                            str(step.get("step_id") or "").strip(),
                            str(step.get("name") or "").strip(),
                            str(step.get("title") or "").strip(),
                            str(step.get("action") or "").strip(),
                        })
                    )
                )
            ]
            # Some providers emit only a knowledge-level relation.  It can be
            # assigned deterministically when this handoff has one source step.
            if not matched_steps and len(source_steps) == 1:
                matched_steps = source_steps
            raw_skill_ids = relation.get("skill_ids") or []
            if not isinstance(raw_skill_ids, (list, tuple, set)):
                raw_skill_ids = [raw_skill_ids]
            else:
                raw_skill_ids = list(raw_skill_ids)
            if relation.get("skill_id"):
                raw_skill_ids = [*raw_skill_ids, relation["skill_id"]]
            normalized_skill_ids = list(dict.fromkeys(
                str(value).strip() for value in raw_skill_ids if str(value).strip()
            ))
            for match_index, step in enumerate(matched_steps):
                relationship = dict(relation)
                relationship.update({
                    "relation_id": (
                        str(relation.get("relation_id") or "")
                        + (f":{match_index + 1}" if len(matched_steps) > 1 else "")
                    ),
                    "relation_type": str(
                        relation.get("relation_type") or "required_for_step"
                    ),
                    "strength": "strong",
                    "step_id": str(step.get("step_id") or ""),
                    "knowledge_id": knowledge_id,
                    "skill_ids": normalized_skill_ids,
                })
                relationships.append(relationship)
        if not relationships:
            raise LearningTaskConversionError(
                "知识点强关系无法定位到已校验任务步骤",
                status_code=422,
            )
    else:
        relationships = [
            {
                "relation_id": f"{step.get('step_id')}:{knowledge_id}",
                "relation_type": "required_for_step",
                "strength": "strong",
                "step_id": str(step.get("step_id") or ""),
                "knowledge_id": knowledge_id,
                "skill_ids": [
                    str(value) for value in step.get("skill_point_ids") or []
                ],
                "basis": "validated_step_mapping",
                "reason": "该知识点与技能点由已校验任务步骤显式共同引用。",
            }
            for step in source_steps
        ]

    entry_seed = f"{task_card_id}:{knowledge_id}"
    entry_id = f"ple_{sha256(entry_seed.encode('utf-8')).hexdigest()[:24]}"
    artifacts = bundle.get("artifacts") if isinstance(bundle.get("artifacts"), dict) else {}
    entry_path = (
        "/personalized-learning/tasks/"
        f"{task_card_id}/knowledge/{knowledge_id}"
    )
    handoff_path = (
        "/api/learning-task-conversion/tasks/"
        f"{task_card_id}/knowledge/{knowledge_id}/personalized-learning-entry"
    )

    return {
        "schema_version": "learning-task-knowledge-to-personalized-learning-v1",
        "entry_id": entry_id,
        "status": "ready",
        "source": {
            "source_system": "learning-work-task-conversion",
            "task_card_id": task_card_id,
            "verification_status": str(bundle.get("verification_status") or ""),
            "full_handoff_json_url": str(
                artifacts.get("personalized_learning_json_url") or ""
            ),
        },
        "task_context": {
            "work_task_id": str(work_task.get("work_task_id") or ""),
            "enterprise_task_name": str(
                work_task.get("enterprise_task_name") or ""
            ),
            "enterprise_task_description": str(
                work_task.get("enterprise_task_description") or ""
            ),
            "teaching_task_name": str(work_task.get("teaching_task_name") or ""),
            "teaching_task_description": str(
                work_task.get("teaching_task_description") or ""
            ),
            "work_situation": work_task.get("work_situation"),
        },
        "focus": {
            "knowledge_point": knowledge,
            "source_steps": source_steps,
            "strongly_related_skills": related_skills,
            "relationships": relationships,
        },
        "generation_contract": {
            "purpose": "围绕选中知识点生成个性化学习目标、内容、练习与评价。",
            "immutable_fields": [
                "task_context.work_task_id",
                "task_context.enterprise_task_name",
                "focus.source_steps[].step_id",
                "focus.source_steps[].action",
                "focus.source_steps[].deliverable",
                "focus.source_steps[].check",
                "focus.relationships",
            ],
            "downstream_may_generate": [
                "learning_objectives",
                "learning_content",
                "learning_sequence",
                "practice_activities",
                "assessment_plan",
                "learner_adaptations",
            ],
            "must_preserve_relation_traceability": True,
        },
        "feedback_contract": {
            "schema_version": "personalized-learning-to-task-conversion-feedback-v1",
            "method": "POST",
            "url": "/api/learning-task-conversion/downstream-feedback",
            "supported_issue_targets": [
                "step_id", "knowledge_id", "skill_id", "relation_id",
            ],
        },
        "navigation": {
            "route_key": "personalized_learning.generate_from_knowledge",
            "entry_path": entry_path,
            "handoff_json_path": handoff_path,
            "return_path": f"/wf03/tasks/{task_card_id}",
        },
    }


def _gateway() -> LearningTaskConversionGateway:
    return LearningTaskConversionGateway()


def _xfyun_client() -> XfyunLearningTaskWorkflowClient:
    # This client alone reads backend/.private/learning_task_conversion.xfyun.env.
    # Do not move these credentials into app.core.config or the global .env.
    return XfyunLearningTaskWorkflowClient()


def _personalized_learning_client() -> PersonalizedLearningHandoffClient:
    return PersonalizedLearningHandoffClient()


def _direct_plan_generator() -> LearningTaskDirectPlanGenerator:
    return LearningTaskDirectPlanGenerator()


def _raise_gateway_error(exc: LearningTaskConversionError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _raise_xfyun_error(
    exc: XfyunWorkflowError | XfyunWorkflowConfigError,
) -> None:
    status_code = getattr(exc, "status_code", 503)
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _task_card_id_from_content(content: str) -> str:
    patterns = (
        r"/learning-task-conversion/tasks/(ltc_[A-Za-z0-9_-]{1,96})/",
        r"/learning-tasks/(ltc_[A-Za-z0-9_-]{1,96})/",
        r'"task_card_id"\s*:\s*"(ltc_[A-Za-z0-9_-]{1,96})"',
    )
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return match.group(1)
    return ""


def _failure_reason_from_content(content: str) -> str:
    """Extract a short public reason without exposing workflow internals."""

    match = re.search(r'"hard_errors"\s*:\s*\[\s*"([^"]+)"', content)
    if match:
        return match.group(1).strip()
    match = re.search(r'"errors"\s*:\s*\[\s*"([^"]+)"', content)
    if match:
        return match.group(1).strip()
    return "当前候选任务尚未通过内容与证据门禁"


def _query_requires_clarification(user_input: str) -> bool:
    """Only ask the learner when the input truly contains no usable direction."""

    normalized = re.sub(r"[\s，。！？、,.!?]", "", user_input).lower()
    if not normalized:
        return True
    uncertainty_patterns = (
        r"^(我)?(还)?不知道$",
        r"^(我)?(还)?没想好$",
        r"^(我)?(还)?没决定$",
        r"^(随便|都可以|无所谓)$",
    )
    if any(re.fullmatch(pattern, normalized) for pattern in uncertainty_patterns):
        return True
    remainder = re.sub(
        r"^(我)?(想|要|希望)?(学习|学|了解|入门|从事|做|成为|当)",
        "",
        normalized,
    )
    return not remainder


def _expand_broad_computing_task(user_input: str) -> str:
    """Turn a computing-major direction into one representative work task.

    The task-conversion entry is intentionally different from the ordinary
    learning-goal chat: learners may type a technology name first.  Repeating
    the same clarification for inputs such as ``java`` makes the entry appear
    broken even though the product can safely choose a reversible example.
    Keep explicit tasks unchanged and only expand a small, auditable catalogue
    of broad computing-major directions.
    """

    compact = re.sub(r"[\s，。！？、,.!?的]", "", user_input).lower()
    compact = re.sub(
        r"^(我)?(想|要|希望)?(学习|学|了解|入门|掌握)",
        "",
        compact,
    )
    java_task = "学生成绩管理系统的学生信息增删改查模块开发与验收（Java）"
    python_task = "学生成绩数据分析工具开发与验收（Python）"
    defaults = {
        "java": java_task,
        "java学习": java_task,
        "java入门": java_task,
        "java编程": java_task,
        "java程序设计": java_task,
        "java开发": java_task,
        "java应用": java_task,
        "java应用开发": java_task,
        "python": python_task,
        "python编程": python_task,
        "python开发": python_task,
        "前端": "响应式课程管理前端页面开发与验收",
        "web前端": "响应式课程管理前端页面开发与验收",
        "前端开发": "响应式课程管理前端页面开发与验收",
        "数据库": "学生成绩管理数据库表结构与增删改查功能设计与验收",
        "sql": "学生成绩管理数据库表结构与增删改查功能设计与验收",
        "linux": "Linux服务器安装与基础服务配置验收",
        "网络": "企业园区交换机VLAN与Trunk配置及连通性验收",
        "网络技术": "企业园区交换机VLAN与Trunk配置及连通性验收",
    }
    return defaults.get(compact, user_input)


_LOCAL_JAVA_TASK_CARD_ID = "ltc_java_student_records_v1"
_LOCAL_JAVA_TASK_NAME = "学生成绩管理系统的学生信息增删改查模块开发与验收（Java）"


def _local_reviewed_task_card_id(user_input: str) -> str:
    """Resolve a broad computing direction to a reviewed demo task.

    The provider workflow is still used for concrete, user-specified tasks.
    This small catalogue only prevents common professional-group entry words
    from falling into the provider's INTAKE loop during a live demonstration.
    """

    if _expand_broad_computing_task(user_input) == _LOCAL_JAVA_TASK_NAME:
        return _LOCAL_JAVA_TASK_CARD_ID
    return ""


def _local_reviewed_task_bundle(task_card_id: str) -> dict[str, Any] | None:
    """Return the versioned, reviewable bundle for a local computing task."""

    if task_card_id != _LOCAL_JAVA_TASK_CARD_ID:
        return None

    resource_queries = {
        "kp_java_requirements": "Java 学生成绩管理系统 需求分析 数据模型",
        "kp_java_maven": "Java Maven 项目创建 分层结构",
        "kp_java_oop": "Java 面向对象 封装 参数校验 异常处理",
        "kp_java_crud": "Java CRUD 增删改查 ArrayList",
        "kp_java_junit": "Java JUnit5 单元测试 入门",
        "kp_java_delivery": "Java 项目调试 Git 交付 验收",
    }

    def resources(knowledge_id: str, name: str) -> list[dict[str, str]]:
        query = resource_queries[knowledge_id].replace(" ", "%20")
        return [
            {
                "resource_id": f"res_{knowledge_id}_bilibili",
                "resource_name": f"B站：{name}实操教程",
                "resource_type": "video_search",
                "platform": "bilibili",
                "resource_url": f"https://search.bilibili.com/all?keyword={query}",
            }
        ]

    knowledge_specs = [
        (
            "kp_java_requirements", "K1", "需求分析与数据模型",
            "把业务字段、约束和操作边界转成可实现、可验收的数据模型。",
        ),
        (
            "kp_java_maven", "K2", "Maven工程与分层结构",
            "理解工程目录、依赖配置以及界面层、服务层和数据层的职责边界。",
        ),
        (
            "kp_java_oop", "K3", "Java封装、校验与异常处理",
            "在实体对象中应用封装，并对非法输入给出明确、可追踪的异常。",
        ),
        (
            "kp_java_crud", "K4", "集合与增删改查逻辑",
            "使用集合、接口和条件判断实现学生信息的新增、查询、修改和删除。",
        ),
        (
            "kp_java_junit", "K5", "JUnit 5单元测试",
            "围绕正常、边界和异常场景设计可重复执行的自动化测试。",
        ),
        (
            "kp_java_delivery", "K6", "调试、版本控制与交付验收",
            "根据运行日志定位问题，形成可复现构建和可检查的交付记录。",
        ),
    ]
    knowledge_points = [
        {
            "knowledge_id": knowledge_id,
            "display_code": code,
            "name": name,
            "scope": scope,
            "related_skill_ids": [f"sp_java_{index:02d}"],
            "learning_resources": resources(knowledge_id, name),
        }
        for index, (knowledge_id, code, name, scope) in enumerate(
            knowledge_specs, start=1,
        )
    ]
    skill_names = [
        "把需求整理为字段、规则与验收清单",
        "创建可运行的Maven分层工程",
        "实现实体封装、输入校验与异常处理",
        "实现并调试学生信息增删改查",
        "编写并执行JUnit自动化测试",
        "完成构建、版本归档与验收演示",
    ]
    skill_points = [
        {
            "skill_id": f"sp_java_{index:02d}",
            "display_code": f"S{index}",
            "name": name,
            "observable_action": name,
        }
        for index, name in enumerate(skill_names, start=1)
    ]
    step_specs = [
        (
            "需求分析与数据模型设计",
            "分析学生信息增删改查场景，确定学号、姓名、课程和成绩字段及唯一性、取值范围等规则。",
            "上游任务目标与示例数据已确认。",
            "需求清单与Student、Score数据模型草图",
            "字段覆盖新增、查询、修改、删除四类操作；学号唯一且成绩范围明确。",
            "只使用脱敏的实训数据，不采集真实学生隐私信息。",
        ),
        (
            "创建Maven工程与分层骨架",
            "创建Java Maven工程，配置JDK与JUnit依赖，建立model、repository、service和app目录。",
            "数据模型和技术约束已经评审。",
            "可编译运行的工程骨架与pom.xml",
            "执行mvn test能够完成编译，目录职责与依赖方向清晰。",
            "依赖版本固定，不引入来源不明的第三方包。",
        ),
        (
            "实现实体封装与输入校验",
            "实现Student和Score实体，封装字段访问，并对空值、重复学号和非法成绩抛出业务异常。",
            "工程骨架已通过编译。",
            "实体类、校验器与异常类型源码",
            "非法姓名、重复学号及越界成绩均被拒绝并返回可理解的信息。",
            "异常信息不得输出密码、路径等敏感运行信息。",
        ),
        (
            "实现学生信息增删改查",
            "通过repository与service接口实现新增、按学号查询、修改成绩和删除记录，并保持数据状态一致。",
            "实体与校验逻辑已经完成。",
            "可运行的CRUD服务代码与操作演示记录",
            "四类操作结果正确；不存在的学号得到明确反馈；修改与删除后查询结果一致。",
            "删除前必须确认目标记录，禁止批量误删。",
        ),
        (
            "编写JUnit测试并修复缺陷",
            "为正常、边界和异常路径编写JUnit 5测试，执行测试并根据失败信息修复实现。",
            "CRUD主流程可手工运行。",
            "JUnit测试集、测试报告与缺陷修复记录",
            "核心服务测试全部通过，至少覆盖重复学号、成绩边界和不存在记录三类异常。",
            "测试必须隔离，不能依赖上一次运行遗留的数据。",
        ),
        (
            "构建交付并完成验收演示",
            "清理工程、执行完整构建，整理README和版本提交，按验收清单演示从新增到删除的完整流程。",
            "自动化测试全部通过。",
            "可运行JAR、README、Git提交记录与验收截图",
            "全新环境按README可完成构建；演示结果与需求清单一致；交付物可以追溯到版本号。",
            "交付包不包含密钥、个人数据、IDE缓存和临时构建文件。",
        ),
    ]
    task_steps = [
        {
            "step": index,
            "step_id": f"step_java_{index:02d}",
            "name": name,
            "action": action,
            "prerequisites": prerequisites,
            "deliverable": deliverable,
            "check": check,
            "safety": safety,
            "knowledge_point_ids": [knowledge_specs[index - 1][0]],
            "skill_point_ids": [f"sp_java_{index:02d}"],
        }
        for index, (
            name, action, prerequisites, deliverable, check, safety,
        ) in enumerate(step_specs, start=1)
    ]
    relationships = [
        {
            "relation_id": f"rel_java_{index:02d}",
            "knowledge_id": knowledge_specs[index - 1][0],
            "skill_id": f"sp_java_{index:02d}",
            "skill_ids": [f"sp_java_{index:02d}"],
            "relation_type": "required_for_step",
            "strength": "strong",
            "applies_to_steps": [step_specs[index - 1][0]],
            "step_id": f"step_java_{index:02d}",
            "basis": "reviewed_computing_task_template",
            "reason": "该知识点直接支撑本步骤的可观察技能动作与验收产物。",
        }
        for index in range(1, 7)
    ]
    return {
        "schema_version": "learning-task-conversion-integration-bundle-v1",
        "task_card_id": task_card_id,
        "verification_status": "reviewed_computing_task",
        "task": {
            "schema_version": "learning-task-to-personalized-learning-v1",
            "task_card_id": task_card_id,
            "work_task": {
                "work_task_id": "work_java_student_records_v1",
                "enterprise_task_name": "Java学生成绩管理模块开发与验收",
                "enterprise_task_description": (
                    "按软件开发任务要求实现学生信息增删改查模块，并通过自动化测试和交付验收。"
                ),
                "teaching_task_name": "Java学生成绩管理模块开发学习型工作任务",
                "teaching_task_description": (
                    "在校内软件开发实训环境中完成需求、编码、测试与交付的完整工作过程。"
                ),
                "work_situation": (
                    "作为初级Java开发成员，根据明确需求完成学生成绩管理模块并提交可运行版本。"
                ),
                "task_scenario": (
                    "校内软件项目实训：从需求清单出发完成学生信息模块的开发、测试和验收。"
                ),
                "tools": ["JDK 21", "IntelliJ IDEA", "Maven", "JUnit 5", "Git"],
                "safety_points": [
                    "仅使用脱敏测试数据",
                    "禁止在源码中写入密钥和个人信息",
                    "删除操作必须确认目标记录",
                ],
                "acceptance_tests": [
                    "Maven完整构建通过",
                    "增删改查与异常路径测试通过",
                    "README能够指导全新环境复现",
                ],
                "task_steps": task_steps,
                "knowledge_points": knowledge_points,
                "skill_points": skill_points,
            },
        },
        "strong_relationships": relationships,
        "artifacts": {
            "interactive_html_url": "",
            "pdf_url": "",
            "personalized_learning_json_url": (
                f"/api/learning-task-conversion/tasks/{task_card_id}/personalized-learning"
            ),
            "feedback_json_url": "/api/learning-task-conversion/downstream-feedback",
        },
    }


async def _resolved_task_bundle(task_card_id: str) -> dict[str, Any]:
    local_bundle = _local_reviewed_task_bundle(task_card_id)
    if local_bundle is not None:
        return local_bundle
    return await _gateway().task_bundle(task_card_id)


def _learner_display_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Remove provider review state from the learner-facing task bundle.

    After structural validation the workbench opens the result as a normal
    task. Provider evidence/review metadata remains at the source service for
    auditing, but it must not create a learner-facing draft or pending state.
    """

    display_bundle = deepcopy(bundle)
    display_bundle.pop("verification_status", None)
    display_bundle.pop("traceability", None)
    task = display_bundle.get("task")
    if isinstance(task, dict):
        for field in (
            "verification_status",
            "review_required",
            "review_mode",
            "evidence_required",
            "release_scope",
        ):
            task.pop(field, None)
    return display_bundle


def _is_explicit_work_task(user_input: str) -> bool:
    normalized = re.sub(r"\s+", "", user_input)
    role_markers = (
        "工程师", "技术员", "技师", "操作员", "运维员", "岗位", "职业",
    )
    if any(marker in normalized for marker in role_markers):
        return False
    action_markers = (
        "安装", "拆装", "装配", "检修", "维修", "维护", "调试", "检测",
        "校准", "配置", "部署", "开发", "制作", "加工", "焊接", "更换",
        "诊断", "排查", "修复", "验收", "测试", "巡检", "交付",
    )
    return any(marker in normalized for marker in action_markers)


def _task_object_anchor(user_input: str) -> str:
    """Derive a short object phrase that repair candidates can preserve verbatim."""

    normalized = re.sub(r"[\s，。！？、,.!?]", "", user_input).strip()
    normalized = re.sub(
        r"^(我)?(想|要|希望)?(学习|学|了解|入门|掌握|做)",
        "",
        normalized,
    )
    for marker in (
        "安装", "拆装", "装配", "检修", "维修", "维护", "调试", "检测",
        "校准", "配置", "部署", "开发", "制作", "加工", "焊接", "更换",
        "诊断", "排查", "修复", "验收", "测试", "巡检", "交付",
    ):
        marker_index = normalized.find(marker)
        if marker_index > 0:
            normalized = normalized[:marker_index]
            break
    normalized = normalized.strip("的")
    if "新能源" in normalized and "汽车" in normalized and normalized.endswith("电池"):
        normalized += "包"
    elif normalized.endswith("动力电池"):
        normalized += "包"
    return normalized[:48]


def _catalog_bundle_preserves_task_object(
    user_input: str,
    bundle: dict[str, Any],
) -> bool:
    """Reject broad catalogue matches that replace the requested task object."""

    anchor = _task_object_anchor(user_input)
    normalized_anchor = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", anchor).lower()
    if not normalized_anchor:
        return False
    task = bundle.get("task") if isinstance(bundle, dict) else None
    work_task = task.get("work_task") if isinstance(task, dict) else None
    if not isinstance(work_task, dict):
        return False
    searchable_fields = (
        "enterprise_task_name",
        "enterprise_task_description",
        "teaching_task_name",
        "teaching_task_description",
        "work_situation",
        "task_scenario",
    )
    searchable = "".join(
        str(work_task.get(field) or "") for field in searchable_fields
    )
    normalized_searchable = re.sub(
        r"[^a-zA-Z0-9\u4e00-\u9fff]", "", searchable,
    ).lower()

    # Preserve every explicitly named technology across the whole request,
    # including technologies after an action verb.  For example,
    # "Docker Compose部署Redis" must never reuse a Docker Nginx/MySQL task just
    # because its prefix matches.
    required_latin = {
        token.lower()
        for token in re.findall(
            r"[a-zA-Z][a-zA-Z0-9+#.]{1,30}", user_input,
        )
    }
    if any(token not in normalized_searchable for token in required_latin):
        return False
    if normalized_anchor in normalized_searchable:
        return True
    # For a short direction such as "Windows系统安装", retain a strict
    # technology/object prefix instead of accepting a match on generic words
    # like "开发" or "验收".
    latin_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.]{1,20}", anchor)
    distinctive_chinese = [
        token for token in re.findall(r"[\u4e00-\u9fff]{2,}", anchor)
        if token not in {"系统", "模块", "任务", "开发", "验收"}
    ]
    tokens = [token.lower() for token in latin_tokens] + distinctive_chinese
    return bool(tokens) and all(token in normalized_searchable for token in tokens)


def _task_bundle_quality_issues(
    user_input: str,
    bundle: dict[str, Any],
) -> list[str]:
    """Return release-blocking learner-facing task-package defects."""

    issues: list[str] = []
    if not _catalog_bundle_preserves_task_object(user_input, bundle):
        issues.append("TASK_OBJECT_NOT_PRESERVED")
    task = bundle.get("task") if isinstance(bundle, dict) else None
    work_task = task.get("work_task") if isinstance(task, dict) else None
    if not isinstance(work_task, dict):
        return [*issues, "WORK_TASK_MISSING"]
    steps = work_task.get("task_steps")
    if not isinstance(steps, list) or not 5 <= len(steps) <= 8:
        issues.append("STEP_COUNT_OUT_OF_RANGE")
        steps = steps if isinstance(steps, list) else []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            issues.append(f"STEP_{index}_INVALID")
            continue
        for field in ("name", "action", "deliverable", "check"):
            if not str(step.get(field) or "").strip():
                issues.append(f"STEP_{index}_{field.upper()}_MISSING")
        if not step.get("knowledge_point_ids"):
            issues.append(f"STEP_{index}_KNOWLEDGE_MISSING")
        if not step.get("skill_point_ids"):
            issues.append(f"STEP_{index}_SKILL_MISSING")
    knowledge_points = work_task.get("knowledge_points")
    skill_points = work_task.get("skill_points")
    if not isinstance(knowledge_points, list) or len(knowledge_points) < 3:
        issues.append("KNOWLEDGE_POINTS_INSUFFICIENT")
    if not isinstance(skill_points, list) or len(skill_points) < 3:
        issues.append("SKILL_POINTS_INSUFFICIENT")
    return issues


def _auto_revision_prompt(user_input: str, content: str) -> str:
    """Compile a bounded, auditable repair request accepted by Xingchen tools."""

    hints: list[str] = []
    if "ACTION_NOT_SPECIFIC" in content:
        hints.append("动作写明操作对象和实际操作")
    if "CHECK_NOT_VERIFIABLE" in content:
        hints.append("检查点改成可观察、可记录或可测量")
    if "workflow_steps" in content:
        hints.append("重建完整实际作业步骤")
    if "OBJECT_NOT_PRESERVED" in content or "没有保留任务对象" in content:
        hints.append("原样写出对象锚点")
    hint_text = "；".join(hints[:3])
    if _is_explicit_work_task(user_input):
        level_instruction = (
            "这是明确的单个企业任务，不反问、不换题，也不得拆成多个任务。"
        )
    else:
        level_instruction = (
            "这是岗位或职业方向，不反问、不换题；自动选择其中一个可执行的典型企业任务。"
        )
    object_anchor = _task_object_anchor(user_input) if _is_explicit_work_task(user_input) else ""
    anchor_instruction = (
        f"对象锚点为“{object_anchor}”，任务名称、描述和至少一个步骤必须原样写出该对象；"
        "近义词可并列，不能替代对象锚点。"
        if object_anchor
        else ""
    )
    prompt = (
        f"{user_input}\n"
        f"自动修订要求：{level_instruction}重新生成完整候选，步骤数按实际流程确定；"
        f"{anchor_instruction}"
        "每步包含具体动作、可留存产物、可核验检查点及知识点和技能点映射。"
        "除明显跑题、缺少步骤或安全风险外，其余不足标待复核并继续生成。"
        "Plan的repair_budget=1（不得超过2）。"
    )
    if hint_text:
        prompt += f"优先修复：{hint_text}。"
    # AgentRunCreateRequest has a hard 500-character user_query limit.  The
    # public request schema uses the same limit, so this only removes optional
    # repair hints and never truncates the immutable original input.
    if len(prompt) > 500 and hint_text:
        prompt = prompt[: prompt.rfind("优先修复：")]
    return prompt


def _non_success_result(
    workflow_run: dict[str, Any],
    user_input: str,
) -> dict[str, Any]:
    content = str(workflow_run.get("content") or "").strip()
    if _query_requires_clarification(user_input):
        # Workflow output may contain provider-only URLs or empty Markdown
        # links. Clarification is a fixed public response, never a pass-through
        # of orchestration content.
        message = _clarification_result(user_input)["message"]
        status = "needs_clarification"
    else:
        reason = _failure_reason_from_content(content)
        message = (
            f"系统已经锁定“{user_input}”并完成自动修订，但候选仍未通过发布门禁：{reason}。"
            "原任务没有被替换；本次结果已保留为待复核草稿，不要求学习者重复补充同一信息。"
        )
        status = "needs_revision"
    return {
        "schema_version": "learnflow-learning-task-generation-v2",
        "execute_id": workflow_run.get("run_id") or "",
        "status": status,
        "task_card_id": "",
        "message": message,
        "usage": workflow_run.get("usage") or {},
        "bundle": None,
    }


def _fresh_workflow_uid(learner_id: int) -> str:
    """Keep every task-conversion run isolated from Xingchen stage state."""

    return f"lf-{learner_id}-{uuid4().hex[:24]}"


def _is_workflow_stage_conflict(exc: XfyunWorkflowError) -> bool:
    message = str(exc)
    # 21812 is Xingchen's generic workflow/tool execution code.  It is also
    # returned for network/plugin failures (for example a third-party 405),
    # which must never be presented to the learner as "please clarify the
    # task".  Only the provider's explicit stage-state wording is recoverable
    # by creating a fresh workflow UID.
    return "当前阶段" in message or bool(
        re.search(r"\bINTAKE\b.*(?:不接受|阶段|冲突)", message, flags=re.I)
    )


def _should_use_direct_plan_fallback(
    exc: XfyunWorkflowError | XfyunWorkflowConfigError,
) -> bool:
    """Use the same Plan backend when Xingchen's published tool is unhealthy."""

    if isinstance(exc, XfyunWorkflowConfigError):
        return True
    message = str(exc).lower()
    markers = (
        "third-party tool request failed",
        "method not allowed",
        "error code: 405",
        "功能授权",
        "业务量已超限",
        "20373",
        "连接失败",
        "未收到响应",
    )
    return any(marker in message for marker in markers)


async def _direct_plan_after_xfyun_failure(
    user_input: str,
    exc: XfyunWorkflowError | XfyunWorkflowConfigError,
) -> dict[str, Any]:
    if not _should_use_direct_plan_fallback(exc):
        raise exc
    return await _direct_plan_generator().generate(user_input)


async def _quality_gate_or_direct_plan(
    user_input: str,
    workflow_run: dict[str, Any],
) -> dict[str, Any]:
    """Accept a generated package only when the learner-facing bundle is deep enough."""

    task_card_id = _task_card_id_from_content(
        str(workflow_run.get("content") or "")
    )
    if task_card_id:
        try:
            bundle = await _gateway().task_bundle(task_card_id)
        except LearningTaskConversionError:
            bundle = {}
        if not _task_bundle_quality_issues(user_input, bundle):
            return workflow_run
    # A clear task that produced no package, a wrong task, or fewer than five
    # complete steps is not shown as a learner-facing failure.  Recompile it
    # through the same Plan/Critic/commit service with the strict candidate
    # schema used by the direct fallback.
    return await _direct_plan_generator().generate(user_input)


def _clarification_result(user_input: str) -> dict[str, Any]:
    """Translate Xingchen's INTAKE state into a user-facing follow-up turn."""

    return {
        "schema_version": "learnflow-learning-task-generation-v2",
        "execute_id": "",
        "status": "needs_clarification",
        "task_card_id": "",
        "message": (
            f"我已识别到你想围绕“{user_input}”生成学习型工作任务，但目前还不能唯一确定"
            "要转换的企业真实工作任务。请再补充一个可执行对象或结果，例如："
            "“Linux系统安装与基础配置”“风力发电机组日常巡检”或"
            "“新能源汽车电池包安装”。补充后我会沿用本次功能继续生成。"
        ),
        "usage": {},
        "bundle": None,
    }


async def _owned_generation_session(
    db: AsyncSession,
    learner_id: int,
    session_id: int | None,
) -> AgentSession | None:
    if session_id is None:
        return None
    session = (await db.execute(select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.learner_id == learner_id,
        AgentSession.status == "active",
    ))).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="当前任务生成会话不存在或已结束")
    return session


async def _replay_generation_result(
    db: AsyncSession,
    session: AgentSession | None,
    client_turn_id: str,
) -> dict[str, Any] | None:
    if session is None:
        return None
    idempotency_key = f"learning-task-result:{session.learner_id}:{client_turn_id}"
    message = (await db.execute(select(AgentMessage).where(
        AgentMessage.session_id == session.id,
        AgentMessage.idempotency_key == idempotency_key,
    ))).scalar_one_or_none()
    if message is None:
        return None
    stored = dict((message.meta_data or {}).get("generation_result") or {})
    task_card_id = str(stored.get("task_card_id") or "")
    bundle = (
        _learner_display_bundle(await _resolved_task_bundle(task_card_id))
        if task_card_id else None
    )
    workspace_path = f"/wf03/tasks/{task_card_id}" if task_card_id else ""
    artifacts = bundle.get("artifacts") if isinstance(bundle, dict) else None
    provider_artifact_url = (
        str(artifacts.get("interactive_html_url") or "").strip()
        if isinstance(artifacts, dict)
        else ""
    )
    return {
        "schema_version": "learnflow-learning-task-generation-v2",
        "execute_id": str(stored.get("execute_id") or ""),
        "status": str(stored.get("status") or "needs_revision"),
        "task_card_id": task_card_id,
        "message": message.content,
        "usage": {},
        "workspace_path": workspace_path,
        "artifact_url": workspace_path,
        "provider_artifact_url": provider_artifact_url,
        "bundle": bundle,
        "replayed": True,
    }


async def _persist_generation_exchange(
    db: AsyncSession,
    session: AgentSession | None,
    *,
    client_turn_id: str,
    user_input: str,
    result: dict[str, Any],
) -> None:
    if session is None:
        return
    learner_id = session.learner_id
    request_key = f"learning-task-request:{learner_id}:{client_turn_id}"
    result_key = f"learning-task-result:{learner_id}:{client_turn_id}"
    request_statement = sqlite_insert(AgentMessage).values(
        session_id=session.id,
        role="user",
        content=user_input,
        meta_data={
            "message_kind": "learning_task_request",
            "client_turn_id": client_turn_id,
        },
        idempotency_key=request_key,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"])
    await db.execute(request_statement)
    public_result = {
        "status": result["status"],
        "task_card_id": result.get("task_card_id") or "",
        "execute_id": result.get("execute_id") or "",
        "workspace_path": result.get("workspace_path") or "",
    }
    result_statement = sqlite_insert(AgentMessage).values(
        session_id=session.id,
        role="assistant",
        content=str(result.get("message") or ""),
        meta_data={
            "message_kind": (
                "learning_task_generated"
                if result["status"] == "success"
                else "learning_task_follow_up"
            ),
            "generation_result": public_result,
            "client_turn_id": client_turn_id,
        },
        idempotency_key=result_key,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"])
    inserted_result = await db.execute(result_statement)
    if inserted_result.rowcount:
        await record_event(
            db,
            learner_id=learner_id,
            event_type=(
                "learning_work_task_generated"
                if result["status"] == "success"
                else "learning_work_task_generation_follow_up"
            ),
            source="learning_task_conversion",
            session_id=session.id,
            payload={
                "query": user_input,
                **public_result,
            },
            artifact_refs=(
                [f"learning-task:{result['task_card_id']}"]
                if result.get("task_card_id") else []
            ),
            client_event_id=f"learning-task:{client_turn_id}",
        )
    await db.commit()


async def _run_isolated_workflow(
    client: XfyunLearningTaskWorkflowClient,
    user_input: str,
    *,
    learner_id: int,
) -> dict[str, Any]:
    """Run in a fresh provider session and self-heal one stale-stage failure."""

    try:
        return await client.run(
            user_input,
            uid=_fresh_workflow_uid(learner_id),
        )
    except XfyunWorkflowError as exc:
        if not _is_workflow_stage_conflict(exc):
            raise
        return await client.run(
            user_input,
            uid=_fresh_workflow_uid(learner_id),
        )


def _merge_workflow_usage(*runs: dict[str, Any]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for run in runs:
        usage = run.get("usage") if isinstance(run, dict) else None
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, int) and not isinstance(value, bool):
                merged[key] = merged.get(key, 0) + value
    return merged


async def _run_generation_workflow(
    client: XfyunLearningTaskWorkflowClient,
    user_input: str,
    *,
    learner_id: int,
) -> dict[str, Any]:
    """Run Plan once, then repair one clear-but-rejected task automatically."""

    if _query_requires_clarification(user_input):
        return await _run_isolated_workflow(
            client,
            user_input,
            learner_id=learner_id,
        )

    local_task_card_id = _local_reviewed_task_card_id(user_input)
    if local_task_card_id:
        return {
            "schema_version": "learning-task-conversion-reviewed-run-v1",
            "provider": "reviewed-computing-task-catalog",
            "run_id": f"reviewed:{local_task_card_id}",
            "content": f'{{"task_card_id":"{local_task_card_id}"}}',
            "usage": {},
            "catalog_reuse": True,
        }

    user_input = _expand_broad_computing_task(user_input)

    # WF03 is database-first: reviewed enterprise tasks already have complete
    # workflow_steps and must not be degraded by a fresh model repair turn.
    # Only an unseen task continues to the Xingchen Plan workflow below.
    catalog_task_card_id: str | None = None
    if _is_explicit_work_task(user_input):
        try:
            catalog_task_card_id = await _gateway().generate_catalog_match(
                user_input
            )
            if catalog_task_card_id:
                catalog_bundle = await _gateway().task_bundle(catalog_task_card_id)
                if _task_bundle_quality_issues(user_input, catalog_bundle):
                    catalog_task_card_id = None
        except LearningTaskConversionError:
            # Catalogue lookup is an optimization, not a new single point of
            # failure.  Unavailable or unmatched data continues to the model
            # Plan path, which is the required standalone operating mode.
            catalog_task_card_id = None
    if catalog_task_card_id:
        return {
            "schema_version": "learning-task-conversion-catalog-run-v1",
            "provider": "wf03-reviewed-task-catalog",
            "run_id": f"catalog:{catalog_task_card_id}",
            "content": (
                "/api/v1/learning-task-conversion/tasks/"
                f"{catalog_task_card_id}/interactive.html"
            ),
            "usage": {},
            "catalog_reuse": True,
        }

    # Clear tasks receive the proven Plan constraints on the first run.  A
    # repair branch starts after a short head start, rather than waiting several
    # minutes for a rejected draft and then paying the same latency again.
    primary = asyncio.create_task(_run_isolated_workflow(
        client,
        _auto_revision_prompt(user_input, ""),
        learner_id=learner_id,
    ))
    done, _ = await asyncio.wait(
        {primary},
        timeout=_SPECULATIVE_REPAIR_HEAD_START_SECONDS,
    )
    if done:
        try:
            initial = await primary
        except (XfyunWorkflowError, XfyunWorkflowConfigError) as exc:
            return await _direct_plan_after_xfyun_failure(user_input, exc)
        if _task_card_id_from_content(str(initial.get("content") or "")):
            return await _quality_gate_or_direct_plan(user_input, initial)
        try:
            repaired = await _run_isolated_workflow(
                client,
                _auto_revision_prompt(user_input, str(initial.get("content") or "")),
                learner_id=learner_id,
            )
        except (XfyunWorkflowError, XfyunWorkflowConfigError) as exc:
            return await _direct_plan_after_xfyun_failure(user_input, exc)
        result = dict(repaired)
        result["usage"] = _merge_workflow_usage(initial, repaired)
        result["auto_revision"] = {
            "attempted": True,
            "mode": "sequential_fast_failure",
            "attempts": 1,
            "initial_run_id": str(initial.get("run_id") or ""),
            "final_run_id": str(repaired.get("run_id") or ""),
        }
        return await _quality_gate_or_direct_plan(user_input, result)

    repair = asyncio.create_task(_run_isolated_workflow(
        client,
        _auto_revision_prompt(
            user_input,
            "ACTION_NOT_SPECIFIC CHECK_NOT_VERIFIABLE workflow_steps",
        ),
        learner_id=learner_id,
    ))
    tasks = (primary, repair)
    completed_runs: list[dict[str, Any]] = []
    errors: list[Exception] = []
    try:
        for finished in asyncio.as_completed(tasks):
            try:
                run = await finished
            except Exception as exc:
                errors.append(exc)
                continue
            completed_runs.append(run)
            if _task_card_id_from_content(str(run.get("content") or "")):
                result = dict(run)
                result["usage"] = _merge_workflow_usage(*completed_runs)
                result["auto_revision"] = {
                    "attempted": True,
                    "mode": "speculative_parallel",
                    "attempts": 1,
                    "winner_run_id": str(run.get("run_id") or ""),
                }
                return await _quality_gate_or_direct_plan(user_input, result)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    if completed_runs:
        result = dict(completed_runs[-1])
        result["usage"] = _merge_workflow_usage(*completed_runs)
        result["auto_revision"] = {
            "attempted": True,
            "mode": "speculative_parallel",
            "attempts": 1,
            "winner_run_id": "",
        }
        return await _quality_gate_or_direct_plan(user_input, result)
    if errors:
        first = errors[0]
        if isinstance(first, (XfyunWorkflowError, XfyunWorkflowConfigError)):
            return await _direct_plan_after_xfyun_failure(user_input, first)
        raise first
    raise XfyunWorkflowError("自动修订未返回工作流结果")


@router.post("/workflow-runs")
async def run_learning_task_conversion_workflow(
    payload: dict[str, Any] = Body(...),
    current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    """Run only the bound Plan workflow for this feature.

    Callers cannot provide a host, API key, secret, or flow ID.  Those values
    stay in the ignored feature-private file, preventing this endpoint from
    becoming a generic Xingchen proxy.
    """

    user_input = str(payload.get("user_input") or "").strip()
    if not user_input:
        raise HTTPException(status_code=422, detail="请提供明确的岗位典型工作任务")
    if len(user_input) > 500:
        raise HTTPException(status_code=422, detail="岗位典型工作任务描述不能超过500字")

    try:
        return await _run_isolated_workflow(
            _xfyun_client(),
            user_input,
            learner_id=current.learner.id,
        )
    except (XfyunWorkflowError, XfyunWorkflowConfigError) as exc:
        _raise_xfyun_error(exc)


@router.post("/generate")
async def generate_learning_task_from_conversation(
    request: LearningTaskGenerationRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate and resolve one task into the LearnFlow review workspace.

    The endpoint composes the feature-private Xingchen workflow with the fixed
    artifact gateway.  It never accepts credentials, hosts, or flow IDs from
    the browser.
    """

    user_input = request.query.strip()
    client_turn_id = request.client_turn_id or f"learning-task-{uuid4().hex}"
    session = await _owned_generation_session(
        db, current.learner.id, request.session_id,
    )
    replayed = await _replay_generation_result(db, session, client_turn_id)
    if replayed is not None:
        return replayed

    try:
        workflow_run = await _run_generation_workflow(
            _xfyun_client(),
            user_input,
            learner_id=current.learner.id,
        )
        task_card_id = _task_card_id_from_content(workflow_run["content"])
        if not task_card_id:
            result = _non_success_result(workflow_run, user_input)
            await _persist_generation_exchange(
                db, session, client_turn_id=client_turn_id,
                user_input=user_input, result=result,
            )
            return result
        bundle = _learner_display_bundle(await _resolved_task_bundle(task_card_id))
        workspace_path = f"/wf03/tasks/{task_card_id}"
        artifacts = bundle.get("artifacts") if isinstance(bundle, dict) else None
        provider_artifact_url = (
            str(artifacts.get("interactive_html_url") or "").strip()
            if isinstance(artifacts, dict)
            else ""
        )
        result = {
            "schema_version": "learnflow-learning-task-generation-v2",
            "execute_id": workflow_run.get("run_id") or "",
            "status": "success",
            "task_card_id": task_card_id,
            "message": (
                "学习型任务已经生成并在中间工作区打开。"
                "你可以按步骤查看产物与验收点，点击知识点直接进入个性化学习。"
            ),
            "usage": workflow_run.get("usage") or {},
            # The repository workbench is the only learner-facing page.  Keep
            # the provider-rendered HTML only as an audit artifact so callers
            # cannot accidentally replace the three-column workspace with it.
            "workspace_path": workspace_path,
            "artifact_url": workspace_path,
            "provider_artifact_url": provider_artifact_url,
            "bundle": bundle,
        }
        await _persist_generation_exchange(
            db, session, client_turn_id=client_turn_id,
            user_input=user_input, result=result,
        )
        return result
    except (XfyunWorkflowError, XfyunWorkflowConfigError) as exc:
        if isinstance(exc, XfyunWorkflowError) and _is_workflow_stage_conflict(exc):
            result = _clarification_result(user_input)
            await _persist_generation_exchange(
                db, session, client_turn_id=client_turn_id,
                user_input=user_input, result=result,
            )
            return result
        _raise_xfyun_error(exc)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)
    except LearningTaskDirectPlanError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/integration-generate")
async def generate_learning_task_for_integration(
    payload: LearningTaskIntegrationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate a WF03 task for an approved external learning shell.

    The caller never supplies provider credentials or a workflow id.  In
    development this endpoint is loopback-only; deployments must configure a
    shared integration token.  The response contains the validated bundle and
    the task artifact URL so the caller can render it in its own workbench.
    """

    _require_learning_task_integration(request)
    learner_id = (await db.execute(
        select(Learner.id)
        .join(UserAccount, UserAccount.id == Learner.user_id)
        .where(UserAccount.status == "active")
        .order_by(Learner.id.asc())
        .limit(1)
    )).scalar_one_or_none()
    if learner_id is None:
        raise HTTPException(status_code=503, detail="学习型任务转化服务尚无可用运行身份")

    user_input = payload.query.strip()
    try:
        workflow_run = await _run_generation_workflow(
            _xfyun_client(), user_input, learner_id=learner_id,
        )
        task_card_id = _task_card_id_from_content(workflow_run["content"])
        if not task_card_id:
            return _non_success_result(workflow_run, user_input)
        bundle = _learner_display_bundle(await _resolved_task_bundle(task_card_id))
        artifacts = bundle.get("artifacts") if isinstance(bundle, dict) else None
        provider_artifact_url = (
            str(artifacts.get("interactive_html_url") or "").strip()
            if isinstance(artifacts, dict)
            else ""
        )
        workspace_path = f"/wf03/tasks/{task_card_id}"
        return {
            "schema_version": "learnflow-learning-task-generation-v2",
            "execute_id": workflow_run.get("run_id") or "",
            "status": "success",
            "task_card_id": task_card_id,
            "message": "学习型任务已经生成，可在当前工作台查看并选择知识点进入个性化学习。",
            "usage": workflow_run.get("usage") or {},
            "workspace_path": workspace_path,
            "artifact_url": workspace_path,
            "provider_artifact_url": provider_artifact_url,
            "bundle": bundle,
        }
    except (XfyunWorkflowError, XfyunWorkflowConfigError) as exc:
        if isinstance(exc, XfyunWorkflowError) and _is_workflow_stage_conflict(exc):
            return _clarification_result(user_input)
        _raise_xfyun_error(exc)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)
    except LearningTaskDirectPlanError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post(
    "/integration-tasks/{task_card_id}/knowledge/{knowledge_id}/"
    "personalized-learning-launch"
)
async def launch_integration_personalized_learning(
    payload: LearningTaskIntegrationLaunchRequest,
    request: Request,
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    knowledge_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Launch one knowledge point inside an approved external workbench."""

    _require_learning_task_integration(request)
    learner_id = (await db.execute(
        select(Learner.id)
        .join(UserAccount, UserAccount.id == Learner.user_id)
        .where(UserAccount.status == "active")
        .order_by(Learner.id.asc())
        .limit(1)
    )).scalar_one_or_none()
    if learner_id is None:
        raise HTTPException(status_code=503, detail="学习型任务转化服务尚无可用运行身份")
    try:
        bundle = await _resolved_task_bundle(task_card_id)
        entry = _knowledge_handoff_entry(bundle, task_card_id, knowledge_id)
        result = await _personalized_learning_client().import_entry(
            learner_id=learner_id,
            handoff=entry,
            downstream_student_id=payload.student_id,
        )
        await record_event(
            db,
            learner_id=learner_id,
            event_type="personalized_learning_handoff_opened",
            source="learning_task_conversion",
            payload={
                "entry_id": entry["entry_id"],
                "task_card_id": task_card_id,
                "knowledge_id": knowledge_id,
                "schema_version": entry["schema_version"],
                "downstream_project_id": result["project_id"],
                "downstream_created": result["created"],
            },
            artifact_refs=[
                f"learning-task:{task_card_id}",
                f"knowledge:{knowledge_id}",
            ],
            client_event_id=(
                f"personalized-integration-launch:{learner_id}:{entry['entry_id']}"
            ),
        )
        await db.commit()
        return result
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)
    except PersonalizedLearningHandoffConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PersonalizedLearningHandoffError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/capabilities")
async def get_learning_task_conversion_capabilities(
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().capabilities()
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.post("/upstream-handoffs")
async def submit_competency_graph_handoff(
    payload: dict[str, Any] = Body(...),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().submit_upstream_handoff(payload)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.get("/tasks/{task_card_id}/bundle")
async def get_learning_task_conversion_bundle(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _resolved_task_bundle(task_card_id)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.get("/tasks/{task_card_id}/personalized-learning")
async def get_personalized_learning_handoff(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        local_bundle = _local_reviewed_task_bundle(task_card_id)
        if local_bundle is not None:
            return dict(local_bundle["task"])
        return await _gateway().personalized_learning_handoff(task_card_id)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.get(
    "/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-entry"
)
async def get_knowledge_personalized_learning_entry(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    knowledge_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    """Return a knowledge-scoped, versioned JSON handoff for downstream use."""

    try:
        bundle = await _resolved_task_bundle(task_card_id)
        return _knowledge_handoff_entry(bundle, task_card_id, knowledge_id)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.post(
    "/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-entry"
)
async def open_knowledge_personalized_learning_entry(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    knowledge_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Prepare the handoff and record the explicit cross-function navigation."""

    try:
        bundle = await _resolved_task_bundle(task_card_id)
        entry = _knowledge_handoff_entry(bundle, task_card_id, knowledge_id)
        await record_event(
            db,
            learner_id=current.learner.id,
            event_type="personalized_learning_handoff_opened",
            source="learning_task_conversion",
            payload={
                "entry_id": entry["entry_id"],
                "task_card_id": task_card_id,
                "knowledge_id": knowledge_id,
                "schema_version": entry["schema_version"],
            },
            artifact_refs=[
                f"learning-task:{task_card_id}",
                f"knowledge:{knowledge_id}",
            ],
            client_event_id=f"personalized-entry:{current.learner.id}:{entry['entry_id']}",
        )
        await db.commit()
        return entry
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.post(
    "/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-launch"
)
async def launch_knowledge_personalized_learning(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    knowledge_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Import the verified handoff with server-owned identity and return a URL."""

    try:
        bundle = await _resolved_task_bundle(task_card_id)
        entry = _knowledge_handoff_entry(bundle, task_card_id, knowledge_id)
        result = await _personalized_learning_client().import_entry(
            learner_id=current.learner.id,
            handoff=entry,
        )
        await record_event(
            db,
            learner_id=current.learner.id,
            event_type="personalized_learning_handoff_opened",
            source="learning_task_conversion",
            payload={
                "entry_id": entry["entry_id"],
                "task_card_id": task_card_id,
                "knowledge_id": knowledge_id,
                "schema_version": entry["schema_version"],
                "downstream_project_id": result["project_id"],
                "downstream_created": result["created"],
            },
            artifact_refs=[
                f"learning-task:{task_card_id}",
                f"knowledge:{knowledge_id}",
            ],
            client_event_id=(
                f"personalized-launch:{current.learner.id}:{entry['entry_id']}"
            ),
        )
        await db.commit()
        return result
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)
    except PersonalizedLearningHandoffConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PersonalizedLearningHandoffError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post(
    "/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-results"
)
async def receive_personalized_learning_result(
    payload: PersonalizedLearningResultRequest,
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    knowledge_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Persist a verified downstream result as a zero-kernel audit artifact.

    The imported direction only supports provisional self-checks.  The result
    is useful for continuity and review, but cannot become mastery evidence
    until LearnFlow owns a formal assessment specification and attempt.
    """

    try:
        bundle = await _resolved_task_bundle(task_card_id)
        entry = _knowledge_handoff_entry(bundle, task_card_id, knowledge_id)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)

    expected_entry_id = scoped_personalized_learning_entry_id(
        str(entry["entry_id"]),
        current.learner.id,
    )
    if payload.entry_id != expected_entry_id or payload.knowledge_point_id != knowledge_id:
        raise HTTPException(status_code=409, detail="个性化学习结果身份与当前交接不一致")
    if payload.formal_evidence:
        raise HTTPException(
            status_code=422,
            detail="当前交接仅允许回传临时自测结果，不能声明正式掌握证据",
        )

    summary = payload.summary
    assessment_type = str(summary.get("assessment_type") or "").strip()
    if assessment_type != "provisional_self_check":
        raise HTTPException(status_code=422, detail="当前仅接受练习型初测结果")

    def bounded_count(name: str, *, minimum: int, maximum: int) -> int:
        value = summary.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(status_code=422, detail=f"{name} 必须是整数")
        if value < minimum or value > maximum:
            raise HTTPException(status_code=422, detail=f"{name} 超出允许范围")
        return value

    total = bounded_count("total", minimum=1, maximum=100)
    score = bounded_count("score", minimum=0, maximum=total)
    weak_point_count = bounded_count(
        "weak_point_count", minimum=0, maximum=total,
    )

    launch_events = (await db.execute(
        select(EvidenceEvent)
        .where(
            EvidenceEvent.learner_id == current.learner.id,
            EvidenceEvent.event_type == "personalized_learning_handoff_opened",
        )
        .order_by(EvidenceEvent.id.desc())
        .limit(100)
    )).scalars().all()
    launch_found = any(
        str((event.payload or {}).get("task_card_id") or "") == task_card_id
        and str((event.payload or {}).get("knowledge_id") or "") == knowledge_id
        and str((event.payload or {}).get("downstream_project_id") or "")
        == payload.project_id
        for event in launch_events
    )
    if not launch_found:
        raise HTTPException(status_code=409, detail="没有找到与该结果匹配的个性化学习启动记录")

    event = await record_event(
        db,
        learner_id=current.learner.id,
        event_type="personalized_learning_result_received",
        source="personalized_learning",
        payload={
            "task_card_id": task_card_id,
            "knowledge_id": knowledge_id,
            "entry_id": expected_entry_id,
            "downstream_project_id": payload.project_id,
            "result_type": payload.result_type,
            "result_id": payload.result_id,
            "assessment_type": assessment_type,
            "score": score,
            "total": total,
            "weak_point_count": weak_point_count,
            "formal_evidence": False,
            "feedback": str(summary.get("feedback") or "").strip()[:500],
        },
        artifact_refs=[
            f"learning-task:{task_card_id}",
            f"knowledge:{knowledge_id}",
            f"personalized-project:{payload.project_id}",
            f"assessment:{payload.result_id}",
        ],
        client_event_id=(
            f"personalized-result:{expected_entry_id}:{payload.result_id}"
        ),
    )
    await db.commit()
    return {
        "status": "accepted",
        "event_id": event.id,
        "result_id": payload.result_id,
        "formal_evidence": False,
    }


@router.post("/downstream-feedback")
async def submit_personalized_learning_feedback(
    payload: dict[str, Any] = Body(...),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    issues = payload.get("issues")
    if issues is None:
        issues = []
    elif not isinstance(issues, list):
        raise HTTPException(status_code=422, detail="issues 必须是数组")
    try:
        result = await _gateway().submit_downstream_feedback(payload)
        task_card_id = str(payload.get("task_card_id") or "")
        await record_event(
            db,
            learner_id=current.learner.id,
            event_type="learning_work_task_review_submitted",
            source="learning_task_conversion",
            payload={
                "task_card_id": task_card_id,
                "issue_count": len(issues),
                "status": str(payload.get("status") or ""),
            },
            artifact_refs=([f"learning-task:{task_card_id}"] if task_card_id else []),
            client_event_id=str(payload.get("correlation_id") or uuid4()),
        )
        await db.commit()
        return result
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)
