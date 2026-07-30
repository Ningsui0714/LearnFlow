"""
Learning Route Agent Service.

Uses LangChain + an LLM to:
- Chat with the user about their learning goals
- Generate / revise a checkpoint-based roadmap
- Assign relevant chunks to each checkpoint
"""
import json
from typing import List, Optional, Dict, Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.core.config import settings

# ── Prompt templates ──

SYSTEM_PROMPT = """你是一名学习路线规划专家。你的任务是帮助用户为特定学习主题规划一条循序渐进的学习路线。

## 你的工作流程：
1. 首先分析用户提供的参考资料（已切片并编号为 [chunk-xxx]）。
2. 与用户对话了解他们的基础水平、学习目标和可用时间。
3. 提出一个初始学习路线方案，包含若干个关卡（checkpoint）。
4. 根据用户反馈调整路线方案。
5. 最终确认后，输出格式化的路线 JSON。

## 输出格式（最终确认后）：
```json
{{
  "checkpoints": [
    {{
      "title": "关卡名称",
      "description": "学习目标描述",
      "order": 1,
      "prerequisites": [],
      "chunk_ids": [关联的切片ID列表],
      "completed": false
    }}
  ]
}}
```

## 每关要求：
- 标题简洁，描述学习目标
- prerequisites 是前置关卡的 order 列表
- **chunk_ids 必须是整数切片编号**，从参考资料中 `[chunk-xxx]` 标记提取
  ✅ 正确: "chunk_ids": [12, 15, 23]
  ❌ 错误: "chunk_ids": ["chapter_xx"] 或 ["chunk-12"]
- 只有当你看到 `[chunk-N]` 标记时才使用对应的数字 N
- 难度递进，前后关联
- 总关卡数建议 5-12 关（视主题复杂度调整）

## 与用户交互时：
- 主动给出方案，不要问"你想要什么"，而是说"我建议这样"
- 如果用户反驳，解释原因并调整
- 关卡之间要有明确的先修关系
- 适时总结当前的路线方案"""


class RoadmapAgent:
    """Conversational agent that plans learning roadmaps."""

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.7,
            timeout=60,  # Increased for large contexts
            max_retries=0,
        )

    def _build_context(self, chunks: List[Dict]) -> str:
        """Build a readable chunk context for the LLM."""
        if not chunks:
            return "暂无参考资料。"
        parts = []
        for c in chunks[:50]:  # Limit context size
            preview = c["content"][:300]
            parts.append(f"[chunk-{c['id']}]\n{preview}\n")
        if len(chunks) > 50:
            parts.append(f"... 还有 {len(chunks) - 50} 个切片未展示")
        return "\n---\n".join(parts)

    def _build_enriched_context(self, chunks: List[Dict], dir_info: Optional[Dict] = None) -> str:
        """Build enriched context with directory structure and organized chunks."""
        parts = []

        # Section 1: Directory structure (if available) — condensed
        if dir_info and dir_info.get("repo_analysis"):
            ra = dir_info["repo_analysis"]
            toc = ra.get("readme_toc", [])
            groups = ra.get("dir_groups", [])

            if toc:
                parts.append("## 仓库目录")
                for item in toc[:10]:
                    parts.append(f"  - {item.get('title', '')}")
                parts.append("")

            if groups:
                parts.append("## 章节分布")
                for g in groups[:20]:
                    marker = "📖" if g.get("is_chapter") else "📁"
                    parts.append(f"  {marker} {g['name']} ({g['count']} files)")
                parts.append("")

        # Section 2: Chunks by file — show only representative samples
        if chunks:
            by_file = {}
            for c in chunks:
                meta = c.get("meta", {}) if isinstance(c.get("meta"), dict) else {}
                fp = meta.get("file", "") or f"chunk-{c['id']}"
                if fp not in by_file:
                    by_file[fp] = []
                by_file[fp].append(c)

            # Sort files: chapter dirs first, then others
            chapter_files = [fp for fp in by_file if 'chapter_' in fp]
            other_files = [fp for fp in by_file if 'chapter_' not in fp]
            sorted_files = sorted(chapter_files) + sorted(other_files)

            parts.append(f"## 参考资料 ({len(chunks)} 块, {len(by_file)} 个文件)")
            count = 0
            for fp in sorted_files:
                if count >= 15:  # Show only first 15 files
                    remaining = len(sorted_files) - 15
                    parts.append(f"  ... 以及其他 {remaining} 个文件 ({len(chunks)} 块)")
                    break
                file_chunks = by_file[fp]
                meta = file_chunks[0].get("meta", {}) if isinstance(file_chunks[0].get("meta"), dict) else {}
                headings = meta.get("headings", [])
                hint = (meta.get("topic_hints", [""]) or [""])[0]
                tags = f" → {hint[:40]}" if hint else ""
                parts.append(f"  📄 {fp} ({len(file_chunks)} 块){tags}")
                for c in file_chunks[:1]:  # Only first chunk preview
                    preview = c["content"][:120]
                    parts.append(f"     [chunk-{c['id']}] {preview}...")
                count += 1

        return "\n".join(parts)

    async def chat(
        self,
        message: str,
        history: List[Dict[str, str]],
        topic: str = "",
        chunks: Optional[List[Dict]] = None,
        existing_roadmap: Optional[Dict] = None,
        dir_info: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Process a chat message and return response + optional roadmap update.
        """
        # Use enriched context when available
        context = self._build_enriched_context(chunks or [], dir_info)

        system_content = SYSTEM_PROMPT + f"\n\n## 学习主题\n{topic}\n\n## 参考资料切片\n{context}"

        if existing_roadmap:
            roadmap_json = json.dumps(existing_roadmap, ensure_ascii=False, indent=2)
            system_content += f"\n\n## 当前路线图（已有部分进度）\n{roadmap_json}\n\n用户想修改路线图。已完成的关卡不可删除，但可以在前后插入新关卡。请根据对话调整。\n如果用户明确表示确认，输出完整的更新后 JSON 路线图。"

        # Convert history to LangChain messages
        lc_messages = [SystemMessage(content=system_content)]
        for msg in history:
            if msg["role"] == "user":
                lc_messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                lc_messages.append(AIMessage(content=msg["content"]))
        lc_messages.append(HumanMessage(content=message))

        response = await self.llm.ainvoke(lc_messages)
        reply = response.content

        # Try to extract JSON roadmap from response
        updated_roadmap = None
        if "```json" in reply:
            try:
                json_str = reply.split("```json")[1].split("```")[0].strip()
                parsed = json.loads(json_str)
                if "checkpoints" in parsed:
                    updated_roadmap = parsed
            except (json.JSONDecodeError, IndexError):
                pass

        return {
            "message": reply,
            "updated_roadmap": updated_roadmap,
        }
