"""Versioned domain-knowledge supply and integrity policies.

This module owns domain truth projections, not learner knowledge.  Every
packet is a read-only, provenance-preserving compilation of source versions.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Chunk, DomainKnowledgePacket, Project, Source, SourceVersion


PACKET_POLICY_VERSION = "domain-knowledge-packet-v1"
SOURCE_POLICY_VERSION = "source-integrity-v1"

ACTIVE_SOURCE_STATUSES = {"active", "conflicted"}
RETRIEVABLE_SOURCE_STATUSES = {"active", "conflicted", "stale"}

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I),
    re.compile(r"(?:system|developer)\s+prompt\s*[:：]", re.I),
    re.compile(r"(?:执行|调用)\s*(?:以下|这个)?\s*(?:工具|命令)", re.I),
    re.compile(r"(?:泄露|输出|显示).{0,16}(?:密钥|token|系统提示|开发者消息)", re.I),
    re.compile(r"you\s+are\s+now\s+(?:an?|the)\s+", re.I),
)

_OPERATING_PHRASES = (
    r"^请", r"^先", r"^帮我", r"^给我", r"^我想", r"^带我",
    r"然后用完整讲义与练习带我学.*$", r"然后用.*带我学.*$",
    r"用完整讲义与练习.*$", r"带我(?:理解|学习|弄懂)",
    r"简要说明", r"简单解释", r"完整示范",
)

_FOUNDATION_PRIMERS = {
    "gradient-descent": {
        "patterns": (r"梯度下降", r"gradient\s+descent", r"负梯度"),
        "title": "梯度下降：负梯度方向与学习率",
        "content": """# 梯度下降：为什么沿负梯度走

## 定义与局部模型
梯度由各坐标方向的偏导数组成，描述函数在当前位置的一阶变化。对很小的位移 Δx，一阶近似是 f(x+Δx)≈f(x)+∇f(x)·Δx。

## 核心机制
当位移长度固定时，内积 ∇f(x)·Δx 在 Δx 与梯度方向相反时最小。因此在欧氏距离约束下，负梯度是让一阶近似下降最快的方向。这里的“最快”是局部且针对一阶近似，并不表示一步到达全局最小值。

## 一维完整例子
令 f(x)=(x-2)^2，则 f'(x)=2(x-2)。从 x=0 开始，梯度为 -4，负梯度为 4。取学习率 η=0.1，更新式 x_new=x-ηf'(x)，得到 x=0.4；函数值从 4 下降到 2.56。第二次梯度为 -3.2，更新到 x=0.72，函数值下降到 1.6384。

## 边界与误区
负梯度只保证足够小步长下的局部下降。学习率过大可能跨过低点、振荡，甚至使函数值上升；在非凸问题中也不保证到达全局最优。若使用不同的距离度量或预条件，最陡下降方向也会改变。

## 可验证问题
学习者应能从一阶近似解释更新式中的负号，能对一维导数判断更新方向，并能说明学习率过大为何破坏下降。""",
    },
    "clustering": {
        "patterns": (r"聚类", r"clustering", r"k-?means", r"dbscan"),
        "title": "聚类：目标、算法与边界",
        "content": """# 聚类

## 定义
聚类是在没有目标标签的情况下，依据选定的表示、相似度和目标函数，把对象组织成若干组。所谓“相似”不是数据天然携带的答案，而是由特征和距离共同定义。

## 核心机制
K-Means 最小化样本到所属中心的平方距离，适合近似球状且尺度可比的簇；层次聚类产生逐层合并或拆分的树；DBSCAN 依据局部密度连接样本，可识别噪声和非球状簇。

## 例子
客户分群可以按购买频率、金额和品类偏好形成向量，再标准化并聚类。所得簇需要结合业务解释和稳定性检查，不能仅凭算法编号命名为真实人群。

## 边界与误区
聚类结果依赖特征、尺度、距离和超参数；没有唯一正确分组。聚类不是分类，也不能仅凭离群点就断言欺诈。评价应结合内部指标、稳定性和外部用途。

## 可验证问题
学习者应能解释聚类与分类的区别，比较 K-Means 与 DBSCAN 的假设，并指出特征缩放为何会改变结果。""",
    },
    "marginal-cost": {
        "patterns": (r"边际成本", r"marginal\s+cost"),
        "title": "边际成本：新增一单位产出的成本变化",
        "content": """# 边际成本

