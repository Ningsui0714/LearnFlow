"""
Learning Route Agent Service (T2: tool-calling based repo understanding).

Layered repo understanding (NOT prompt-stuffed RAG):
- L0: deterministic structure (README TOC + dir groups + confidence)
- L1: cached per-file summaries (LLM batch, stored on Source.meta_data)
- L2: on-demand chunk reads (read_chunk / list_chunks tools)
- L3: semantic search (search_chunks tool) — only when needed

The agent proposes changes in conversation; only after explicit user
confirmation it calls submit_roadmap(checkpoints), which is validated
(completed checkpoints cannot be deleted / renamed) and returned to the
API layer for transactional apply. The LLM never emits full roadmap JSON
inside chat text — output pressure is reduced by design.
"""
import json
from typing import List, Optional, Dict, Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

from app.core.config import settings

MAX_TOOL_ROUNDS = 12

SYSTEM_PROMPT = """你是一名学习路线规划专家。你的任务是帮助用户为特定学习主题规划一条循序渐进的学习路线。

## 你的工作流程
1. 先用工具理解仓库：get_repo_structure 查看整体结构，get_file_summaries 查看各文件作用。
2. 需要细节时用 list_chunks / read_chunk / search_chunks 按需查看内容（不要凭空编造）。
3. 与用户对话了解基础水平、学习目标、可用时间。主动给出方案（"我建议这样"），不要只反问。
4. 在对话中描述你的路线方案；用户确认后，调用 submit_roadmap 提交最终路线。
5. 用户提出修改时，直接调整方案；再次确认后再提交。

## submit_roadmap 的参数格式
{
  "checkpoints": [
    {
      "title": "关卡名称",
      "description": "学习目标描述",
      "order": 1,
      "prerequisites": [],
      "chunk_ids": [整数切片ID],
      "files": ["建议涉及的文件路径"],
      "key_concepts": ["本关核心概念"]
    }
  ]
}

## 规则
- 总关卡数建议 5-12 关，难度递进，前后关联。
- chunk_ids 必须是整数，且只能来自工具返回的结果；不要臆造。
- files 只写仓库中真实存在的文件路径。
- 已完成的关卡不可删除、不可改名（提交时系统会校验并拒绝）。
- 未确认前不要调用 submit_roadmap；确认后只调用一次。
- 关卡间用 prerequisites 表达先修关系。
- **不要输出过渡语**（如"让我查看...""我先看看..."）。要么直接调用工具，要么输出给用户的正式回复——所有文本输出都会被视为正式回复。
- **仓库可能包含多语言翻译副本**（如 translations/ 或不同语言子目录），同一内容会出现多次。规划路线时只依据主语言版本（通常是 en/ 或根目录），忽略翻译副本，不要在回复中展示翻译副本。"""


