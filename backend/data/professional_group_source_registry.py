"""计算机信息技术专业群的候选来源登记清单。

清单只登记公开权威来源及其适用模块，不包含可直接发布的讲义正文。所有记录
初始均为 ``pending``，须由课程负责人或指定专业教师核验来源版本、定位和摘录后，
再经 ``source_documents`` / ``knowledge_candidates`` 审核流程发布为本地知识条目。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.data.capability_catalog import CAPABILITY_PACKS
from backend.data.teaching_contract_drafts import get_teaching_contract_draft


SOURCE_REGISTRY_VERSION = "professional-group-source-registry-v1"
PENDING_REVIEW = "pending"
REVIEW_GUIDANCE = (
    "来源登记不等于知识条目审核通过。需核验版本、适用范围、定位符与摘录，"
    "并补齐定义、步骤、示例、练习与 Rubric 后才能升级为正式能力包。"
)


def _source(
    document_id: str,
    title: str,
    source_type: str,
    source_url: str,
    locator: str,
    authority: str,
) -> dict[str, str]:
    return {
        "document_id": document_id,
        "title": title,
        "source_type": source_type,
        "source_url": source_url,
        "locator": locator,
        "authority": authority,
    }


_SOURCES = {
    "software-programming": _source("SRC-OPENJDK-JAVA", "OpenJDK Java 文档", "official_document", "https://docs.oracle.com/en/java/", "Java SE API 与语言基础章节", "Oracle / OpenJDK"),
    "java-class": _source("SRC-ORACLE-JAVA-TUTORIAL", "Oracle Java Documentation", "official_document", "https://docs.oracle.com/en/java/", "Classes and Objects", "Oracle"),
    "java-encapsulation": _source("SRC-ORACLE-JAVA-TUTORIAL", "Oracle Java Documentation", "official_document", "https://docs.oracle.com/en/java/", "Controlling Access to Members", "Oracle"),
    "java-inheritance": _source("SRC-ORACLE-JAVA-TUTORIAL", "Oracle Java Documentation", "official_document", "https://docs.oracle.com/en/java/", "Inheritance", "Oracle"),
    "java-polymorphism": _source("SRC-ORACLE-JAVA-TUTORIAL", "Oracle Java Documentation", "official_document", "https://docs.oracle.com/en/java/", "Interfaces and Inheritance", "Oracle"),
    "java-collection": _source("SRC-ORACLE-JAVA-TUTORIAL", "Oracle Java Documentation", "official_document", "https://docs.oracle.com/en/java/", "Collections Framework", "Oracle"),
    "java-exception": _source("SRC-ORACLE-JAVA-TUTORIAL", "Oracle Java Documentation", "official_document", "https://docs.oracle.com/en/java/", "Exceptions", "Oracle"),
    "java-io": _source("SRC-ORACLE-JAVA-TUTORIAL", "Oracle Java Documentation", "official_document", "https://docs.oracle.com/en/java/", "Basic I/O", "Oracle"),
    "software-web": _source("SRC-MDN-WEB", "MDN Web Docs", "official_document", "https://developer.mozilla.org/zh-CN/docs/Learn_web_development", "Learn web development：HTML、CSS、JavaScript 与 Web API", "MDN / Mozilla"),
    "software-database": _source("SRC-POSTGRES-SQL", "PostgreSQL Documentation", "official_document", "https://www.postgresql.org/docs/current/", "SQL Language 与 Tutorial", "PostgreSQL Global Development Group"),
    "software-testing": _source("SRC-ISTQB-GLOSSARY", "ISTQB Glossary", "industry_standard", "https://glossary.istqb.org/", "测试、缺陷、测试用例术语", "ISTQB"),
    "software-engineering": _source("SRC-SWEBOK", "SWEBOK Guide", "industry_standard", "https://www.computer.org/education/bodies-of-knowledge/software-engineering", "Software Engineering Fundamentals", "IEEE Computer Society"),
    "software-versioning": _source("SRC-GIT-BOOK", "Pro Git", "official_document", "https://git-scm.com/book/zh/v2", "Git 分支、协作与远程仓库章节", "Git SCM"),
    "software-project": _source("SRC-SWEBOK", "SWEBOK Guide", "industry_standard", "https://www.computer.org/education/bodies-of-knowledge/software-engineering", "工程过程、质量与配置管理章节", "IEEE Computer Society"),
    "application-hardware": _source("SRC-EDU-CATALOG", "职业教育专业目录（2021年）", "government_document", "https://www.moe.gov.cn/srcsite/A07/moe_953/202103/t20210319_521135.html", "计算机应用技术专业简介", "教育部"),
    "application-os": _source("SRC-MICROSOFT-WINDOWS", "Microsoft Windows 文档", "official_document", "https://learn.microsoft.com/zh-cn/windows/", "Windows 管理与安全文档", "Microsoft"),
    "application-office": _source("SRC-MICROSOFT-365", "Microsoft 365 培训", "official_document", "https://support.microsoft.com/zh-cn/training", "Office 与协作培训主题", "Microsoft"),
    "application-network": _source("SRC-CISCO-NETWORK", "Cisco Networking Academy Skills for All", "official_course", "https://www.netacad.com/", "网络基础与故障排查课程单元", "Cisco"),
    "application-development": _source("SRC-MDN-WEB", "MDN Web Docs", "official_document", "https://developer.mozilla.org/zh-CN/docs/Learn_web_development", "前端、表单与 Web API 学习路径", "MDN / Mozilla"),
    "application-deployment": _source("SRC-MICROSOFT-LEARN", "Microsoft Learn", "official_course", "https://learn.microsoft.com/zh-cn/training/", "部署、备份和运维学习模块", "Microsoft"),
    "application-project": _source("SRC-EDU-CATALOG", "职业教育专业目录（2021年）", "government_document", "https://www.moe.gov.cn/srcsite/A07/moe_953/202103/t20210319_521135.html", "计算机应用技术专业简介与岗位能力范围", "教育部"),
    "network-foundation": _source("SRC-RFC-8200", "RFC 8200: IPv6 Specification", "internet_standard", "https://www.rfc-editor.org/rfc/rfc8200", "Internet Protocol Version 6 Specification", "IETF"),
    "network-switching": _source("SRC-CISCO-NETWORK", "Cisco Networking Academy Skills for All", "official_course", "https://www.netacad.com/", "交换、VLAN 与二层通信课程单元", "Cisco"),
    "network-routing": _source("SRC-RFC-1812", "RFC 1812: Requirements for IP Version 4 Routers", "internet_standard", "https://www.rfc-editor.org/rfc/rfc1812", "IP 路由器要求", "IETF"),
    "network-services": _source("SRC-RFC-1035", "RFC 1035: Domain Names", "internet_standard", "https://www.rfc-editor.org/rfc/rfc1035", "DNS 实现与规范章节", "IETF"),
    "network-wireless": _source("SRC-CISCO-NETWORK", "Cisco Networking Academy Skills for All", "official_course", "https://www.netacad.com/", "无线接入课程单元", "Cisco"),
    "network-security": _source("SRC-NIST-CSF", "NIST Cybersecurity Framework 2.0", "government_standard", "https://www.nist.gov/cyberframework", "Govern、Protect、Detect 等核心功能", "NIST"),
    "network-automation": _source("SRC-NAPALM-DOCS", "NAPALM Documentation", "official_document", "https://napalm.readthedocs.io/", "网络设备自动化与状态采集文档", "NAPALM Community"),
    "network-project": _source("SRC-CISCO-NETWORK", "Cisco Networking Academy Skills for All", "official_course", "https://www.netacad.com/", "网络设计、实施与验证课程单元", "Cisco"),
    "data-linux": _source("SRC-GNU-BASH", "GNU Bash Reference Manual", "official_document", "https://www.gnu.org/software/bash/manual/", "Shell 基础、文件与命令章节", "GNU Project"),
    "data-python": _source("SRC-PYTHON-TUTORIAL", "Python 官方教程", "official_document", "https://docs.python.org/zh-cn/3/tutorial/", "数据结构、模块与输入输出章节", "Python Software Foundation"),
    "data-sql": _source("SRC-POSTGRES-SQL", "PostgreSQL Documentation", "official_document", "https://www.postgresql.org/docs/current/", "Tutorial 与 SQL Language", "PostgreSQL Global Development Group"),
    "data-etl": _source("SRC-APACHE-AIRFLOW", "Apache Airflow Documentation", "official_document", "https://airflow.apache.org/docs/", "工作流、任务与数据管道概念", "Apache Software Foundation"),
    "data-warehouse": _source("SRC-IBM-DWH", "IBM 数据仓库基础资料", "official_document", "https://www.ibm.com/think/topics/data-warehouse", "数据仓库、主题域与分析概念", "IBM"),
    "data-computing": _source("SRC-APACHE-SPARK", "Apache Spark Documentation", "official_document", "https://spark.apache.org/docs/latest/", "Quick Start、Structured APIs 与部署", "Apache Software Foundation"),
    "data-visualization": _source("SRC-W3C-DV", "W3C Data Visualization", "web_standard", "https://www.w3.org/standards/webdesign/", "Web 数据表达相关标准与指南入口", "W3C"),
    "data-governance": _source("SRC-NIST-PRIVACY", "NIST Privacy Framework", "government_standard", "https://www.nist.gov/privacy-framework", "数据处理风险与治理框架", "NIST"),
    "data-project": _source("SRC-APACHE-SPARK", "Apache Spark Documentation", "official_document", "https://spark.apache.org/docs/latest/", "数据处理与作业提交文档", "Apache Software Foundation"),
    "ai-python": _source("SRC-PYTHON-TUTORIAL", "Python 官方教程", "official_document", "https://docs.python.org/zh-cn/3/tutorial/", "数据结构、函数、模块与输入输出章节", "Python Software Foundation"),
    "ai-math": _source("SRC-NIST-AI-RMF", "NIST AI Risk Management Framework", "government_standard", "https://www.nist.gov/itl/ai-risk-management-framework", "测量、管理与模型风险术语", "NIST"),
    "ai-ml": _source("SRC-SCIKIT-LEARN", "scikit-learn User Guide", "official_document", "https://scikit-learn.org/stable/user_guide.html", "监督学习、模型选择与评估章节", "scikit-learn developers"),
    "ai-dl": _source("SRC-PYTORCH", "PyTorch Documentation", "official_document", "https://docs.pytorch.org/docs/stable/", "Autograd、神经网络和优化器文档", "PyTorch Foundation"),
    "ai-vision": _source("SRC-OPENCV", "OpenCV Documentation", "official_document", "https://docs.opencv.org/", "图像处理与计算机视觉教程", "OpenCV"),
    "ai-nlp": _source("SRC-HUGGINGFACE", "Hugging Face 文档", "official_document", "https://huggingface.co/docs", "Transformers、推理与模型使用文档", "Hugging Face"),
    "ai-deployment": _source("SRC-FASTAPI", "FastAPI 文档", "official_document", "https://fastapi.tiangolo.com/zh/", "服务接口、部署与运行文档", "FastAPI"),
    "ai-governance": _source("SRC-NIST-AI-RMF", "NIST AI Risk Management Framework", "government_standard", "https://www.nist.gov/itl/ai-risk-management-framework", "治理、映射、测量和管理章节", "NIST"),
    "ai-project": _source("SRC-NIST-AI-RMF", "NIST AI Risk Management Framework", "government_standard", "https://www.nist.gov/itl/ai-risk-management-framework", "可信 AI 系统的风险管理章节", "NIST"),
}


def pending_source_registry() -> dict[str, Any]:
    """Return one pending source-registration record for every catalog module."""
    modules: list[dict[str, Any]] = []
    for pack in CAPABILITY_PACKS.values():
        for module in pack["modules"]:
            module_id = str(module["module_id"])
            source = _SOURCES[module_id]
            draft = get_teaching_contract_draft(module_id)
            modules.append({
                "module_id": module_id,
                "knowledge_point_name": module["knowledge_point_name"],
                "pack_id": pack["pack_id"],
                "support_level": pack["support_level"],
                "review_status": PENDING_REVIEW,
                "required_knowledge_blocks": ["concept", "steps", "example"],
                "required_assets": ["teaching_contract", "reviewed_questions", "practical_rubric", "error_patterns"],
                "teaching_contract_status": (
                    str(draft["review"]["status"]) if draft else "not_started"
                ),
                "source": deepcopy(source),
            })
    return {
        "schema_version": SOURCE_REGISTRY_VERSION,
        "review_guidance": REVIEW_GUIDANCE,
        "modules": modules,
    }