## 定义
边际成本描述产量增加一个很小单位时总成本的增量；连续模型中写作 MC(q)=dC(q)/dq，离散情境中可用 C(q+1)-C(q) 近似。

## 核心机制
边际成本会随产量变化，因为新增产出使用的资源条件会变化：低产量时分摊固定准备和专业化可能降低新增成本；接近容量上限后，加班、拥堵和低效率投入会抬高新增成本。因此“总成本增加”并不意味着边际成本恒定。

## 例子
一家面包店从每天 80 个面包增至 81 个时只需多用少量原料；若烤箱已经满载，从 200 个增至 201 个可能需要加班或新增一炉，后一情境的边际成本更高。

## 边界与误区
边际成本不是平均成本，也不是固定成本；它取决于考察的产量点和时间尺度。短期容量约束与长期可调整设备时的曲线可能不同，不能脱离条件断言它一定上升或下降。

## 可验证问题
学习者应能由总成本函数求边际成本，解释容量约束如何改变它，并区分边际成本与平均成本。""",
    },
    "event-loop": {
        "patterns": (r"事件循环", r"event\s+loop", r"微任务", r"microtask"),
        "title": "事件循环：任务队列与微任务检查点",
        "content": """# 事件循环

## 定义
事件循环是运行时协调调用栈、任务队列和异步回调的一套调度机制；它让单线程执行上下文在一次只运行一段代码的同时处理后续事件。

## 核心机制
一次任务执行到调用栈清空后，运行时进入微任务检查点并持续清空当时可运行的微任务；随后才选择下一个任务。Promise 回调通常进入微任务队列，定时器回调进入任务队列，所以二者就绪时间相近时 Promise 回调通常先执行。

## 例子
同步代码先打印 A，随后安排 setTimeout 打印 B 和 Promise.then 打印 C，最后同步打印 D；常见顺序是 A、D、C、B，因为当前任务先结束，再清空微任务，最后处理后续定时器任务。

## 边界与误区
“微任务优先”不表示它能打断正在执行的同步代码，也不表示所有宿主环境的任务来源完全相同。递归不断加入微任务还可能延迟后续任务和渲染。

## 可验证问题
学习者应能追踪同步代码、微任务和任务的顺序，并说明调用栈不为空时回调为何不能执行。""",
    },
    "queue-fifo": {
        "patterns": (r"(?:FIFO|先进先出)", r"队列.*(?:入队|出队)", r"queue.*(?:enqueue|dequeue)"),
        "title": "队列：先进先出的状态变化",
        "content": """# 队列与 FIFO

## 定义
队列是按先进先出规则访问元素的线性结构：enqueue 把新元素加入队尾，dequeue 从队首移除并返回最早进入且尚未移除的元素。

## 核心机制
队首和队尾承担不同职责，因此操作顺序可以确定状态轨迹。若初始队列为 [A,B]，先 enqueue(C) 得到 [A,B,C]，再 dequeue() 返回 A，剩余 [B,C]。

## 例子
打印任务按进入顺序排队；新任务追加到末尾，打印机总是先取最早等待的任务，这正对应 FIFO。

## 边界与误区
队列不是栈：栈以后进先出访问栈顶。优先队列也不按纯粹到达顺序出队，因此不能仅凭名称中的“队列”就假设 FIFO。

## 可验证问题
学习者应能逐步追踪 enqueue 与 dequeue 后的返回值和剩余状态，并区分队列、栈和优先队列。""",
    },
    "python-closure": {
        "patterns": (r"闭包", r"closure", r"捕获外层变量"),
        "title": "Python 闭包：自由变量与调用时取值",
        "content": """# Python 闭包

## 定义
闭包是函数与其定义时词法环境中自由变量绑定关系的组合。内部函数引用外层局部变量时，即使外层函数已经返回，这个绑定仍可由闭包单元保存。

## 核心机制
Python 闭包通常捕获的是变量绑定而不是定义瞬间的值快照；真正读取发生在内部函数调用时。循环中创建多个 lambda 却都引用同一个循环变量，因此稍后调用时可能看到相同的最终值。

