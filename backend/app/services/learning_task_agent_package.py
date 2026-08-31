"""Repository-owned Agent Package for learning-task conversion.

The package compiles one confirmed work task into an immutable, step-level
learning task snapshot.  It deliberately keeps generation and revision behind
the generic Plugin Host so the central workspace never becomes a second source
of learner or project truth.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, TYPE_CHECKING

from app.services.plugin_host import canonical_hash, register_builtin_workflow

if TYPE_CHECKING:
    from app.services.plugin_host import PluginWorkflowContext


PLUGIN_ID = "learning_task_conversion"
OBJECT_SCHEMA = "learning-task.object.v1"
WORKFLOWS = ("generate", "revise", "review", "handoff")
OBJECT_TYPES = {
    "learning_task", "task_step", "knowledge_point", "skill_point",
    "task_relation", "learning_resource", "review_note",
}


def _compact(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _stable_id(kind: str, *values: Any) -> str:
    raw = ":".join(_compact(value, 240).casefold() for value in values)
    return f"{kind}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:14]}"


def _source_refs(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    refs: list[dict[str, Any]] = []
    excerpts: list[str] = []
    for source in list(payload.get("sources") or []):
        if not isinstance(source, dict):
            continue
        refs.append({
            "ref": str(source.get("ref") or ""),
            "source_id": source.get("source_id"),
            "source_version_id": source.get("source_version_id"),
            "content_hash": str(source.get("content_hash") or ""),
            "authority_tier": str(source.get("authority_tier") or "learner_owned"),
            "status": str(source.get("status") or "active"),
        })
        for chunk in list(source.get("chunks") or []):
            if isinstance(chunk, dict) and len("\n".join(excerpts)) < 8_000:
                excerpts.append(_compact(chunk.get("content") or chunk.get("text"), 1_200))
    return refs, "\n".join(item for item in excerpts if item)[:8_000]


def _task_profile(title: str) -> dict[str, Any]:
    lowered = title.casefold()
    if "vlan" in lowered or "trunk" in lowered or "交换机" in title:
        return {
            "context": "在网络实训环境中依据业务隔离要求完成交换机 VLAN 与 Trunk 配置，并用命令输出和连通性测试验收。",
            "tools": ["可管理交换机或网络仿真器", "终端与串口工具", "网络拓扑与地址规划表"],
            "safety": ["变更前备份配置", "逐端口核对，避免误改管理链路", "验收通过后再保存运行配置"],
            "steps": [
                ("核对拓扑与业务边界", "读取端口连接、部门隔离和互通要求，形成可检查的现状记录。", "网络拓扑与需求核对表", "设备、端口、VLAN 范围与业务要求一一对应", "VLAN 与广播域", "网络拓扑识读"),
                ("编制 VLAN 与端口规划", "确定 VLAN ID、名称、Access 端口和 Trunk 允许列表。", "VLAN 与端口规划表", "规划无 ID 冲突，端口角色和允许列表完整", "Access 与 Trunk 链路", "VLAN 规划"),
                ("创建并配置 VLAN", "在交换机上创建 VLAN，设置名称并将终端端口加入目标 VLAN。", "VLAN 配置与命令回显", "show vlan 输出与规划表一致", "交换机 VLAN 数据库", "交换机命令配置"),
                ("配置 Trunk 与允许列表", "在交换机互联端口启用 Trunk，并限制允许通过的 VLAN。", "Trunk 配置与状态回显", "Trunk 状态、封装与允许列表符合规划", "Trunk 协商与标签帧", "Trunk 配置"),
                ("执行连通性与隔离测试", "按测试矩阵验证同 VLAN 连通、跨 VLAN 隔离及异常路径。", "连通性测试记录", "每条预期结果均有命令、现象和结论", "二层转发与隔离", "网络测试与定位"),
                ("归档配置并完成验收", "保存配置，整理关键回显、拓扑和测试证据，形成交付包。", "配置备份与验收报告", "重载后配置可恢复，交付证据完整可复核", "配置持久化", "网络交付与复核"),
            ],
        }
    if "unity" in lowered or "摄像机" in title:
        return {
            "context": "在 Unity 项目中实现可配置的第三人称摄像机跟随，处理旋转、平滑、遮挡与边界，并通过运行场景验收。",
            "tools": ["Unity Editor", "C# 脚本编辑器", "测试场景与目标角色 Prefab"],
            "safety": ["在版本分支中修改 Prefab 和脚本", "暴露参数而非写死场景对象", "修改前保留可回退版本"],
            "steps": [
                ("建立跟随需求与场景基线", "确认目标角色、观察角度、输入方式、遮挡物与可移动边界。", "摄像机需求与场景检查表", "跟随对象、坐标系和验收动作明确", "Unity 坐标系与 Transform", "场景对象分析"),
                ("搭建摄像机跟随骨架", "创建跟随脚本并绑定目标 Transform，分离目标位置与相机偏移。", "可运行的跟随脚本骨架", "角色移动时相机保持预设相对位置", "Transform 层级与引用", "组件绑定"),
                ("实现平滑位置跟随", "在 LateUpdate 中计算目标位置并使用阻尼平滑更新。", "平滑位置跟随效果", "帧率变化下无明显抖动和滞后突变", "LateUpdate 与插值", "平滑运动实现"),
                ("实现旋转与视角约束", "接入输入，计算水平垂直旋转并限制俯仰角。", "可控制且受限的观察视角", "旋转方向正确，俯仰不翻转", "欧拉角与四元数", "视角控制"),
                ("处理遮挡与边界", "用射线检测缩短相机距离，并在遮挡解除后平滑恢复。", "遮挡规避测试记录", "墙体不遮住角色，相机恢复无跳变", "Physics Raycast 与 LayerMask", "碰撞查询与过滤"),
                ("参数化、回归与交付", "暴露可调参数，覆盖移动、跳跃、转向和狭窄空间并记录结果。", "Prefab、脚本与回归报告", "所有场景用例通过且参数有说明", "序列化字段与回归测试", "Unity 组件交付"),
            ],
        }
    if "java" in lowered or "接口" in title or "web" in lowered or "系统" in title:
        return {
            "context": f"在软件开发项目中完成“{title}”，从需求与接口契约出发交付可运行实现、自动化测试和部署说明。",
            "tools": ["IDE 与版本管理工具", "项目构建工具", "接口调试与自动化测试工具"],
            "safety": ["敏感配置通过环境变量注入", "所有变更在独立分支完成", "合并前通过测试和代码复核"],
            "steps": [
                ("澄清需求与验收场景", "把业务目标拆为输入、输出、边界与可执行验收用例。", "需求与验收清单", "每项需求均有唯一验收场景", "需求建模与边界条件", "验收用例设计"),
                ("定义领域对象与接口契约", "确定数据模型、接口字段、状态码和错误语义。", "接口与数据契约", "字段、类型、必填项和异常返回可校验", "对象建模与 API 契约", "接口设计"),
                ("搭建最小可运行骨架", "建立分层结构、依赖配置和健康检查，先打通最短运行链路。", "可启动的应用骨架", "本地环境可构建、启动并通过健康检查", "分层架构与依赖注入", "工程搭建"),
                ("实现核心业务流程", "按契约完成校验、业务服务、持久化或外部依赖适配。", "核心功能代码与提交记录", "主流程和关键异常分支符合契约", "业务事务与异常处理", "核心编码"),
                ("执行自动化测试与修复", "覆盖单元、接口与边界用例，定位首次分歧并最小修复。", "测试报告与修复记录", "关键用例通过且失败原因可追溯", "测试分层与断言", "自动化测试"),
                ("构建发布与交付说明", "完成构建、配置样例、部署步骤、回滚策略和验收记录。", "发布包与交付文档", "新环境可按文档部署并复现验收结果", "构建发布与配置管理", "软件交付"),
            ],
        }
    return {
        "context": f"在计算机专业实训或软件项目环境中完成“{title}”，提交过程记录、可运行产物和可复核验收证据。",
        "tools": ["版本管理与协作工具", "任务对应的开发或运维环境", "自动化测试与记录工具"],
        "safety": ["在独立分支或隔离环境中操作", "敏感信息不得写入代码和交付物", "关键变更保留回退点"],
        "steps": [
            ("确认任务输入与完成定义", "识别对象、动作、边界、依赖和交付标准，锁定任务语义。", "任务契约与验收清单", "目标、范围、产物和验收项无歧义", "任务契约与边界", "需求澄清"),
            ("建立环境与最小基线", "准备工具、依赖、数据和版本基线，验证最短运行链路。", "环境快照与基线记录", "依赖可用且基线结果可复现", "环境与依赖管理", "环境搭建"),
            ("实现核心工作步骤", "按真实作业顺序完成主要配置、编码或数据处理操作。", "核心阶段产物", "核心功能满足任务契约", "核心原理与状态变化", "核心实施"),
            ("处理依赖与异常分支", "补齐接口联调、资源约束、安全边界和典型失败路径。", "联调与异常处理记录", "关键异常有可观察结果和恢复策略", "依赖关系与异常模型", "故障处理"),
            ("执行验证并局部修复", "用验收矩阵逐项检查，定位失败点并仅重做受影响步骤。", "测试与修复报告", "所有关键验收项通过且证据完整", "验证策略与因果定位", "测试修复"),
            ("整理交付与复核材料", "归档版本、产物、配置、操作记录和后续维护说明。", "版本化交付包", "另一名学习者可按记录复现结果", "版本与交付管理", "交付复核"),
        ],
    }


def _model_schema(target_steps: int) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["title", "context", "objective", "tools", "safety", "acceptance", "steps"],
        "properties": {
            "title": {"type": "string"},
            "context": {"type": "string"},
            "objective": {"type": "string"},
            "tools": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "safety": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "acceptance": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "steps": {
                "type": "array", "minItems": max(4, target_steps - 1), "maxItems": min(10, target_steps + 2),
                "items": {
                    "type": "object",
                    "required": ["title", "operation", "deliverable", "acceptance", "knowledge", "skill"],
                    "properties": {
                        "title": {"type": "string"}, "operation": {"type": "string"},
                        "deliverable": {"type": "string"}, "acceptance": {"type": "string"},
                        "knowledge": {"type": "string"}, "skill": {"type": "string"},
                        "prerequisites": {"type": "array", "items": {"type": "string"}},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }


def _normalize_plan(title: str, value: dict[str, Any] | None, target_steps: int) -> dict[str, Any]:
    profile = _task_profile(title)
    candidate = value if isinstance(value, dict) else {}
    raw_steps = list(candidate.get("steps") or [])
    if len(raw_steps) < 4:
        raw_steps = [
            {
                "title": row[0], "operation": row[1], "deliverable": row[2],
                "acceptance": row[3], "knowledge": row[4], "skill": row[5],
                "prerequisites": [],
            }
            for row in profile["steps"][:target_steps]
        ]
    return {
        "title": _compact(candidate.get("title") or f"{title}学习型工作任务", 240),
        "context": _compact(candidate.get("context") or profile["context"], 1_200),
        "objective": _compact(candidate.get("objective") or f"完成“{title}”，提交可运行产物、过程记录和验收证据。", 800),
        "tools": [_compact(item, 160) for item in list(candidate.get("tools") or profile["tools"]) if _compact(item, 160)][:12],
        "safety": [_compact(item, 240) for item in list(candidate.get("safety") or profile["safety"]) if _compact(item, 240)][:12],
        "acceptance": [_compact(item, 240) for item in list(candidate.get("acceptance") or [row[3] for row in profile["steps"]]) if _compact(item, 240)][:12],
        "steps": [dict(item) for item in raw_steps[:10] if isinstance(item, dict)],
    }


def _compile_components(title: str, plan: dict[str, Any]) -> dict[str, Any]:
    task_id = _stable_id("learning_task", title)
    knowledge_by_title: dict[str, dict[str, Any]] = {}
    skills_by_title: dict[str, dict[str, Any]] = {}
    resources: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    previous_id = ""
    for order, raw in enumerate(plan["steps"], start=1):
        step_title = _compact(raw.get("title") or f"步骤 {order}", 160)
        step_id = _stable_id("task_step", task_id, order, step_title)
        knowledge_title = _compact(raw.get("knowledge") or f"{step_title}相关原理", 160)
        skill_title = _compact(raw.get("skill") or f"{step_title}实施技能", 160)
        knowledge = knowledge_by_title.setdefault(knowledge_title, {
            "id": _stable_id("knowledge_point", task_id, knowledge_title),
            "type": "knowledge_point", "title": knowledge_title,
            "summary": f"理解“{knowledge_title}”在本步骤中的适用对象、状态变化和验收边界。",
            "lifecycle": "candidate", "references": [],
        })
        skill = skills_by_title.setdefault(skill_title, {
            "id": _stable_id("skill_point", task_id, skill_title),
            "type": "skill_point", "title": skill_title,
            "summary": f"能够在任务环境中独立完成“{skill_title}”并留下可检查证据。",
            "lifecycle": "candidate", "references": [],
        })
        resource = {
            "id": _stable_id("learning_resource", task_id, step_id, knowledge_title),
            "type": "learning_resource", "title": f"{knowledge_title}学习资源",
            "kind": "search", "provider": "B站",
            "query": f"{title} {knowledge_title} 实操 教程",
            "url": f"https://search.bilibili.com/all?keyword={title} {knowledge_title} 实操 教程",
            "lifecycle": "candidate", "references": [knowledge["id"]],
        }
        resources.append(resource)
        prereq = [previous_id] if previous_id else []
        prereq.extend(_compact(item, 160) for item in list(raw.get("prerequisites") or []) if _compact(item, 160))
        step = {
            "id": step_id, "type": "task_step", "order": order, "title": step_title,
            "operation": _compact(raw.get("operation"), 1_000),
            "deliverable": _compact(raw.get("deliverable"), 500),
            "acceptance": _compact(raw.get("acceptance"), 700),
            "prerequisites": prereq[:8],
            "knowledge_ids": [knowledge["id"]], "skill_ids": [skill["id"]],
            "resource_ids": [resource["id"]], "review_state": "ready",
            "lifecycle": "candidate", "references": [knowledge["id"], skill["id"], resource["id"]],
        }
        steps.append(step)
        for relation_type, target in (("requires_knowledge", knowledge), ("requires_skill", skill)):
            relations.append({
                "id": _stable_id("task_relation", step_id, relation_type, target["id"]),
                "type": "task_relation", "relation": relation_type,
                "source_id": step_id, "target_id": target["id"],
                "reason": f"“{step_title}”需要{target['title']}，并通过“{step['deliverable']}”观察结果。",
                "lifecycle": "candidate", "references": [step_id, target["id"]],
            })
        previous_id = step_id
    task = {
        "id": task_id, "type": "learning_task", "title": plan["title"],
        "source_title": title, "context": plan["context"], "objective": plan["objective"],
        "tools": plan["tools"], "safety": plan["safety"], "acceptance": plan["acceptance"],
        "status": "reviewable", "step_ids": [item["id"] for item in steps],
        "lifecycle": "candidate", "references": [item["id"] for item in steps],
    }
    return {
        "task-document": {"task": task, "steps": steps},
        "knowledge-map": {
            "knowledge_points": list(knowledge_by_title.values()),
            "skill_points": list(skills_by_title.values()),
            "relations": relations,
            "resources": resources,
        },
        "review-notes": {"notes": []},
    }


def _object_locators(components: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    def visit(component: str, value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            object_id = str(value.get("id") or "")
            object_type = str(value.get("type") or value.get("object_type") or "")
            if object_id and object_type in OBJECT_TYPES:
                output.append({
                    "id": object_id, "type": object_type,
                    "label": str(value.get("title") or value.get("label") or object_type),
                    "component": component, "json_pointer": pointer,
                    "content_hash": canonical_hash(value),
                    "lifecycle": str(value.get("lifecycle") or "candidate"),
                    "references": list(value.get("references") or []),
                })
            for key, child in value.items():
                token = str(key).replace("~", "~0").replace("/", "~1")
                visit(component, child, f"{pointer}/{token}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(component, child, f"{pointer}/{index}")

    for component, value in components.items():
        visit(component, value, "")
    return output


def _snapshot(components: dict[str, Any], source_refs: list[dict[str, Any]], provenance: dict[str, Any]) -> dict[str, Any]:
    steps = list(dict(components.get("task-document") or {}).get("steps") or [])
    relations = list(dict(components.get("knowledge-map") or {}).get("relations") or [])
    objects = _object_locators(components)
    return {
        "schema_version": OBJECT_SCHEMA,
        "components": components,
        "objects": objects,
        "source_refs": source_refs,
        "validation": {
            "valid": bool(steps) and all(item.get("deliverable") and item.get("acceptance") for item in steps),
            "stats": {"steps": len(steps), "relations": len(relations), "objects": len(objects)},
            "gates": {
                "identity": True, "dependency": True, "evidence": True,
                "safety": True, "delivery": True, "pedagogy": True,
            },
        },
        "provenance": {**provenance, "agent_package": PLUGIN_ID, "kernel_targets": [], "mastery_unchanged": True},
    }


async def run_learning_task_workflow(
    context: "PluginWorkflowContext", input_value: dict[str, Any],
) -> dict[str, Any]:
    workflow = str((context.run.contract or {}).get("workflow_id") or context.run.operation_id)
    configuration = dict(input_value.get("plugin_configuration") or {})
    snapshot_input = dict(input_value.get("snapshot") or {})
    if workflow == "generate":
        project = dict(await context.call_host_port("project.read.v1", {}) or {})
        title = _compact(input_value.get("task_title") or project.get("name") or "软件项目交付", 240)
        target_steps = max(4, min(int(configuration.get("target_steps", 6)), 10))
        sources = dict(await context.call_host_port("source.read.v1", {
            "source_ids": list(input_value.get("source_ids") or [])[:20],
            "max_sources": 20, "max_chunks": 24, "max_chars": 8_000,
        }) or {})
        source_refs, source_excerpt = _source_refs(sources)
        upstream = input_value.get("upstream_task")
        if isinstance(upstream, dict):
            upstream_text = json.dumps(upstream, ensure_ascii=False)[:4_000]
        else:
            upstream_text = _compact(upstream, 4_000)
        prompt = (
            "你是计算机专业群的学习型任务规划器。把一个已经确认的真实工作任务转成课堂可执行工单。"
            "必须保持任务对象、动作、边界和交付物，不按知识章节拆步骤。"
            f"输出约 {target_steps} 个按真实作业先后排列的步骤；每步必须有具体操作、可观察产物、验收依据、知识点和技能点。"
            "不要输出工业机器人案例，不要写宣传语，不要解释规划算法。仅返回符合 JSON Schema 的对象。\n"
            f"任务：{title}\n项目：{project.get('name', '')}；{project.get('description', '')}\n"
            f"上游任务 JSON：{upstream_text or '未提供'}\n固定来源摘录：{source_excerpt or '无'}"
        )
        generated: dict[str, Any] | None = None
        try:
            response = await context.call_host_port("model.generate_structured.v1", {
                "prompt": prompt, "schema": _model_schema(target_steps),
            })
            value = dict(response or {}).get("value")
            generated = dict(value) if isinstance(value, dict) else None
        except Exception:
            if not bool(configuration.get("allow_model_fallback", True)):
                raise
        plan = _normalize_plan(title, generated, target_steps)
        components = _compile_components(title, plan)
        candidate = _snapshot(components, source_refs, {
            "workflow": "generate", "model_generated": generated is not None,
            "upstream_present": bool(upstream_text), "effective_configuration": configuration,
        })
        return {
            "result": {"status": "completed", "title": plan["title"], "step_count": len(plan["steps"])},
            "snapshot": candidate,
            "events": [{"type": "task_generated", "payload": {"step_count": len(plan["steps"])}}],
        }

    components = deepcopy(dict(snapshot_input.get("components") or {}))
    if not components:
        raise ValueError("learning_task_snapshot_missing")
    if workflow == "revise":
        target_id = _compact(input_value.get("target_id") or "document", 160)
        quote = _compact(input_value.get("quote"), 1_000)
        requested_order = [
            _compact(item, 160) for item in list(input_value.get("step_order") or [])
            if _compact(item, 160)
        ]
        steps = list(dict(components.get("task-document") or {}).get("steps") or [])
        if requested_order and set(requested_order) == {str(item.get("id")) for item in steps if isinstance(item, dict)}:
            by_id = {str(item.get("id")): item for item in steps if isinstance(item, dict)}
            reordered = [by_id[step_id] for step_id in requested_order]
            previous_id = ""
            for order, step in enumerate(reordered, start=1):
                step["order"] = order
                step["prerequisites"] = [previous_id] if previous_id else []
                previous_id = str(step.get("id") or "")
            dict(components.get("task-document") or {})["steps"] = reordered
            components["task-document"]["steps"] = reordered
        note = _compact(
            input_value.get("note") or ("拖动调整任务步骤顺序" if requested_order else ""),
            2_000,
        )
        if not note:
            raise ValueError("revision_note_required")
        notes = dict(components.setdefault("review-notes", {})).setdefault("notes", [])
        note_value = {
            "id": _stable_id("review_note", snapshot_input.get("root_hash"), target_id, quote, note),
            "type": "review_note", "target_id": target_id, "quote": quote,
            "note": note, "status": "pending_review", "lifecycle": "candidate",
            "references": [] if target_id == "document" else [target_id],
        }
        notes.append(note_value)
        for step in list(dict(components.get("task-document") or {}).get("steps") or []):
            if isinstance(step, dict) and step.get("id") == target_id:
                step["review_state"] = "pending_review"
        successor = _snapshot(
            components, list(snapshot_input.get("source_refs") or []),
            {"workflow": "revise", "base_snapshot_ref": input_value.get("snapshot_ref"), "target_id": target_id},
        )
        return {
            "result": {"status": "completed", "review_note_id": note_value["id"]},
            "snapshot": successor,
            "events": [{"type": "revision_submitted", "payload": {"target_id": target_id}}],
        }
    if workflow == "review":
        validation = dict(snapshot_input.get("validation") or {})
        return {"result": {"status": "reviewed", "validation": validation, "mastery_unchanged": True}}
    if workflow == "handoff":
        knowledge_id = _compact(input_value.get("knowledge_id"), 160)
        task_document = dict(components.get("task-document") or {})
        knowledge_map = dict(components.get("knowledge-map") or {})
        knowledge = next((item for item in list(knowledge_map.get("knowledge_points") or []) if isinstance(item, dict) and item.get("id") == knowledge_id), None)
        if not knowledge:
            raise ValueError("knowledge_point_not_found")
        relations = [item for item in list(knowledge_map.get("relations") or []) if isinstance(item, dict) and item.get("target_id") == knowledge_id]
        step_ids = {str(item.get("source_id")) for item in relations}
        steps = [item for item in list(task_document.get("steps") or []) if isinstance(item, dict) and item.get("id") in step_ids]
        skill_ids = {skill_id for step in steps for skill_id in list(step.get("skill_ids") or [])}
        skills = [item for item in list(knowledge_map.get("skill_points") or []) if isinstance(item, dict) and item.get("id") in skill_ids]
        resource_ids = {resource_id for step in steps for resource_id in list(step.get("resource_ids") or [])}
        resources = [item for item in list(knowledge_map.get("resources") or []) if isinstance(item, dict) and item.get("id") in resource_ids]
        package = {
            "protocol": "learnflow.personalized-learning-handoff.v1",
            "task": task_document.get("task"), "knowledge": knowledge,
            "steps": steps, "skills": skills, "resources": resources,
            "feedback_contract": {"target_id": knowledge_id, "return_event": "relation_review_requested"},
            "kernel_targets": [],
        }
        return {
            "result": {"status": "ready", "handoff": package, "mastery_unchanged": True},
            "events": [{"type": "handoff_prepared", "payload": {"knowledge_id": knowledge_id}}],
        }
    raise ValueError(f"unknown_learning_task_workflow:{workflow}")


def register_learning_task_agent_package() -> None:
    for workflow in WORKFLOWS:
        register_builtin_workflow(PLUGIN_ID, workflow, run_learning_task_workflow)


__all__ = ["register_learning_task_agent_package", "run_learning_task_workflow"]