class RoadmapAgent:
    """Conversational agent that plans learning roadmaps via tool calling."""

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.7,
            timeout=60,
            max_retries=0,
        )
        self._existing_roadmap: Optional[Dict] = None
        self._last_submitted_roadmap: Optional[Dict] = None

    # ── Compact structure context (L0 + L1, no chunk stuffing) ──

    def _build_structure_context(self, sources_info: List[Dict]) -> str:
        parts = []
        for s in sources_info:
            ra = s.get("repo_analysis") or {}
            toc = ra.get("readme_toc", [])
            groups = ra.get("dir_groups", [])
            conf = ra.get("structure_confidence") or {}
            logic = ra.get("structure_logic", "mixed")
            summaries = ra.get("file_summaries") or {}
            if not (toc or groups or summaries):
                continue
            parts.append(f"## 来源 #{s.get('source_id')}（结构置信度: {conf.get('level', 'unknown')}，逻辑: {logic}）")
            for r in conf.get("reasons", []):
                parts.append(f"  - {r}")
            if toc:
                parts.append("README 目录:")
                for item in toc[:20]:
                    parts.append(f"  - {item.get('title', '')}")
            if groups:
                parts.append("目录分组:")
                for g in groups[:25]:
                    marker = "📖" if g.get("is_chapter") else "📁"
                    parts.append(f"  {marker} {g.get('name')} ({g.get('count')} 文件)")
            if summaries:
                parts.append("文件摘要:")
                for fp, sm in list(summaries.items())[:40]:
                    parts.append(f"  - {fp}: {sm}")
        return "\n".join(parts) if parts else "（无仓库结构信息，请先调用 get_repo_structure）"

    # ── Tools ──

    def _build_tools(self, chunks: List[Dict], sources_info: List[Dict]):
        chunk_by_id = {c["id"]: c for c in chunks}
        by_file: Dict[str, list] = {}
        for c in chunks:
            fp = (c.get("meta") or {}).get("file", "") or f"chunk-{c['id']}"
            by_file.setdefault(fp, []).append(c)

        def first_repo_analysis() -> dict:
            for s in sources_info:
                ra = s.get("repo_analysis")
                if ra:
                    return ra
            return {}

        @tool
        def get_repo_structure() -> str:
            """返回仓库整体结构：README 目录、目录分组、结构置信度与逻辑类型。规划路线前先调用。"""
            ra = first_repo_analysis()
            if not ra:
                return "该来源没有可用的仓库结构分析（可能不是 GitHub 仓库或处理失败）。"
            conf = ra.get("structure_confidence") or {}
            lines = [f"结构置信度: {conf.get('level', '?')} | 结构逻辑: {ra.get('structure_logic', 'mixed')}"]
            for r in conf.get("reasons", []):
                lines.append(f"  - {r}")
            toc = ra.get("readme_toc", [])
            if toc:
                lines.append("README 目录:")
                lines += [f"  - {t.get('title', '')}" for t in toc[:30]]
            groups = ra.get("dir_groups", [])
            if groups:
                lines.append("目录分组:")
                lines += [f"  📁 {g.get('name')} ({g.get('count')} 文件)" for g in groups[:30]]
            lines.append(f"总文件数: {ra.get('total_files', '?')}")
            return "\n".join(lines)

        @tool
        def get_file_summaries(files: Optional[List[str]] = None) -> str:
            """返回文件的一句话摘要。files 可指定部分文件路径，缺省返回全部已有摘要。"""
            ra = first_repo_analysis()
            summaries = ra.get("file_summaries") or {}
            if not summaries:
                return "尚无文件摘要。可用 list_chunks 查看各文件内容。"
            keys = files or list(summaries.keys())
            return "\n".join(f"- {fp}: {summaries.get(fp, '（无摘要）')}" for fp in keys[:60])

        @tool
        def list_chunks(file: str, limit: int = 10) -> str:
            """列出某个文件下的切片（id + 标题 + 预览）。file 为仓库内文件路径（支持模糊匹配）。"""
            hits = [fp for fp in by_file if file in fp]
            if not hits:
                return f"未找到包含 '{file}' 的文件。可用 get_repo_structure 查看文件列表。"
            out = []
            for fp in hits[:3]:
                cs = by_file[fp]
                out.append(f"## {fp} ({len(cs)} 块)")
                for c in cs[:limit]:
                    meta = c.get("meta") or {}
                    heads = " > ".join(meta.get("headings", [])[:3])
                    out.append(f"[chunk-{c['id']}] {heads}\n  {c['content'][:200]}")
            return "\n".join(out)

        @tool
        def read_chunk(chunk_ids: List[int]) -> str:
            """读取指定切片的完整内容。chunk_ids 为整数列表。"""
            out = []
            for cid in chunk_ids:
                c = chunk_by_id.get(cid)
                if c:
                    out.append(f"[chunk-{cid}]\n{c['content']}\n")
                else:
                    out.append(f"[chunk-{cid}] （不存在）")
            return "\n---\n".join(out)

        @tool
        async def search_chunks(query: str, top_k: int = 10) -> str:
            """按语义搜索相关切片。仅在其他工具不足以定位内容时使用。"""
            from app.services.lecture_agent import LectureAgent
            hits = await LectureAgent()._retrieve_relevant_chunks(query, chunks, top_k=top_k)
            if not hits:
                return "未找到相关切片。"
            out = []
            for c in hits[:top_k]:
                meta = c.get("meta") or {}
                heads = " > ".join(meta.get("headings", [])[:3])
                out.append(f"[chunk-{c['id']}] {heads}\n  {c['content'][:250]}")
            return "\n".join(out)

        @tool
        def submit_roadmap(checkpoints: List[dict]) -> str:
            """用户确认后提交最终路线。系统会校验已学关卡不可删除；校验通过后路线生效。"""
            errors = self._validate_roadmap(checkpoints)
            if errors:
                return ("提交被拒绝：\n" + "\n".join(f"- {e}" for e in errors)
                        + "\n请修正后重新提交。")
            self._last_submitted_roadmap = {"checkpoints": checkpoints}
            return f"✅ 路线已确认并保存，共 {len(checkpoints)} 关。请向用户简要总结最终路线。"

        return [get_repo_structure, get_file_summaries, list_chunks,
                read_chunk, search_chunks, submit_roadmap]

    # ── Validation ──

    def _validate_roadmap(self, checkpoints: List[dict]) -> List[str]:
        errors = []
        if not checkpoints:
            return ["路线为空"]
        orders = [c.get("order") for c in checkpoints]
        if len(orders) != len(set(orders)):
            errors.append("order 存在重复")
        existing = self._existing_roadmap or {}
        existing_cps = existing.get("checkpoints", [])
        completed_titles = {c.get("title") for c in existing_cps if c.get("completed")}
        new_titles = {c.get("title") for c in checkpoints}
        for t in completed_titles:
            if t and t not in new_titles:
                errors.append(f"已学关卡「{t}」不可删除或改名")
        for c in checkpoints:
            title = c.get("title", "")
            if not title:
                errors.append("存在没有标题的关卡")
            for p in c.get("prerequisites", []):
                if p not in orders:
                    errors.append(f"关卡「{title}」的前置 {p} 不存在")
        return errors

    # ── Chat loop ──

    async def chat(
        self,
        message: str,
        history: List[Dict[str, str]],
        topic: str = "",
        chunks: Optional[List[Dict]] = None,
        existing_roadmap: Optional[Dict] = None,
        sources_info: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Process a chat message with tool calling; returns reply + optional roadmap."""
        self._existing_roadmap = existing_roadmap
        self._last_submitted_roadmap = None
        chunks = chunks or []
        sources_info = sources_info or []

        try:
            return await self._chat_with_tools(message, history, topic, chunks, sources_info)
        except Exception as e:
            # Fallback: legacy single-shot path (robustness)
            print(f"[RoadmapAgent] tool-calling failed, falling back: {type(e).__name__}: {str(e)[:200]}")
            return await self._chat_legacy(message, history, topic, chunks, sources_info)

    async def _chat_with_tools(self, message, history, topic, chunks, sources_info):
        tools = self._build_tools(chunks, sources_info)
        llm = self.llm.bind_tools(tools)
        tool_map = {t.name: t for t in tools}

        system_content = SYSTEM_PROMPT + f"\n\n## 学习主题\n{topic}\n\n## 仓库结构速览\n{self._build_structure_context(sources_info)}"
        if existing_roadmap := self._existing_roadmap:
            roadmap_json = json.dumps(existing_roadmap, ensure_ascii=False, indent=2)[:4000]
            system_content += (
                f"\n\n## 当前路线图\n{roadmap_json}\n\n"
                "用户可能要求修改路线。已学关卡（completed=true）不可删除或改名。"
                "只有在用户明确确认时才能调用 submit_roadmap。"
            )

        messages: List = [SystemMessage(content=system_content)]
        for msg in history[-20:]:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=message))

        for _ in range(MAX_TOOL_ROUNDS):
            resp = await llm.ainvoke(messages)
            messages.append(resp)
            tool_calls = getattr(resp, "tool_calls", None) or []
            if not tool_calls:
                break
            for tc in tool_calls:
                fn = tool_map.get(tc.get("name"))
                if not fn:
                    messages.append(ToolMessage(content=f"未知工具 {tc.get('name')}", tool_call_id=tc.get("id")))
                    continue
                try:
                    result = await fn.ainvoke(tc.get("args") or {})
                    result = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                except Exception as e:
                    result = f"工具调用失败: {type(e).__name__}: {str(e)[:200]}"
                messages.append(ToolMessage(content=result, tool_call_id=tc.get("id")))

        # Tool rounds exhausted while still calling tools → force a final text
        # answer so the user never sees raw tool output as the reply.
        if isinstance(messages[-1], ToolMessage):
            messages.append(HumanMessage(
                content="请基于以上工具结果，直接给出完整、自然的回复，不要再调用工具。"))
            resp = await llm.ainvoke(messages)
            messages.append(resp)

        # Reply = last assistant text message (never raw tool output)
        reply = ""
        for m in reversed(messages):
            if isinstance(m, AIMessage) and m.content and str(m.content).strip():
                reply = m.content if isinstance(m.content, str) else str(m.content)
                break
        if not reply:
            reply = ("我已经查看了相关资料，接下来想先了解你的基础："
                     "你更熟悉 Python 吗？希望每天投入多少时间学习？")
        return {
            "message": reply,
            "updated_roadmap": self._last_submitted_roadmap,
        }

    # ── Legacy fallback (pre-T2 single-shot) ──

    def _build_enriched_context(self, chunks: List[Dict], sources_info: List[Dict] = None) -> str:
        parts = []

        ra = {}
        for s in (sources_info or []):
            if s.get("repo_analysis"):
                ra = s["repo_analysis"]
                break
        toc = ra.get("readme_toc", [])
        groups = ra.get("dir_groups", [])
        if toc:
            parts.append("## 仓库目录")
            parts += [f"  - {item.get('title', '')}" for item in toc[:10]]
            parts.append("")
        if groups:
            parts.append("## 章节分布")
            for g in groups[:20]:
                marker = "📖" if g.get("is_chapter") else "📁"
                parts.append(f"  {marker} {g.get('name')} ({g.get('count')} files)")
            parts.append("")

        if chunks:
            by_file = {}
            for c in chunks:
                meta = c.get("meta", {}) if isinstance(c.get("meta"), dict) else {}
                fp = meta.get("file", "") or f"chunk-{c['id']}"
                by_file.setdefault(fp, []).append(c)
            chapter_files = sorted(fp for fp in by_file if "chapter_" in fp)
            other_files = sorted(fp for fp in by_file if "chapter_" not in fp)
            parts.append(f"## 参考资料 ({len(chunks)} 块, {len(by_file)} 个文件)")
            count = 0
            for fp in chapter_files + other_files:
                if count >= 15:
                    parts.append(f"  ... 以及其他 {len(by_file) - 15} 个文件")
                    break
                file_chunks = by_file[fp]
                meta = file_chunks[0].get("meta", {}) if isinstance(file_chunks[0].get("meta"), dict) else {}
                headings = meta.get("headings", [])
                hint = (meta.get("topic_hints", [""]) or [""])[0]
                tags = f" → {hint[:40]}" if hint else ""
                parts.append(f"  📄 {fp} ({len(file_chunks)} 块){tags}")
                for c in file_chunks[:1]:
                    parts.append(f"     [chunk-{c['id']}] {c['content'][:120]}...")
                count += 1

        return "\n".join(parts)

    async def _chat_legacy(self, message, history, topic, chunks, sources_info=None):
        context = self._build_enriched_context(chunks, sources_info)
        system_content = SYSTEM_PROMPT + f"\n\n## 学习主题\n{topic}\n\n## 参考资料切片\n{context}"

        if self._existing_roadmap:
            roadmap_json = json.dumps(self._existing_roadmap, ensure_ascii=False, indent=2)
            system_content += (
                f"\n\n## 当前路线图（已有部分进度）\n{roadmap_json}\n\n"
                "用户想修改路线图。已完成的关卡不可删除，但可以在前后插入新关卡。请根据对话调整。\n"
                "如果用户明确表示确认，输出完整的更新后 JSON 路线图。"
            )

        lc_messages = [SystemMessage(content=system_content)]
        for msg in history:
            if msg["role"] == "user":
                lc_messages.append(HumanMessage(content=msg["content"]))
            else:
                lc_messages.append(AIMessage(content=msg["content"]))
        lc_messages.append(HumanMessage(content=message))

        response = await self.llm.ainvoke(lc_messages)
        reply = response.content

        updated_roadmap = None
        if "```json" in reply:
            try:
                json_str = reply.split("```json")[1].split("```")[0].strip()
                parsed = json.loads(json_str)
                if "checkpoints" in parsed:
                    updated_roadmap = parsed
            except (json.JSONDecodeError, IndexError):
                pass

        return {"message": reply, "updated_roadmap": updated_roadmap}