## 例子
外层函数令 x=1，定义返回 x 的 inner，随后把 x 改为 2 再返回 inner；调用 inner() 得到 2。若需要冻结循环当次值，可用默认参数 lambda i=i: i 在函数创建时求值。

## 边界与误区
闭包不同于把所有外层变量复制进函数；未被引用的变量不会成为自由变量。修改外层非局部绑定需要 nonlocal，而可变对象的内容变化与重新绑定变量也应区分。

## 可验证问题
学习者应能判断一个名字是否为自由变量，预测延迟调用的循环闭包结果，并解释默认参数冻结值为何有效。""",
    },
}


def _foundation_match(query: str) -> tuple[str, dict[str, Any]] | None:
    for key, item in _FOUNDATION_PRIMERS.items():
        if any(re.search(pattern, query, re.I) for pattern in item["patterns"]):
            return key, item
    from app.services.topic_primers import deterministic_topic_primer
    legacy = deterministic_topic_primer(query)
    if legacy:
        artifact, source_key = legacy
        card = dict(artifact.get("card") or {})
        content = (
            f"# {card.get('title', query)}\n\n## 定义与机制\n"
            + "\n".join(str(item) for item in list(card.get("key_points") or []))
            + f"\n\n## 例子\n{card.get('example', '')}"
            + f"\n\n## 边界与误区\n{card.get('common_confusion', '')}"
            + f"\n\n## 可验证问题\n{card.get('success_criteria', '')}"
        )
        return source_key.replace(".", "-"), {
            "title": str(card.get("title") or query), "content": content,
        }
    return None


async def ensure_foundation_source(
    db: AsyncSession, *, learner_id: int, query: str,
) -> Source | None:
    matched = _foundation_match(query)
    if not matched:
        return None
    key, primer = matched
    project = (await db.execute(select(Project).where(
        Project.learner_id == learner_id,
        Project.project_kind == "knowledge_library",
        Project.visibility == "internal",
    ).order_by(Project.id))).scalars().first()
    if not project:
        project = Project(
            learner_id=learner_id, name="个人领域知识库",
            description="个人资料与 LearnFlow 策展底座。",
            project_kind="knowledge_library", visibility="internal",
        )
        db.add(project)
        await db.flush()
    location = f"learnflow://foundation/{key}"
    source = (await db.execute(select(Source).where(
        Source.project_id == project.id, Source.url == location,
    ))).scalar_one_or_none()
    if source:
        return source
    source = Source(
        project_id=project.id, type="curated", url=location, role="auxiliary",
        status="processing", meta_data={"foundation": True, "title": primer["title"]},
    )
    db.add(source)
    await db.flush()
    payload = [{
        "index": 0, "content": primer["content"], "tokens": len(primer["content"]) // 4,
        "meta": {"title": primer["title"], "heading": primer["title"], "foundation": True},
    }]
    version, _ = await ensure_source_version(db, source=source, chunks=payload, source_meta={"version": "v1"})
    version.source_role = "canonical"
    version.authority_tier = "curated"
    version.freshness_class = "stable"
    db.add(Chunk(
        source_id=source.id, source_version_id=version.id, index=0,
        content=primer["content"], tokens=len(primer["content"]) // 4,
        meta_data=payload[0]["meta"],
    ))
    source.status = "processed"
    return source


async def ensure_inline_source(
    db: AsyncSession, *, learner_id: int, text: str, title: str,
) -> Source | None:
    """Version explicit task material without treating chat instructions as facts."""
    content = str(text or "").strip()
    if len(content) < 40:
        return None
    project = (await db.execute(select(Project).where(
        Project.learner_id == learner_id,
        Project.project_kind == "knowledge_library",
        Project.visibility == "internal",
    ).order_by(Project.id))).scalars().first()
    if not project:
        project = Project(
            learner_id=learner_id, name="个人领域知识库",
            description="个人资料与 LearnFlow 策展底座。",
            project_kind="knowledge_library", visibility="internal",
        )
        db.add(project)
        await db.flush()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    location = f"learnflow://inline/{digest}"
    source = (await db.execute(select(Source).where(
        Source.project_id == project.id, Source.url == location,
    ))).scalar_one_or_none()
    if source:
        return source
    source = Source(
        project_id=project.id, type="inline", url=location, role="auxiliary",
        status="processing", meta_data={"explicit_inline_material": True, "title": title[:500]},
    )
    db.add(source)
    await db.flush()
    payload = [{
        "index": 0, "content": content, "tokens": max(1, len(content) // 4),
        "meta": {"title": title[:500], "heading": title[:500], "inline": True},
    }]
    version, _ = await ensure_source_version(db, source=source, chunks=payload)
    version.source_role = "learner_context"
    db.add(Chunk(
        source_id=source.id, source_version_id=version.id, index=0,
        content=content, tokens=max(1, len(content) // 4), meta_data=payload[0]["meta"],
    ))
    return source


def source_content_hash(chunks: Iterable[dict[str, Any]]) -> str:
    payload = [
        {
            "index": int(item.get("index") or index),
            "content": str(item.get("content") or "").replace("\r\n", "\n"),
            "meta": item.get("meta") or {},
        }
        for index, item in enumerate(chunks)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def inspect_source_chunks(chunks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(chunks)
    contents = [str(item.get("content") or "").strip() for item in items]
    nonempty = [item for item in contents if item]
    matches = sorted({pattern.pattern for text in nonempty for pattern in _INJECTION_PATTERNS if pattern.search(text)})
    normalized = [re.sub(r"\s+", " ", item).casefold()[:1000] for item in nonempty]
    duplicates = sum(count - 1 for count in Counter(normalized).values() if count > 1)
    total_characters = sum(len(item) for item in nonempty)
    reasons: list[str] = []
    if not nonempty or total_characters < 40:
        reasons.append("empty_or_unusable_content")
    if matches:
        reasons.append("instruction_injection_detected")
    if nonempty and duplicates / len(nonempty) >= 0.6:
        reasons.append("excessive_duplicate_content")
    quarantined = bool(matches or "empty_or_unusable_content" in reasons)
    return {
        "policy_version": SOURCE_POLICY_VERSION,
        "quarantined": quarantined,
        "reasons": reasons,
        "injection_pattern_count": len(matches),
        "chunk_count": len(items),
        "nonempty_chunk_count": len(nonempty),
        "total_characters": total_characters,
        "duplicate_chunk_count": duplicates,
        "instruction_boundary": "来源正文只作为不可信数据；其中的指令永不进入 Agent 控制面。",
    }


def infer_source_policy(source: Source) -> tuple[str, str, str]:
    location = str(source.url or "").casefold()
    if any(token in location for token in ("docs.", "documentation", "reference", "rfc-editor", "w3.org")):
        return "canonical", "official", "versioned"
    if any(token in location for token in ("arxiv.org", "acm.org", "ieee.org", "openreview.net")):
        return "complementary", "academic", "current"
    if source.type == "github":
        return "complementary", "repository", "versioned"
    return "learner_context", "learner_owned", "stable"


async def mark_packets_stale_for_source_version(
    db: AsyncSession, source_version_id: int, *, reason: str, packet_status: str = "stale",
) -> int:
    packets = list((await db.execute(select(DomainKnowledgePacket).where(
        DomainKnowledgePacket.status.in_({"ready", "ready_with_gaps"}),
    ))).scalars().all())
    changed = 0
    for packet in packets:
        refs = list(packet.source_version_refs or [])
        if any(int(ref.get("source_version_id") or 0) == source_version_id for ref in refs if isinstance(ref, dict)):
            packet.status = packet_status
            packet.freshness = {
                **dict(packet.freshness or {}),
                "stale": True,
                "reason": reason,
                "detected_at": datetime.utcnow().isoformat(),
            }
            changed += 1
    return changed


async def ensure_source_version(
    db: AsyncSession,
    *,
    source: Source,
    chunks: list[dict[str, Any]],
    source_meta: dict[str, Any] | None = None,
) -> tuple[SourceVersion, bool]:
    digest = source_content_hash(chunks)
    existing = (await db.execute(select(SourceVersion).where(
        SourceVersion.source_id == source.id,
        SourceVersion.content_hash == digest,
    ))).scalar_one_or_none()
    if existing:
        existing.retrieved_at = datetime.utcnow()
        source.status = "quarantined" if existing.status == "quarantined" else "processed"
        source.meta_data = {**dict(source.meta_data or {}), "active_source_version_id": existing.id}
        return existing, False

    latest = (await db.execute(select(SourceVersion).where(
        SourceVersion.source_id == source.id,
    ).order_by(SourceVersion.version.desc()).limit(1))).scalar_one_or_none()
    inspection = inspect_source_chunks(chunks)
    role, authority, freshness = infer_source_policy(source)
    version = SourceVersion(
        source_id=source.id,
        version=int(latest.version if latest else 0) + 1,
        content_hash=digest,
        source_role=role,
        authority_tier=authority,
        version_label=str(dict(source_meta or {}).get("version") or "")[:120],
        freshness_class=freshness,
        status="quarantined" if inspection["quarantined"] else "active",
        health={"status": "blocked" if inspection["quarantined"] else "healthy"},
        provenance={
            "source_id": source.id,
            "source_type": source.type,
            "location": source.url,
            "retrieved_at": datetime.utcnow().isoformat(),
        },
        inspection=inspection,
    )
    db.add(version)
    await db.flush()
    if latest and latest.status in ACTIVE_SOURCE_STATUSES:
        latest.status = "superseded"
        await mark_packets_stale_for_source_version(
            db, latest.id, reason=f"source_version_superseded_by:{version.id}",
        )
    source.status = "quarantined" if inspection["quarantined"] else "processed"
    source.meta_data = {**dict(source.meta_data or {}), "active_source_version_id": version.id}
    return version, True


def build_domain_brief(
    query: str,
    *,
    kind: str = "explanation",
    skill_id: str = "",
) -> dict[str, Any]:
    topic = " ".join(str(query or "").split())[:1200]
    topic = re.split(r"(?:，|,|；|;)?\s*然后", topic, maxsplit=1)[0]
    for pattern in _OPERATING_PHRASES:
        topic = re.sub(pattern, "", topic, flags=re.I).strip(" ：:，,。.!！?？")
    topic = topic or "当前学习主题"
    required = ["definition", "mechanism", "example", "boundary"]
    if kind in {"guided_skill", "teaching_artifact"}:
        required.extend(["misconception", "assessment_basis"])
    if kind == "project_baseline":
        required = ["scope", "prerequisites", "canonical_sources", "risks"]
        required.append(
            "implementation"
            if re.search(r"代码|编程|软件|仓库|API|工程|implement|repository", query, re.I)
            else "example"
        )
    return {
        "schema_version": "domain-brief-v1",
        "subject": topic[:255],
        "task_topic": topic[:500],
        "kind": kind,
        "skill_id": skill_id,
        "scope": [topic[:500]],
        "non_goals": [],
        "required_knowledge": list(dict.fromkeys(required)),
        "freshness_class": "current" if re.search(r"最新|当前|版本|论文|政策|价格|行业", query, re.I) else "stable",
    }


def _sentences(text: str) -> list[str]:
    return [
        " ".join(item.split())[:700]
        for item in re.split(r"(?<=[。！？.!?])\s+|\n+", text)
        if 30 <= len(" ".join(item.split())) <= 900
    ]


def _query_terms(value: str) -> set[str]:
    terms = {item.casefold() for item in re.findall(r"[A-Za-z0-9_+#.-]{2,}", value)}
    for span in re.findall(r"[\u4e00-\u9fff]{2,}", value):
        for width in range(2, min(6, len(span)) + 1):
            terms.update(span[index:index + width] for index in range(len(span) - width + 1))
            if len(terms) >= 180:
                return terms
    return terms


_RETRIEVAL_STOP_TERMS = {
    "python", "javascript", "理解", "学习", "任务", "讲义", "练习", "完整",
    "为什么", "如何", "怎么", "什么", "函数", "代码", "机制", "解释", "带我",
}


def _rank_rows(
    rows: list[tuple[Chunk, SourceVersion, Source]],
    *,
    query: str,
    explicit_source_ids: set[int],
) -> list[tuple[Chunk, SourceVersion, Source]]:
    terms = {
        term for term in _query_terms(query)
        if term not in _RETRIEVAL_STOP_TERMS
        and not any(stop in term for stop in ("带我学", "完整讲义", "然后用"))
    }
    authority = {"official": 8, "curated": 7, "academic": 6, "repository": 4, "learner_owned": 2}
    ranked = []
    for chunk, version, source in rows:
        meta = dict(chunk.meta_data or {})
        heading = str(meta.get("heading") or meta.get("title") or "").casefold()
        content = str(chunk.content or "").casefold()
        lexical_score = sum(4 if term in heading else 1 for term in terms if term in heading or term in content)
        score = lexical_score + authority.get(version.authority_tier, 0)
        if source.id in explicit_source_ids:
            score += 20
        if lexical_score > 0 or source.id in explicit_source_ids:
            ranked.append((score, lexical_score, chunk, version, source))
    ranked.sort(key=lambda item: (-item[0], item[3].status != "active", item[4].id, item[2].index))
    selected: list[tuple[Chunk, SourceVersion, Source]] = []
    seen_sources: set[int] = set()
    for _, _, chunk, version, source in ranked:
        if source.id not in seen_sources:
            selected.append((chunk, version, source))
            seen_sources.add(source.id)
    for _, _, chunk, version, source in ranked:
        row = (chunk, version, source)
        if row not in selected:
            selected.append(row)
        if len(selected) >= 24:
            break
    return selected


def _section_blocks(text: str) -> list[tuple[str, str]]:
    heading = ""
    blocks: list[tuple[str, str]] = []
    buffer: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            if buffer:
                blocks.append((heading, " ".join(buffer)))
                buffer = []
            heading = line.lstrip("#").strip()
        elif line:
            buffer.append(line)
    if buffer:
        blocks.append((heading, " ".join(buffer)))
    return blocks or [("", str(text or ""))]


def _knowledge_units(rows: list[tuple[Chunk, SourceVersion, Source]]) -> dict[str, Any]:
    concepts: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    misconceptions: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    procedures: list[dict[str, Any]] = []
    counterexamples: list[dict[str, Any]] = []
    for chunk, version, source in rows[:24]:
        meta = dict(chunk.meta_data or {})
        locator = str(meta.get("heading") or meta.get("title") or f"chunk-{chunk.index}")[:240]
        evidence = {
            "source_id": source.id,
            "source_version_id": version.id,
            "chunk_id": chunk.id,
            "locator": locator,
        }
        heading = str(meta.get("heading") or meta.get("title") or "").strip()
        if heading:
            concepts.append({"label": heading[:180], "evidence": evidence})
        for section_heading, section_text in _section_blocks(str(chunk.content or ""))[:12]:
            section_evidence = {
                **evidence,
                "locator": f"{locator} > {section_heading}" if section_heading else locator,
            }
            section_kind = section_heading.casefold()
            for sentence in _sentences(section_text)[:8]:
                row = {"statement": sentence, "evidence": section_evidence, "critical": True}
                claims.append(row)
                if re.search(r"例|示例|example|case", section_kind, re.I) or re.search(
                    r"例如|举例|for instance|比如|令\s*f\(", sentence, re.I
                ):
                    examples.append(row)
                if re.search(r"边界|误区|混淆|注意|limitation|pitfall|mistake", section_kind, re.I) or re.search(
                    r"并不|不能|不保证|not always|common mistake|pitfall", sentence, re.I
                ):
                    misconceptions.append(row)
                if re.search(r"因为|因此|导致|意味着|取决于|because|therefore|depends on|means", sentence, re.I):
                    relations.append({**row, "relation": "explanatory"})
                if re.search(r"步骤|算法|更新|流程|procedure|algorithm|step", section_kind, re.I):
                    procedures.append(row)
                if re.search(r"反例|counterexample|失败|振荡|发散", section_kind + sentence, re.I):
                    counterexamples.append(row)
    dedupe = lambda values, key: list({str(item.get(key)): item for item in values if item.get(key)}.values())
    return {
        "concepts": dedupe(concepts, "label")[:20],
        "claims": dedupe(claims, "statement")[:30],
        "relations": dedupe(relations, "statement")[:12],
        "procedures": dedupe(procedures, "statement")[:10],
        "examples": dedupe(examples, "statement")[:8],
        "counterexamples": dedupe(counterexamples, "statement")[:8],
        "misconceptions": dedupe(misconceptions, "statement")[:8],
        "assessment_basis": dedupe(claims, "statement")[:8],
    }


def _coverage(brief: dict[str, Any], units: dict[str, Any], rows: list[tuple[Chunk, SourceVersion, Source]]) -> dict[str, Any]:
    mapping = {
        "definition": bool(units["concepts"] or units["claims"]),
        "mechanism": bool(units["relations"] or len(units["claims"]) >= 2),
        "example": bool(units["examples"]),
        "boundary": bool(units["misconceptions"]),
        "misconception": bool(units["misconceptions"]),
        "assessment_basis": bool(units["assessment_basis"]),
        "scope": bool(units["concepts"] or units["claims"]),
        "prerequisites": bool(units["relations"]),
        "canonical_sources": any(version.authority_tier in {"official", "academic"} for _, version, _ in rows),
        "implementation": any(version.authority_tier == "repository" for _, version, _ in rows) or bool(units["procedures"]),
        "risks": bool(units["misconceptions"]),
    }
    facets = [{"id": item, "covered": bool(mapping.get(item))} for item in brief["required_knowledge"]]
    covered = sum(item["covered"] for item in facets)
    return {
        "facets": facets,
        "covered": covered,
        "total": len(facets),
        "ratio": round(covered / len(facets), 3) if facets else 1.0,
        "gaps": [item["id"] for item in facets if not item["covered"]],
    }


async def compile_domain_knowledge_packet(
    db: AsyncSession,
    *,
    learner_id: int,
    query: str,
    kind: str,
    source_ids: list[int] | None = None,
    project_id: int | None = None,
    checkpoint_id: int | None = None,
    session_id: int | None = None,
    learning_task_id: int | None = None,
    skill_id: str = "",
    initial_status: str | None = None,
) -> DomainKnowledgePacket:
    brief = build_domain_brief(query, kind=kind, skill_id=skill_id)
    foundation = None if kind == "project_baseline" else await ensure_foundation_source(
        db, learner_id=learner_id, query=query,
    )
    explicit_ids = set(source_ids or [])
    baseline = None
    pinned_version_ids: set[int] = set()
    baseline_unhealthy = False
    if project_id and kind != "project_baseline":
        baseline = (await db.execute(select(DomainKnowledgePacket).where(
            DomainKnowledgePacket.learner_id == learner_id,
            DomainKnowledgePacket.project_id == project_id,
            DomainKnowledgePacket.kind == "project_baseline",
            DomainKnowledgePacket.status != "draft",
        ).order_by(DomainKnowledgePacket.updated_at.desc(), DomainKnowledgePacket.id.desc()).limit(1))).scalar_one_or_none()
        if baseline:
            pinned_version_ids = {
                int(ref.get("source_version_id"))
                for ref in list(baseline.source_version_refs or [])
                if isinstance(ref, dict) and str(ref.get("source_version_id") or "").isdigit()
            }
            explicit_ids.update(
                int(ref.get("source_id"))
                for ref in list(baseline.source_version_refs or [])
                if isinstance(ref, dict) and str(ref.get("source_id") or "").isdigit()
            )
            baseline_unhealthy = baseline.status not in {"ready", "ready_with_gaps"}
    source_query = select(Source).where(Source.project.has(learner_id=learner_id))
    if kind == "project_baseline":
        source_query = source_query.where(
            Source.id.in_(explicit_ids) if explicit_ids else Source.project_id == project_id
        )
    sources = list((await db.execute(source_query.order_by(Source.id))).scalars().all())
    if foundation and foundation.id not in {item.id for item in sources}:
        sources.append(foundation)
    ids = [source.id for source in sources]
    rows: list[tuple[Chunk, SourceVersion, Source]] = []
    if ids:
        rows = list((await db.execute(
            select(Chunk, SourceVersion, Source)
            .join(SourceVersion, SourceVersion.id == Chunk.source_version_id)
            .join(Source, Source.id == Chunk.source_id)
            .where(
                Source.id.in_(ids),
                or_(
                    SourceVersion.status.in_(RETRIEVABLE_SOURCE_STATUSES),
                    SourceVersion.id.in_(pinned_version_ids) if pinned_version_ids else False,
                ),
            )
            .order_by(Source.id, SourceVersion.version.desc(), Chunk.index)
        )).all())
    rows = _rank_rows(rows, query=query, explicit_source_ids=explicit_ids)
    checked_versions: set[int] = set()
    for _, version, _ in rows:
        if version.id in checked_versions:
            continue
        checked_versions.add(version.id)
        if version.status == "active" and freshness_due(version):
            version.status = "stale"
            version.health = {
                **dict(version.health or {}), "status": "stale",
                "reason": "freshness_window_elapsed",
                "checked_at": datetime.utcnow().isoformat(),
            }
    units = _knowledge_units(rows)
    coverage = _coverage(brief, units, rows)
    conflicts = [
        {"source_version_id": version.id, "reason": "source_marked_conflicted"}
        for _, version, _ in rows if version.status == "conflicted"
    ]
    stale_refs = [version.id for _, version, _ in rows if version.status == "stale"]
    gaps = list(coverage["gaps"])
    if baseline_unhealthy:
        gaps.append("project_baseline_stale_or_blocked")
    critical_gap = bool(gaps) and kind in {"guided_skill", "teaching_artifact", "project_baseline"}
    coverage = {**coverage, "critical_gaps": gaps if critical_gap else []}
    status = (
        "blocked" if critical_gap or conflicts or (stale_refs and kind in {"guided_skill", "teaching_artifact"})
        else "ready_with_gaps" if gaps or stale_refs else "ready"
    )
    refs = list({version.id: {
        "source_id": source.id,
        "source_version_id": version.id,
        "version": version.version,
        "content_hash": version.content_hash,
        "status": version.status,
        "authority_tier": version.authority_tier,
    } for _, version, source in rows}.values())
    gate_status = status
    if initial_status:
        coverage = {**coverage, "gate_status": gate_status}
        status = initial_status
    fingerprint_payload = {
        "learner_id": learner_id, "project_id": project_id, "checkpoint_id": checkpoint_id,
        "session_id": session_id, "learning_task_id": learning_task_id, "kind": kind,
        "brief": brief, "refs": refs, "policy": PACKET_POLICY_VERSION,
        "initial_status": initial_status,
    }
    fingerprint = hashlib.sha256(json.dumps(
        fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    existing = (await db.execute(select(DomainKnowledgePacket).where(
        DomainKnowledgePacket.learner_id == learner_id,
        DomainKnowledgePacket.input_fingerprint == fingerprint,
    ))).scalar_one_or_none()
    if existing:
        return existing
    packet = DomainKnowledgePacket(
        learner_id=learner_id, project_id=project_id, checkpoint_id=checkpoint_id,
        session_id=session_id, learning_task_id=learning_task_id, kind=kind,
        subject_key=brief["subject"], domain_brief=brief, source_version_refs=refs,
        knowledge_units=units, coverage=coverage,
        freshness={"stale": bool(stale_refs), "stale_source_version_ids": stale_refs},
        conflicts=conflicts, unresolved_gaps=gaps, status=status,
        policy_version=PACKET_POLICY_VERSION, input_fingerprint=fingerprint,
    )
    db.add(packet)
    await db.flush()
    return packet


def packet_view(packet: DomainKnowledgePacket, *, compact: bool = False) -> dict[str, Any]:
    units = dict(packet.knowledge_units or {})
    if compact:
        units = {
            "concepts": list(units.get("concepts") or [])[:6],
            "claims": list(units.get("claims") or [])[:8],
            "relations": list(units.get("relations") or [])[:5],
            "examples": list(units.get("examples") or [])[:3],
            "misconceptions": list(units.get("misconceptions") or [])[:3],
        }
    return {
        "id": packet.id, "kind": packet.kind, "subject_key": packet.subject_key,
        "domain_brief": packet.domain_brief, "source_version_refs": packet.source_version_refs,
        "knowledge_units": units, "coverage": packet.coverage, "freshness": packet.freshness,
        "conflicts": packet.conflicts, "unresolved_gaps": packet.unresolved_gaps,
        "status": packet.status, "policy_version": packet.policy_version,
        "input_fingerprint": packet.input_fingerprint,
        "mastery_inference": False,
    }


def freshness_due(version: SourceVersion, *, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    window = {
        "stable": timedelta(days=180),
        "versioned": timedelta(days=30),
        "current": timedelta(days=7),
        "live": timedelta(hours=1),
    }.get(version.freshness_class, timedelta(days=30))
    return version.retrieved_at < now - window
