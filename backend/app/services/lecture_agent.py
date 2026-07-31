"""
Lecture Generation Agent.

Two-phase process:
1. Plan: LLM plans lecture outline from checkpoint title + chunks + user level
2. Generate: Stream each section with full content, formulas, ASCII diagrams
"""
import json
import re
from typing import AsyncGenerator, List, Dict, Optional, Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.core.config import settings

PLAN_PROMPT = """你是学习内容专家。你需要为某个学习关卡规划一份讲义大纲。

## 学习关卡
{checkpoint_title}: {checkpoint_description}

## 学生水平
{user_level}

## 参考资料
{chunk_context}

## 要求
1. 规划 4-8 个小节，每节一个清晰的主题
2. 每节约 300-800 字正文，配合公式和图表
3. 难度递进，前后衔接
4. 每节末尾有 1-2 个自查问题

## 输出格式（JSON）
```json
{{
  "sections": [
    {{
      "title": "小节标题",
      "keywords": ["关键词1", "关键词2"],
      "goal": "本节学习目标"
    }}
  ]
}}
```"""

GENERATE_SECTION_PROMPT = """你是学习内容专家。根据大纲生成完整的小节内容。

## 关卡
{checkpoint_title}

## 本节信息
标题: {section_title}
关键词: {keywords}
目标: {goal}

## 参考资料
{chunk_context}

## 生成要求
1. 用 **markdown 格式** 输出
2. 关键公式用 KaTeX 语法：
   - 行内公式: $E = mc^2$
   - 块级公式: $$L(θ) = \\frac{1}{n}\\sum_{i=1}^n (y_i - \\hat{y}_i)^2$$
3. 复杂结构用 ASCII 图，例如：
   ```
       层1    层2    输出
      x₁ → ○ → ○ → ŷ
      x₂ → ○ → ○
   ```
4. 关键技术术语用 **加粗**
5. 引用参考资料时标注 `[chunk-N]`
6. 代码示例用 ```python 代码块
7. 末尾放 1-2 个自查问题（用 > **思考题:** 开头）

## 输出
直接输出 markdown 内容，不要额外的 JSON 包裹。"""


class QueryExpander:
    """Expand user queries with synonyms and related terms."""

    SYNONYMS = {
        "梯度下降": ["gradient descent", "gd", "参数更新", "最速下降法", "steepest descent"],
        "反向传播": ["backpropagation", "backprop", "bp", "链式法则", "chain rule", "误差反向传播"],
        "卷积": ["convolution", "cnn", "特征提取", "卷积核", "filter", "kernel", "特征图", "feature map"],
        "损失函数": ["loss function", "代价函数", "目标函数", "objective", "误差函数", "loss"],
        "注意力": ["attention", "self-attention", "transformer", "缩放点积", " scaled dot-product"],
        "激活函数": ["activation", "relu", "sigmoid", "tanh", "非线性"],
        "正则化": ["regularization", "weight decay", "dropout", "l2", "过拟合", "overfitting"],
        "归一化": ["normalization", "batch norm", "layer norm", "标准化"],
        "过拟合": ["overfitting", "正则化", "regularization", "泛化", "generalization"],
        "线性回归": ["linear regression", "线性模型", "最小二乘", "least squares"],
        "softmax": ["softmax", "交叉熵", "cross entropy", "多类分类", "multiclass"],
        "循环神经网络": ["rnn", "recurrent", "lstm", "gru", "序列模型", "sequence"],
        "embedding": ["词向量", "word vector", "词嵌入", "representation learning"],
        "学习率": ["learning rate", "lr", "步长", "step size", "调度", "schedule"],
        "优化器": ["optimizer", "sgd", "adam", "momentum", "优化算法"],
        "transformer": ["attention", "self-attention", "多头注意力", "multi-head", "encoder-decoder"],
    }

    @staticmethod
    def expand(query: str) -> list:
        """Expand query with synonyms and related terms."""
        keywords = set()
        # Split into individual terms
        terms = re.split(r"[\s,，、/]+", query.lower().strip())
        for term in terms:
            if len(term) < 2:
                continue
            keywords.add(term)
            # Check against synonym dict (both Chinese and English keys)
            for key, syns in QueryExpander.SYNONYMS.items():
                if term in key.lower() or any(term == s.lower() for s in syns):
                    keywords.update(s.lower() for s in syns)
                    keywords.add(key.lower())
        return [k for k in keywords if k]

    @staticmethod
    def estimate_complexity(query: str) -> int:
        """Estimate question complexity: 1=simple, 2=medium, 3=complex."""
        query_lower = query.lower()
        # Complex: comparison, why, multiple concepts
        complex_words = ["为什么", "对比", "区别", "关系", "vs", "versus", "二者", "三者",
                        "比较", "联系", "综合", "整体", "系统"]
        if any(w in query_lower for w in complex_words):
            return 3
        # Medium: how, process, with code
        medium_words = ["如何", "怎么", "implement", "实现", "过程", "推导",
                       "证明", "公式", "code", "代码"]
        if any(w in query_lower for w in medium_words):
            return 2
        # Simple: what is, definition
        return 1

    @staticmethod
    def dynamic_top_k(query: str, base_k: int = 15) -> int:
        """Dynamic recall count based on question complexity."""
        c = QueryExpander.estimate_complexity(query)
        mapping = {1: 8, 2: 15, 3: 25}
        return mapping.get(c, base_k)


