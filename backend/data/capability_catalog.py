"""计算机信息技术专业群能力包目录。

目录用于识别专业方向、呈现可学习范围和生成参考学习路径。除 Java 面向对象
示范包外，其余方向尚未完成来源、题库和实操 Rubric 的正式验收，不能用于
正式诊断或掌握度结论。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


CATALOG_SCHEMA_VERSION = 1
FORMAL_SUPPORT_LEVEL = "validated_graph"
REFERENCE_SUPPORT_LEVEL = "reference_catalog"

PROFESSIONAL_GROUP: dict[str, str] = {
    "group_id": "computer-information-technology",
    "group_name": "计算机信息技术专业群",
    "industry_context": "软件和信息技术服务业",
    "catalog_notice": (
        "目录覆盖项目已明确的群内专业。课程范围用于目标澄清和参考学习；"
        "正式测评、画像与掌握度只向完成能力包验收的方向开放。"
    ),
}


def _module(
    module_id: str,
    name: str,
    knowledge_type: str,
    outcome: str,
    prerequisites: list[str] | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "knowledge_point_name": name,
        "knowledge_type": knowledge_type,
        "learning_outcome": outcome,
        "prerequisites": prerequisites or [],
        "keywords": keywords or [],
    }


CAPABILITY_PACKS: dict[str, dict[str, Any]] = {
    "PACK-SOFTWARE-JAVA-OOP": {
        "pack_id": "PACK-SOFTWARE-JAVA-OOP",
        "professional_id": "software-technology",
        "professional_name": "软件技术",
        "professional_code": "510203",
        "title": "Java 应用开发 · 面向对象实训",
        "support_level": FORMAL_SUPPORT_LEVEL,
        "support_label": "正式能力包",
        "content_status": "validated_graph",
        "content_notice": "当前首个正式示范包；讲解来源和题库仍按各自审核状态展示。",
        "roles": ["Java 应用开发工程师"],
        "courses": ["Java 面向对象程序设计", "集合与异常处理", "文件输入输出", "成绩管理实训"],
        "input_examples": ["我想学习 Java 面向对象", "完成 Java 成绩管理实训"],
        "keywords": ["java", "java面向对象", "面向对象", "成绩管理", "java实训"],
        "modules": [
            _module("java-class", "类的定义与对象创建", "code", "定义类并创建对象。"),
            _module("java-encapsulation", "封装与访问控制", "conceptual", "为对象状态设计受控访问接口。", ["java-class"]),
            _module("java-inheritance", "继承与方法重写", "code", "实现带 @Override 的子类行为。", ["java-encapsulation"]),
            _module("java-polymorphism", "多态与接口", "conceptual", "用接口引用替换具体实现。", ["java-inheritance"]),
            _module("java-collection", "集合与泛型", "code", "创建并遍历带泛型的集合。", ["java-class"]),
            _module("java-exception", "异常处理", "code", "处理可预期的异常路径。", ["java-class"]),
            _module("java-io", "输入输出流", "code", "安全读取文本并关闭资源。", ["java-collection", "java-exception"]),
        ],
    },
    "PACK-SOFTWARE-ENGINEERING": {
        "pack_id": "PACK-SOFTWARE-ENGINEERING",
        "professional_id": "software-technology",
        "professional_name": "软件技术",
        "professional_code": "510203",
        "title": "软件开发与工程实践",
        "support_level": REFERENCE_SUPPORT_LEVEL,
        "support_label": "参考学习目录",
        "content_status": "reference_outline",
        "content_notice": "课程范围已纳入目录；正式来源、题库和实操 Rubric 尚待逐模块验收。",
        "roles": ["Web 前端工程师", "软件测试工程师", "初级软件开发工程师"],
        "courses": ["程序设计基础", "Web 前端开发", "数据库应用", "软件测试", "软件工程", "版本管理与部署"],
        "input_examples": ["我想学习软件技术", "学习 Web 前端和软件测试"],
        "keywords": ["软件技术", "软件工程", "软件测试", "web前端", "前端开发", "版本控制", "持续集成", "springboot"],
        "modules": [
            _module("software-programming", "程序设计与问题分解", "code", "把需求拆成可运行的程序模块。"),
            _module("software-web", "Web 页面、交互与接口基础", "code", "完成页面交互并调用接口。", ["software-programming"]),
            _module("software-database", "关系数据库与 SQL", "code", "设计基础表结构并完成增删改查。", ["software-programming"]),
            _module("software-testing", "测试用例与缺陷定位", "practice", "为核心功能编写测试用例并记录缺陷。", ["software-web", "software-database"]),
            _module("software-engineering", "需求、设计与协作规范", "conceptual", "用需求、接口和任务拆分描述一个小型项目。", ["software-programming"]),
            _module("software-versioning", "Git 协作与持续交付基础", "practice", "完成一次分支协作、提交和发布前检查。", ["software-testing", "software-engineering"]),
            _module("software-project", "软件项目综合实践", "project", "交付一个包含页面、数据、测试和说明的小项目。", ["software-versioning"]),
        ],
    },
    "PACK-COMPUTER-APPLICATION": {
        "pack_id": "PACK-COMPUTER-APPLICATION",
        "professional_id": "computer-application-technology",
        "professional_name": "计算机应用技术",
        "professional_code": "510201",
        "title": "计算机应用与系统支持",
        "support_level": REFERENCE_SUPPORT_LEVEL,
        "support_label": "参考学习目录",
        "content_status": "reference_outline",
        "content_notice": "课程范围已纳入目录；正式来源、题库和实操 Rubric 尚待逐模块验收。",
        "roles": ["应用系统实施员", "信息技术支持员", "应用开发助理"],
        "courses": ["计算机组成与维护", "操作系统应用", "办公与协作工具", "应用系统开发", "数据库应用", "系统部署与维护"],
        "input_examples": ["我想学习计算机应用技术", "学习计算机系统维护和应用开发"],
        "keywords": ["计算机应用技术", "计算机应用", "系统维护", "计算机组装", "办公自动化", "应用系统开发", "信息技术支持"],
        "modules": [
            _module("application-hardware", "计算机组成、外设与安全操作", "conceptual", "识别常见硬件部件并完成安全检查。"),
            _module("application-os", "操作系统、文件与账号管理", "practice", "完成文件组织、账户权限和基础排错。", ["application-hardware"]),
            _module("application-office", "办公协作与信息处理", "practice", "按任务规范完成数据整理、文档和协作交付。", ["application-os"]),
            _module("application-network", "网络接入与常见故障排查", "practice", "定位本机网络、服务访问和基础配置问题。", ["application-os"]),
            _module("application-development", "应用页面、数据与接口基础", "code", "完成一个带数据输入输出的应用功能。", ["application-office", "application-network"]),
            _module("application-deployment", "应用部署、备份与维护", "practice", "完成一次部署、备份和故障复盘。", ["application-development"]),
            _module("application-project", "应用系统实施综合任务", "project", "交付可使用的应用配置或小型信息系统。", ["application-deployment"]),
        ],
    },
    "PACK-COMPUTER-NETWORK": {
        "pack_id": "PACK-COMPUTER-NETWORK",
        "professional_id": "computer-network-technology",
        "professional_name": "计算机网络技术",
        "professional_code": "510202",
        "title": "计算机网络构建与运维",
        "support_level": REFERENCE_SUPPORT_LEVEL,
        "support_label": "参考学习目录",
        "content_status": "reference_outline",
        "content_notice": "课程范围已纳入目录；正式来源、题库和实操 Rubric 尚待逐模块验收。",
        "roles": ["网络管理员", "网络运维工程师", "网络安全运维助理"],
        "courses": ["计算机网络基础", "TCP/IP", "交换与路由", "网络服务", "无线网络", "网络安全", "网络自动化运维"],
        "input_examples": ["我想学习计算机网络技术", "学习交换路由和网络运维"],
        "keywords": ["计算机网络", "网络技术", "交换路由", "交换机", "路由器", "网络运维", "网络管理", "tcp/ip", "网络安全"],
        "modules": [
            _module("network-foundation", "网络分层、地址与常用协议", "conceptual", "解释网络分层并完成基础 IP 规划。"),
            _module("network-switching", "以太网交换、VLAN 与二层排错", "practice", "配置 VLAN 并定位二层连通问题。", ["network-foundation"]),
            _module("network-routing", "IP 路由与三层互联", "practice", "配置基础路由并验证跨网段连通。", ["network-foundation"]),
            _module("network-services", "DNS、DHCP 与常用网络服务", "practice", "部署并验证基础网络服务。", ["network-routing"]),
            _module("network-wireless", "无线接入与终端连接", "practice", "完成无线接入配置并排查连接问题。", ["network-services"]),
            _module("network-security", "网络边界、安全基线与日志", "conceptual", "识别最小权限、访问控制和日志审计要点。", ["network-routing"]),
            _module("network-automation", "网络监控与自动化运维基础", "code", "使用脚本或工具采集状态并输出巡检结果。", ["network-services", "network-security"]),
            _module("network-project", "网络部署与运维综合任务", "project", "交付网络拓扑、配置、验证记录和故障复盘。", ["network-automation"]),
        ],
    },
    "PACK-BIG-DATA": {
        "pack_id": "PACK-BIG-DATA",
        "professional_id": "big-data-technology",
        "professional_name": "大数据技术",
        "professional_code": "510206",
        "title": "数据开发、分析与治理",
        "support_level": REFERENCE_SUPPORT_LEVEL,
        "support_label": "参考学习目录",
        "content_status": "reference_outline",
        "content_notice": "课程范围已纳入目录；正式来源、题库和实操 Rubric 尚待逐模块验收。",
        "roles": ["数据开发工程师", "数据分析助理", "数据平台运维助理"],
        "courses": ["Linux 基础", "Python 数据处理", "SQL", "数据采集与 ETL", "数据仓库", "分布式计算", "数据可视化", "数据治理"],
        "input_examples": ["我想学习大数据技术", "学习数据工程和 Spark"],
        "keywords": ["大数据", "数据工程", "数据仓库", "hadoop", "spark", "flink", "etl", "kafka", "数据治理"],
        "modules": [
            _module("data-linux", "Linux、命令行与数据工作环境", "practice", "在命令行中管理数据文件和运行环境。"),
            _module("data-python", "Python 数据处理基础", "code", "读取、转换并检查结构化数据。", ["data-linux"]),
            _module("data-sql", "SQL 查询与关系数据建模", "code", "编写多表查询并解释数据口径。", ["data-linux"]),
            _module("data-etl", "数据采集、清洗与 ETL", "practice", "完成一条可复用的数据清洗流程。", ["data-python", "data-sql"]),
            _module("data-warehouse", "数据仓库与指标建模", "conceptual", "设计基础主题域、维度和指标口径。", ["data-etl"]),
            _module("data-computing", "分布式计算与任务调度", "code", "说明并提交一个批处理或流处理任务。", ["data-warehouse"]),
            _module("data-visualization", "数据分析与可视化表达", "practice", "用图表清楚表达指标变化和结论边界。", ["data-etl"]),
            _module("data-governance", "数据质量、安全与治理", "conceptual", "制定数据质量检查和访问边界。", ["data-warehouse", "data-visualization"]),
            _module("data-project", "数据分析与工程综合项目", "project", "交付可复现的数据处理、分析和说明报告。", ["data-computing", "data-governance"]),
        ],
    },
    "PACK-AI-APPLICATION": {
        "pack_id": "PACK-AI-APPLICATION",
        "professional_id": "artificial-intelligence-technology-application",
        "professional_name": "人工智能技术应用",
        "professional_code": "510209",
        "title": "人工智能应用开发与部署",
        "support_level": REFERENCE_SUPPORT_LEVEL,
        "support_label": "参考学习目录",
        "content_status": "reference_outline",
        "content_notice": "课程范围已纳入目录；正式来源、题库和实操 Rubric 尚待逐模块验收。",
        "roles": ["人工智能应用工程师", "模型部署助理", "智能应用开发助理"],
        "courses": ["Python", "数学与数据基础", "机器学习", "深度学习", "计算机视觉", "自然语言处理", "模型部署", "AI 安全与伦理"],
        "input_examples": ["我想学习人工智能技术应用", "学习机器学习和计算机视觉"],
        "keywords": ["人工智能", "机器学习", "深度学习", "神经网络", "计算机视觉", "图像识别", "自然语言处理", "大模型", "模型部署"],
        "modules": [
            _module("ai-python", "Python、数据结构与科学计算基础", "code", "使用 Python 完成数据读取、处理和函数封装。"),
            _module("ai-math", "数据、概率统计与模型评价基础", "conceptual", "解释训练数据、指标和基本评价结果。", ["ai-python"]),
            _module("ai-ml", "机器学习建模流程", "code", "完成数据划分、训练、预测和基础评估。", ["ai-math"]),
            _module("ai-dl", "深度学习网络与训练过程", "conceptual", "解释网络、损失、优化和过拟合现象。", ["ai-ml"]),
            _module("ai-vision", "计算机视觉应用", "practice", "完成一个图像分类或检测应用的基础验证。", ["ai-dl"]),
            _module("ai-nlp", "自然语言处理与大模型应用", "practice", "设计带输入边界和结果验证的文本处理任务。", ["ai-dl"]),
            _module("ai-deployment", "模型服务、部署与监控", "practice", "将模型封装为可调用服务并记录运行状态。", ["ai-vision", "ai-nlp"]),
            _module("ai-governance", "AI 安全、伦理与数据合规", "conceptual", "识别数据、偏差、隐私和人工复核边界。", ["ai-math"]),
            _module("ai-project", "智能应用综合项目", "project", "交付一个含数据说明、模型调用、验证和风险说明的智能应用。", ["ai-deployment", "ai-governance"]),
        ],
    },
}


PROFESSIONALS: tuple[dict[str, Any], ...] = (
    {
        "professional_id": "software-technology",
        "professional_name": "软件技术",
        "professional_code": "510203",
        "overview": "面向软件开发、测试和工程协作的共性能力。",
        "pack_ids": ("PACK-SOFTWARE-JAVA-OOP", "PACK-SOFTWARE-ENGINEERING"),
    },
    {
        "professional_id": "computer-application-technology",
        "professional_name": "计算机应用技术",
        "professional_code": "510201",
        "overview": "面向应用系统使用、实施、维护与基础开发能力。",
        "pack_ids": ("PACK-COMPUTER-APPLICATION",),
    },
    {
        "professional_id": "computer-network-technology",
        "professional_name": "计算机网络技术",
        "professional_code": "510202",
        "overview": "面向网络构建、服务配置、安全和运维能力。",
        "pack_ids": ("PACK-COMPUTER-NETWORK",),
    },
    {
        "professional_id": "big-data-technology",
        "professional_name": "大数据技术",
        "professional_code": "510206",
        "overview": "面向数据开发、分析、分布式处理和治理能力。",
        "pack_ids": ("PACK-BIG-DATA",),
    },
    {
        "professional_id": "artificial-intelligence-technology-application",
        "professional_name": "人工智能技术应用",
        "professional_code": "510209",
        "overview": "面向智能应用开发、模型调用、部署和风险治理能力。",
        "pack_ids": ("PACK-AI-APPLICATION",),
    },
)


def is_formal_support_level(value: str) -> bool:
    return str(value or "") == FORMAL_SUPPORT_LEVEL


def _public_pack(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(pack[key])
        for key in (
            "pack_id",
            "professional_id",
            "professional_name",
            "professional_code",
            "title",
            "support_level",
            "support_label",
            "content_status",
            "content_notice",
            "roles",
            "courses",
            "input_examples",
            "modules",
        )
    }


def public_capability_catalog() -> dict[str, Any]:
    """Return the user-facing professional-group catalog without matcher rules."""
    programs = []
    for professional in PROFESSIONALS:
        programs.append({
            key: deepcopy(professional[key])
            for key in (
                "professional_id",
                "professional_name",
                "professional_code",
                "overview",
            )
        } | {
            "capability_packs": [
                _public_pack(CAPABILITY_PACKS[pack_id])
                for pack_id in professional["pack_ids"]
            ],
        })
    return {
        "status": "ok",
        "schema_version": CATALOG_SCHEMA_VERSION,
        "professional_group": deepcopy(PROFESSIONAL_GROUP),
        "programs": programs,
    }


def get_capability_pack(pack_id: str) -> dict[str, Any] | None:
    pack = CAPABILITY_PACKS.get(str(pack_id or "").strip())
    return deepcopy(pack) if pack else None


def match_capability_pack(text: str) -> dict[str, Any] | None:
    """Match a specific professional direction without treating generic terms as one."""
    normalized = "".join(str(text or "").casefold().split())
    if not normalized:
        return None
    candidates: list[tuple[int, int, str, list[str]]] = []
    for pack_id, pack in CAPABILITY_PACKS.items():
        matched = [
            keyword for keyword in pack["keywords"]
            if "".join(str(keyword).casefold().split()) in normalized
        ]
        if matched:
            candidates.append((
                len(matched),
                max(len(keyword) for keyword in matched),
                pack_id,
                matched,
            ))
    if not candidates:
        return None
    _, _, pack_id, matched = max(candidates, key=lambda item: (item[0], item[1], item[2]))
    pack = get_capability_pack(pack_id)
    if pack:
        pack["matched_keywords"] = matched
    return pack


def reference_path_nodes(
    pack: dict[str, Any], goal_name: str, target_outcome: str = ""
) -> list[dict[str, Any]]:
    """Build a deterministic, non-formal DAG from a reference catalog pack."""
    nodes = []
    for module in pack.get("modules", []):
        module_name = str(module.get("knowledge_point_name") or "").strip()
        if not module_name:
            continue
        outcome = str(module.get("learning_outcome") or "").strip()
        if target_outcome and module.get("knowledge_type") == "project":
            outcome = f"{outcome} 最终产出对齐“{target_outcome}”。"
        nodes.append({
            "node_key": str(module.get("module_id") or "").strip(),
            "knowledge_point_name": module_name,
            "knowledge_type": str(module.get("knowledge_type") or "conceptual"),
            "prerequisites": list(module.get("prerequisites") or []),
            "goal_connection": (
                f"“{module_name}”是完成“{goal_name}”所需的"
                f"{pack.get('professional_name', '专业')}能力模块。"
            ),
            "learning_outcome": outcome,
            "video_context_keywords": [
                module_name,
                str(pack.get("professional_name") or ""),
                *list(module.get("keywords") or []),
            ],
        })
    return nodes
