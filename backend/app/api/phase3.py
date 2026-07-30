"""
Phase 3 API routes:
- Exercise CRUD
- Code execution
- Code review agent
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.models.project import Checkpoint, Exercise
from app.schemas.project import ExerciseOut, CodeRunRequest, CodeRunResult
from app.services.code_executor import execute_code
from app.services.code_agent import CodeAgent
from langchain_core.messages import HumanMessage

router = APIRouter()


# ── Exercise CRUD ──

@router.get("/checkpoints/{checkpoint_id}/exercises")
async def list_exercises(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    """List exercises for a checkpoint."""
    result = await db.execute(
        select(Exercise)
        .where(Exercise.checkpoint_id == checkpoint_id)
        .order_by(Exercise.order)
    )
    exercises = result.scalars().all()
    return [
        ExerciseOut(
            id=e.id, checkpoint_id=e.checkpoint_id, title=e.title,
            description=e.description, starter_code=e.starter_code,
            test_cases=e.test_cases or [], hints=e.hints or [], order=e.order,
        )
        for e in exercises
    ]


@router.post("/checkpoints/{checkpoint_id}/exercises")
async def create_exercise(
    checkpoint_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Create a new exercise."""
    cp = await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))
    if not cp.scalar_one_or_none():
        raise HTTPException(404, "Checkpoint not found")

    exercise = Exercise(
        checkpoint_id=checkpoint_id,
        title=data.get("title", ""),
        description=data.get("description", ""),
        starter_code=data.get("starter_code", ""),
        solution=data.get("solution", ""),
        test_cases=data.get("test_cases", []),
        hints=data.get("hints", []),
        order=data.get("order", 0),
    )
    db.add(exercise)
    await db.commit()
    await db.refresh(exercise)
    return ExerciseOut(
        id=exercise.id, checkpoint_id=exercise.checkpoint_id,
        title=exercise.title, description=exercise.description,
        starter_code=exercise.starter_code,
        test_cases=exercise.test_cases or [],
        hints=exercise.hints or [], order=exercise.order,
    )


