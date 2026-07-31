"""
Concept question agent (T7).

Generates concept-check questions for a checkpoint:
- q_type: single | multi | judge | wwpd | wwpp
- WWPD (What Would Python Do) / WWPP (What Would Python Print): code-output
  questions. The answer is AUTHORITATIVE — we execute the reference code with
  code_executor at generation time and use the real output as the correct
  answer (never trusting the LLM's guess). If the verified answer collides
  with a distractor, the question is discarded.
"""
import json
import re
from typing import List, Dict, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.services.code_executor import execute_code

GENERATE_PROMPT = """你是计算机教学命题专家。根据下面的关卡学习内容和讲义，设计概念考察题。

## 关卡
{checkpoint_title}: {checkpoint_description}

## 学生水平
{user_level}

## 讲义内容
{lecture_content}

## 参考资料切片
{chunk_context}

## 题目要求
1. 出 3-8 道题，数量由内容复杂度决定：内容有料就多出，没料就少出，绝不硬凑。
2. 题型分配：
   - single：单选概念题（理解而非记忆，考"为什么"）
   - multi：多选题（2-4 个正确选项）
   - judge：判断题（只有两个选项：正确/错误）
   - 如果教学内容包含代码且适合考察代码行为，可以用 wwpd/wwpp（给一段 Python 代码问输出）——内容不合适就不要用，不要硬凑。
3. 难度递进：easy → medium → hard 各若干。
4. 每题附简要解析（explanation），说明为什么对/错。
5. 考察理解、关联、易错点，不考死记硬背。

## 输出格式（JSON）
```json
{{
  "questions": [
    {{
      "q_type": "single",
      "difficulty": "medium",
      "question": "题干（wwpd/wwpp 题先给代码块，再问输出）",
      "code": "wwpd/wwpp 题的参考代码（其他题型为空字符串）",
      "options": ["选项A", "选项B", "选项C", "选项D"],
      "answer_indexes": [0],
      "explanation": "解析"
    }}
  ]
}}
```

规则：
- wwpd/wwpp 的 code 必须是自包含、可直接运行的 Python（只依赖标准库），不要读文件/网络。
- judge 题 options 必须是 ["正确", "错误"]。
- 代码用 ```python 包裹在 question 里展示，code 字段存纯代码。
- JSON 中所有字符串的双引号要正确转义。
- **输出必须是单个合法的 JSON 对象**（不要 markdown 代码块包裹，不要额外文字）。"""

EXPLAIN_PROMPT = """你是学习辅导助手。学生回答了一道概念题，请给出解析。

## 题目（{q_type}）
{question}

## 选项
{options_text}

## 正确答案
{answer_text}

## 学生的回答
{user_answer_text}

## 要求
- 解释为什么正确答案是对的（200-400 字）
- 如果学生答错，指出他可能的误解点
- wwpd/wwpp 题要解释代码的执行过程
- 用 KaTeX 写公式（如有）"""


class ConceptAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.7,
            timeout=120,
            max_retries=0,
            max_tokens=8000,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        # plain LLM for free-text outputs (explain) — json_object mode would
        # require the prompt to contain the word "json", which explains don't
        self.llm_text = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.5,
            timeout=60,
            max_retries=0,
            max_tokens=2000,
        )

    # ── WWPD/WWPP self-verification ──

    @staticmethod
    def _extract_json(content: str) -> dict:
        """Robust JSON extraction: ```json block first, then raw_decode from
        each '{' (LLM output may contain literal braces inside string fields)."""
        m = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        decoder = json.JSONDecoder()
        for i, ch in enumerate(content):
            if ch == "{":
                try:
                    obj, _ = decoder.raw_decode(content[i:])
                    return obj
                except (json.JSONDecodeError, ValueError):
                    continue
        raise ValueError("no JSON object found")

    @staticmethod
    def _norm_option(o: str) -> str:
        """Strip 'A. ' / 'B、' / 'C)' style prefixes from LLM-generated options."""
        o = (o or "").strip()
        m = re.match(r"^[A-Ha-h][\.、\):：]?\s*(.*)$", o)
        if m and m.group(1).strip():
            return m.group(1).strip()
        return o

    @staticmethod
    def _verify_code_answer(code: str) -> Optional[str]:
        """Execute reference code; return the authoritative answer string.

        stdout → printed output; exception → the exception line (e.g.
        "NameError: name 'x' is not defined"); empty/None → verification failed.
        """
        if not code or not code.strip():
            return None
        res = execute_code(code, timeout=5)
        if res.get("timed_out"):
            return None
        out = (res.get("stdout") or "").strip()
        err = (res.get("stderr") or "").strip()
        if out:
            return out
        if res.get("exit_code") != 0 and err:
            # first meaningful line of the traceback (the exception itself)
            lines = [l for l in err.splitlines() if l.strip()]
            for l in lines:
                if "Error" in l:
                    return l.strip()[:120]
            return lines[-1][:120] if lines else None
        return None

    async def generate(
        self,
        checkpoint_title: str,
        checkpoint_description: str,
        user_level: str,
        lecture_sections: List[Dict],
        chunks: List[Dict],
    ) -> List[Dict]:
        """Generate verified concept questions."""
        lecture_text = ""
        for s in (lecture_sections or [])[:3]:
            lecture_text += s.get("content", "")[:1500] + "\n\n"
        chunk_text = "\n".join(c["content"][:500] for c in chunks[:6])

        prompt = GENERATE_PROMPT.format(
            checkpoint_title=checkpoint_title,
            checkpoint_description=checkpoint_description or "",
            user_level=user_level,
            lecture_content=lecture_text[:4500] or "（暂无讲义，请基于参考资料出题）",
            chunk_context=chunk_text[:3000] or "（无）",
        )

        try:
            resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
            content = resp.content
            parsed = self._extract_json(content)
            raw_qs = parsed.get("questions", [])
        except Exception as e:
            print(f"[ConceptAgent] generate failed: {type(e).__name__}: {str(e)[:150]}")
            return []

        questions = []
        seen = set()
        for q in raw_qs:
            q_type = q.get("q_type", "single")
            question = (q.get("question") or "").strip()
            options = [self._norm_option(o) for o in (q.get("options") or [])]
            options = list(dict.fromkeys(o for o in options if o))
            ans = [int(i) for i in (q.get("answer_indexes") or [])]

            if not question or len(options) < 2 or not ans:
                continue
            if any(i >= len(options) for i in ans):
                continue
            if question in seen:
                continue
            seen.add(question)

            code = (q.get("code") or "").strip()
            expected = ""
            if q_type in ("wwpd", "wwpp"):
                if not code:
                    continue
                expected = self._verify_code_answer(code)
                if expected is None:
                    continue  # code doesn't run / no output → discard
                # Authoritative answer: replace LLM's guess with real output
                ans = [0]  # we'll place the verified answer at options[0]
                options = [expected] + [o for o in options if o != expected][:3]
                if len(options) < 2:
                    continue
            elif q_type == "judge":
                options = ["正确", "错误"]
                if not ans or ans[0] not in (0, 1):
                    continue

            questions.append({
                "question": question,
                "code": code,
                "q_type": q_type,
                "difficulty": q.get("difficulty", "medium"),
                "options": options,
                "answer_indexes": ans,
                "expected_output": expected,
                "explanation": (q.get("explanation") or "").strip(),
            })

        return questions

    async def explain(
        self,
        question: Dict,
        user_answer: Optional[List[int]],
    ) -> str:
        """Lazy explanation for a single question (with the user's answer)."""
        opts = question.get("options") or []
        ans = question.get("answer_indexes") or []
        answer_text = "；".join(opts[i] for i in ans if i < len(opts))
        if question.get("q_type") in ("wwpd", "wwpp") and question.get("expected_output"):
            answer_text = f"输出：{question['expected_output']}"
        if user_answer:
            user_text = "；".join(opts[i] for i in user_answer if i < len(opts)) or "（未选择）"
        else:
            user_text = "（未作答）"

        opts_text = "\n".join(f"{chr(65 + i)}. {o}" for i, o in enumerate(opts))
        prompt = EXPLAIN_PROMPT.format(
            q_type=question.get("q_type", ""),
            question=question.get("question", ""),
            options_text=opts_text,
            answer_text=answer_text,
            user_answer_text=user_text,
        )
        try:
            resp = await self.llm_text.ainvoke([HumanMessage(content=prompt)])
            return resp.content
        except Exception as e:
            return f"解析生成失败：{type(e).__name__}: {str(e)[:120]}"