class LectureAgent:
    """Generates structured lecture content for a checkpoint."""

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.7,
            timeout=90,
            max_retries=0,
        )
        self.gen_llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.8,
            timeout=60,
            max_retries=0,
        )

    def _build_chunk_context(self, chunks: List[Dict]) -> str:
        """Build chunk context for a specific checkpoint's relevant chunks."""
        if not chunks:
            return "无参考资料"
        parts = []
        for c in chunks:
            content = c["content"]
            parts.append(f"[chunk-{c['id']}]\n{content}\n")
        return "\n---\n".join(parts)

    async def _retrieve_relevant_chunks(
        self,
        query: str,
        chunks: List[Dict],
        top_k: int = 15,
        extra_keywords: Optional[List[str]] = None,
        boost_ids: Optional[List[int]] = None,
        boost_weight: float = 1.5,
        scope_files: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        Level 1-3 fallback retrieval with query expansion + dynamic top-k.

        T3: accepts upstream retrieval state from CheckpointBrief —
        boost_ids get a score bonus; scope_files restricts the pool first
        (falls back to global when the scope pool is too small).
        """
        if not chunks:
            return []

        # Determine dynamic top-k from query complexity
        effective_k = QueryExpander.dynamic_top_k(query, top_k)

        # Scope restriction (from upstream brief)
        pool = chunks
        if scope_files:
            scoped = [c for c in chunks if (c.get("meta") or {}).get("file") in scope_files]
            if len(scoped) >= max(3, int(effective_k * 0.6)):
                pool = scoped

        # Expand query with synonyms
        expanded = QueryExpander.expand(query)
        if extra_keywords:
            expanded.extend(k.lower() for k in extra_keywords if len(k) > 1)
        expanded = list(dict.fromkeys(expanded))  # uniquify

        if not expanded:
            return pool[:effective_k]

        scored = []
        # Try to load embeddings for vector search
        vector_cache = None
        try:
            from app.services.embedding import load_cache, embed_text, cosine_similarity
            cache = load_cache()
            if cache and len(cache) > 0:
                query_emb = embed_text(query)
                vector_cache = (cache, query_emb)
        except Exception:
            pass

        for c in pool:
            meta = c.get("meta", {}) if isinstance(c.get("meta"), dict) else {}
            score = 0.0

            # Level 1: File path match (weight: 5)
            file_path = (meta.get("file") or "").lower()
            heading_text = " ".join(meta.get("headings") or []).lower()
            for kw in expanded:
                if kw in file_path:
                    score += 5.0
                if kw in heading_text:
                    score += 3.0

            # Level 2: topic_hints match (weight: 3)
            hints = " ".join(meta.get("topic_hints") or []).lower()
            for kw in expanded:
                if kw in hints:
                    score += 3.0

            # Level 3: Content keyword density (weight: 1-5)
            content_lower = c.get("content", "").lower()
            total_len = len(content_lower) or 1
            keyword_count = sum(content_lower.count(kw) for kw in expanded)
            density = keyword_count / (total_len / 1000)
            score += min(density * 1.5, 5.0)

            # Vector similarity (weight: 10) — if cache available
            if vector_cache:
                cache, query_emb = vector_cache
                key = f"chunk-{c['id']}"
                if key in cache:
                    from app.services.embedding import cosine_similarity
                    vec_score = cosine_similarity(query_emb, cache[key])
                    score += vec_score * 10.0

            # Upstream boost (T3: high-relevance chunks from upstream agents)
            if boost_ids and c["id"] in boost_ids:
                score += boost_weight

            scored.append((score, c))

        # Sort by score descending, take top_k
        scored.sort(key=lambda x: -x[0])
        top = [c for _, c in scored[:top_k]]

        # If no meaningful scores, fallback to first chunks
        if all(s[0] == 0 for s in scored):
            return pool[:min(top_k, len(pool))]

        return top

    @staticmethod
    def _safe_format(template: str, **kwargs) -> str:
        """Format a string using simple placeholder substitution (not .format) to avoid { } conflicts."""
        result = template
        # Replace {{ and }} first (they should become { and } in output)
        result = result.replace("{{", "\x00LEFT\x00").replace("}}", "\x00RIGHT\x00")
        for key, value in kwargs.items():
            result = result.replace("{" + key + "}", str(value))
        result = result.replace("\x00LEFT\x00", "{").replace("\x00RIGHT\x00", "}")
        return result

    async def plan_lecture(
        self,
        checkpoint_title: str,
        checkpoint_description: str,
        user_level: str,
        chunks: List[Dict],
        brief: Optional[Dict] = None,
    ) -> List[Dict]:
        """Plan lecture outline using retrieved relevant chunks."""
        # Retrieve top chunks matching the topic
        query = f"{checkpoint_title} {checkpoint_description}"
        rp = (brief or {}).get("retrieval_policy") or {}
        relevant = await self._retrieve_relevant_chunks(
            query, chunks, top_k=15,
            boost_ids=rp.get("boost_chunk_ids"),
            boost_weight=rp.get("boost_weight", 1.5),
            scope_files=(brief or {}).get("scope", {}).get("files"),
        )
        ctx = "\n".join([c["content"][:800] for c in relevant])

        prompt = self._safe_format(PLAN_PROMPT,
            checkpoint_title=checkpoint_title,
            checkpoint_description=checkpoint_description,
            user_level=user_level,
            chunk_context=ctx,
        )

        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content

        # Extract JSON
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content

        try:
            parsed = json.loads(json_str)
            return parsed.get("sections", [])
        except json.JSONDecodeError:
            # Fallback: single section
            return [{"title": checkpoint_title, "keywords": [], "goal": checkpoint_description}]

    async def generate_section(
        self,
        checkpoint_title: str,
        section: Dict,
        chunks: List[Dict],
        section_keywords: Optional[List[str]] = None,
        brief: Optional[Dict] = None,
    ) -> str:
        """Generate a single section's content, using retrieved relevant chunks."""
        # Retrieve chunks relevant to this section's title + keywords
        query = section.get("title", "")
        extra_kw = (section_keywords or []) + [checkpoint_title]
        rp = (brief or {}).get("retrieval_policy") or {}
        relevant = await self._retrieve_relevant_chunks(
            query, chunks, top_k=10, extra_keywords=extra_kw,
            boost_ids=rp.get("boost_chunk_ids"),
            boost_weight=rp.get("boost_weight", 1.5),
            scope_files=(brief or {}).get("scope", {}).get("files"),
        )
        ctx = self._build_chunk_context(relevant)

        prompt = self._safe_format(GENERATE_SECTION_PROMPT,
            checkpoint_title=checkpoint_title,
            section_title=section.get("title", ""),
            keywords=", ".join(section.get("keywords", [])),
            goal=section.get("goal", ""),
            chunk_context=ctx,
        )

        response = await self.gen_llm.ainvoke([HumanMessage(content=prompt)])
        return response.content

    async def generate_full_lecture(
        self,
        checkpoint_title: str,
        checkpoint_description: str,
        user_level: str,
        chunks: List[Dict],
    ) -> AsyncGenerator[Dict, None]:
        """
        Full lecture pipeline: plan → stream sections one by one.
        Yields dicts with section data.
        """
        # Step 1: Plan — yield planning event first
        yield {"type": "status", "message": "正在检索相关切片..."}
        # Pre-retrieve for progress feedback
        query = f"{checkpoint_title} {checkpoint_description}"
        matched = await self._retrieve_relevant_chunks(query, chunks, top_k=1)
        match_count = len(matched) or len(chunks)
        yield {"type": "status", "message": f"找到 {match_count} 个相关切片，规划大纲中..."}
        sections = await self.plan_lecture(
            checkpoint_title, checkpoint_description, user_level, chunks
        )

        total = len(sections)

        # Step 2: Generate each section
        for i, section in enumerate(sections):
            content = await self.generate_section(
                checkpoint_title, section, chunks,
                section_keywords=section.get("keywords", []),
            )

            yield {
                "type": "section",
                "index": i,
                "total": total,
                "title": section.get("title", f"第{i+1}节"),
                "keywords": section.get("keywords", []),
                "content": content,
                "questions": self._extract_questions(content),
            }

        # Done signal
        yield {"type": "done", "sections_count": total}

    def _extract_questions(self, content: str) -> List[str]:
        """Extract check questions from content."""
        questions = []
        for line in content.split("\n"):
            if "**思考题**" in line or "**思考题:**" in line:
                questions.append(line.replace("**思考题**", "").replace("**思考题:**", "").strip())
            elif line.strip().startswith(">") and "?" in line:
                questions.append(line.strip().lstrip(">").strip())
        return questions


class QAAgent:
    """Q&A agent for follow-up questions on selected lecture text."""

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.5,
            timeout=30,
            max_retries=0,
        )

    async def answer(
        self,
        question: str,
        selected_text: str,
        section_content: str,
        checkpoint_title: str,
        history: List[Dict[str, str]],
    ) -> str:
        """Answer a question about selected text in a lecture."""

        system_prompt = f"""你是一名学习辅导助手。用户在阅读以下讲义内容时提出了问题。

## 当前关卡
{checkpoint_title}

## 讲义上下文（用户选中的段落所在小节）
{section_content[:3000]}

## 用户选中的文字
「{selected_text}」

## 你的角色
- 回答要聚焦在被选中文字和问题上
- 可以引述公式、扩展例子来解释
- 如果用户问的问题讲义已有清晰解释，先指出在讲义的哪部分
- 如果问题超出了讲义范围，简要说明并引导回当前内容
- 用 KaTeX 语法写公式
- 回答不宜过长，200-400 字为佳"""

        messages = [SystemMessage(content=system_prompt)]
        for msg in history[-6:]:  # Last 6 messages for context
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=question))

        response = await self.llm.ainvoke(messages)
        return response.content