@router.get("/exercises/{exercise_id}")
async def get_exercise(
    exercise_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get exercise details."""
    result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    e = result.scalar_one_or_none()
    if not e:
        raise HTTPException(404, "Exercise not found")
    return ExerciseOut(
        id=e.id, checkpoint_id=e.checkpoint_id, title=e.title,
        description=e.description, starter_code=e.starter_code,
        test_cases=e.test_cases or [], hints=e.hints or [], order=e.order,
    )


# ── Code Execution ──

@router.post("/exercises/{exercise_id}/run", response_model=CodeRunResult)
async def run_code(
    exercise_id: int,
    req: CodeRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Execute code for an exercise."""
    # Verify exercise exists
    result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    if not result.scalar_one_or_none():
        raise HTTPException(404, "Exercise not found")

    # Run the code
    return execute_code(req.code)


@router.post("/exercises/run", response_model=CodeRunResult)
async def run_standalone_code(
    req: CodeRunRequest,
):
    """Execute arbitrary Python code (no exercise context)."""
    return execute_code(req.code)


# ── Code Review Agent ──

@router.post("/exercises/{exercise_id}/review")
async def review_code(
    exercise_id: int,
    req: CodeRunRequest,  # code + optional selection
    db: AsyncSession = Depends(get_db),
):
    """Review code with AI agent."""
    result = await db.execute(select(Exercise).where(Exercise.id == exercise_id))
    exercise = result.scalar_one_or_none()
    if not exercise:
        raise HTTPException(404, "Exercise not found")

    context = f"{exercise.title}: {exercise.description[:200]}"
    agent = CodeAgent()

    if req.selection:
        answer = await agent.explain(req.selection, req.code, context)
    else:
        answer = await agent.review(req.code, context)

    return {"answer": answer}


@router.post("/code/ask")
async def ask_code_question(
    data: dict,
):
    """Ask a question about code (without exercise context)."""
    agent = CodeAgent()
    selection = data.get("selection", "")
    code = data.get("code", "")
    question = data.get("question", "")
    context = data.get("context", "")

    if question:
        # Specific question about the code
        full_prompt = f"""## 代码
```python
{code}
```

## 选中的代码段
```python
{selection}
```

## 学生的问题
{question}

## 背景
{context}

请回答学生的问题，用 KaTeX 写公式，控制在 400 字以内。"""
        answer = await agent.llm.ainvoke(
            [HumanMessage(content=full_prompt)]
        )
        return {"answer": answer.content}
    elif selection:
        # Explain selected code
        answer = await agent.explain(selection, code, context)
        return {"answer": answer}
    else:
        # Review full code
        answer = await agent.review(code, context)
        return {"answer": answer}


# ── Embedding Indexing ──

@router.post("/projects/{project_id}/embeddings/index")
async def index_embeddings(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Batch index all chunks for a project via DeepSeek API."""
    from app.models.project import Chunk, Source
    from app.services.embedding import embed_batch, cache_embedding

    result = await db.execute(
        select(Chunk).join(Source).where(Source.project_id == project_id).order_by(Chunk.id)
    )
    chunks = result.scalars().all()
    if not chunks:
        raise HTTPException(404, "No chunks found")

    total = len(chunks)
    batch_size = 20
    indexed = 0
    errors = 0

    for i in range(0, total, batch_size):
        batch = chunks[i:i + batch_size]
        try:
            texts = [c.content[:2000] for c in batch]
            embeddings = embed_batch(texts)
            for j, c in enumerate(batch):
                cache_embedding(c.id, embeddings[j])
            indexed += len(batch)
        except Exception as e:
            errors += 1
            print(f"[Embedding] Batch {i//batch_size} failed: {e}")
            continue

    return {"status": "ok", "indexed": indexed, "errors": errors, "total": total}


# ── Generate Exercises ──

@router.post("/checkpoints/{checkpoint_id}/exercises/generate")
async def generate_exercises(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Generate coding exercises via LLM based on checkpoint content."""
    from app.models.project import Checkpoint, Chunk, CheckpointChunk, Lecture
    from app.services.lecture_agent import LectureAgent

    # Get checkpoint
    cp = (await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))).scalar_one_or_none()
    if not cp:
        raise HTTPException(404, "Checkpoint not found")

    # Get lecture content as context
    lecture = (await db.execute(select(Lecture).where(Lecture.checkpoint_id == checkpoint_id))).scalar_one_or_none()
    lecture_text = ""
    if lecture and lecture.sections:
        for s in lecture.sections[:2]:
            lecture_text += s.get("content", "")[:1000] + "\n"

    # Get chunks
    chunks_raw = (await db.execute(
        select(Chunk).join(CheckpointChunk)
        .where(CheckpointChunk.checkpoint_id == checkpoint_id)
        .limit(5)
    )).scalars().all()
    chunk_text = "\n".join([c.content[:500] for c in chunks_raw])

    context = f"## 关卡\n{cp.title}: {cp.description}\n\n## 讲义内容\n{lecture_text}\n\n## 参考资料\n{chunk_text}"

    prompt = f"""根据以下学习内容，生成 2 个 Python 编程练习题。

{context}

## 输出格式 (JSON)
```json
[
  {{
    "title": "题目名称",
    "description": "题目描述，含公式",
    "starter_code": "带有 TODO 的 Python 代码框架",
    "solution": "完整参考解答",
    "hints": ["提示1", "提示2"]
  }}
]
```

要求：
- 题目与学习内容强相关
- starter_code 包含 TODO 标记
- 用 KaTeX 公式
- 难度递进"""

    from langchain_openai import ChatOpenAI
    from app.core.config import settings
    llm = ChatOpenAI(model=settings.llm_model, api_key=settings.llm_api_key,
                     base_url=settings.llm_base_url, temperature=0.7, timeout=30)

    resp = await llm.ainvoke([__import__("langchain_core.messages", fromlist=["HumanMessage"]).HumanMessage(content=prompt)])
    content = resp.content

    # Parse JSON from response
    import re, json as j
    m = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
    if not m:
        m = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
    if not m:
        return {"error": "LLM did not return valid JSON", "raw": content[:500]}

    try:
        exercises_data = j.loads(m.group(1))
    except j.JSONDecodeError as e:
        return {"error": f"JSON parse failed: {e}", "raw": content[:500]}

    # Save to DB
    saved = []
    from app.models.project import Exercise
    for i, ex in enumerate(exercises_data):
        exercise = Exercise(
            checkpoint_id=checkpoint_id,
            title=ex.get("title", f"练习 {i+1}"),
            description=ex.get("description", ""),
            starter_code=ex.get("starter_code", ""),
            solution=ex.get("solution", ""),
            hints=ex.get("hints", []),
            order=i + 1,
        )
        db.add(exercise)
        await db.flush()
        saved.append({"id": exercise.id, "title": exercise.title})

    await db.commit()
    return {"status": "ok", "exercises": saved}
