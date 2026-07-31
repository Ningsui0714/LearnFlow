"""
Phase 3 API routes:
- Exercise CRUD
- Code execution
- Code review agent
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.core.config import settings
from app.models.project import Checkpoint, Exercise, ConceptQuestion, Task, Roadmap
from app.schemas.project import ExerciseOut, CodeRunRequest, CodeRunResult
from app.services.code_executor import execute_code
from app.services.code_agent import CodeAgent
from app.services.concept_agent import ConceptAgent
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


# ── Concept Questions (T7) ──

@router.get("/checkpoints/{checkpoint_id}/concepts")
async def list_concepts(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(ConceptQuestion)
        .where(ConceptQuestion.checkpoint_id == checkpoint_id)
        .order_by(ConceptQuestion.order)
    )).scalars().all()
    return [{
        "id": q.id,
        "checkpoint_id": q.checkpoint_id,
        "question": q.question,
        "options": q.options or [],
        "q_type": q.q_type,
        "difficulty": q.difficulty,
        "code": q.code,
        "order": q.order,
        # answers hidden from list; only used by explain/submit endpoints
    } for q in rows]


@router.post("/checkpoints/{checkpoint_id}/concepts/generate")
async def generate_concepts(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Create a background concept-question generation task (T7)."""
    if not settings.llm_api_key or settings.llm_api_key == "***":
        raise HTTPException(400, "请先配置 API Key: 在设置页填写 LLM_API_KEY")
    cp = (await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))).scalar_one_or_none()
    if not cp:
        raise HTTPException(404, "Checkpoint not found")
    roadmap = (await db.execute(
        select(Roadmap).where(Roadmap.id == cp.roadmap_id)
    )).scalar_one_or_none()

    from app.services.task_manager import find_running_task, manager
    running = await find_running_task(checkpoint_id, "concept_generate")
    if running:
        return {"task_id": running.id, "status": running.status, "already_running": True}

    task = Task(
        project_id=roadmap.project_id if roadmap else None,
        checkpoint_id=checkpoint_id,
        type="concept_generate",
        status="queued",
        payload={"checkpoint_id": checkpoint_id},
        progress={"current": 0, "total": 0, "message": "排队中..."},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    from app.services.task_runners import run_concept_generation
    manager.submit(task.id, run_concept_generation(task.id))
    return {"task_id": task.id, "status": task.status, "already_running": False}


@router.get("/checkpoints/{checkpoint_id}/concepts/task")
async def get_concept_task(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Task)
        .where(Task.checkpoint_id == checkpoint_id, Task.type == "concept_generate")
        .order_by(Task.id.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"task_id": None}
    from app.api.tasks import _snapshot
    return _snapshot(task)


@router.post("/checkpoints/{checkpoint_id}/concepts/{question_id}/explain")
async def explain_concept(
    checkpoint_id: int,
    question_id: int,
    data: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
):
    """Lazy AI explanation for one question, with the user's answer."""
    q = (await db.execute(select(ConceptQuestion).where(
        ConceptQuestion.id == question_id,
        ConceptQuestion.checkpoint_id == checkpoint_id,
    ))).scalar_one_or_none()
    if not q:
        raise HTTPException(404, "Question not found")
    agent = ConceptAgent()
    answer = await agent.explain(
        {
            "question": q.question,
            "options": q.options or [],
            "answer_indexes": q.answer_indexes or [],
            "q_type": q.q_type,
            "expected_output": q.expected_output,
            "explanation": q.explanation,
        },
        user_answer=[int(i) for i in (data or {}).get("user_answer_indexes", [])],
    )
    return {"explanation": answer, "base_explanation": q.explanation}


@router.post("/checkpoints/{checkpoint_id}/concepts/{question_id}/submit")
async def submit_concept(
    checkpoint_id: int,
    question_id: int,
    data: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
):
    """Instant grading: return correct/wrong + right answers (no LLM)."""
    q = (await db.execute(select(ConceptQuestion).where(
        ConceptQuestion.id == question_id,
        ConceptQuestion.checkpoint_id == checkpoint_id,
    ))).scalar_one_or_none()
    if not q:
        raise HTTPException(404, "Question not found")
    correct = sorted(q.answer_indexes or [])
    user = sorted(int(i) for i in (data or {}).get("answer_indexes", []))
    is_correct = user == correct and len(user) > 0
    return {
        "correct": is_correct,
        "answer_indexes": correct,
        "user_answer_indexes": user,
        "explanation": q.explanation or "",
    }


# ── Generate Exercises ──

@router.post("/checkpoints/{checkpoint_id}/exercises/generate")
async def generate_exercises(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    """T8: background exercise generation — blueprint → per-exercise →
    executable verification (solution × test_cases must all pass)."""
    if not settings.llm_api_key or settings.llm_api_key == "***":
        raise HTTPException(400, "请先配置 API Key: 在设置页填写 LLM_API_KEY")
    cp = (await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))).scalar_one_or_none()
    if not cp:
        raise HTTPException(404, "Checkpoint not found")
    roadmap = (await db.execute(
        select(Roadmap).where(Roadmap.id == cp.roadmap_id)
    )).scalar_one_or_none()

    from app.services.task_manager import find_running_task, manager
    running = await find_running_task(checkpoint_id, "exercise_generate")
    if running:
        return {"task_id": running.id, "status": running.status, "already_running": True}

    task = Task(
        project_id=roadmap.project_id if roadmap else None,
        checkpoint_id=checkpoint_id,
        type="exercise_generate",
        status="queued",
        payload={"checkpoint_id": checkpoint_id},
        progress={"current": 0, "total": 0, "message": "排队中..."},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    from app.services.task_runners import run_exercise_generation
    manager.submit(task.id, run_exercise_generation(task.id))
    return {"task_id": task.id, "status": task.status, "already_running": False}


@router.get("/checkpoints/{checkpoint_id}/exercises/task")
async def get_exercise_task(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Task)
        .where(Task.checkpoint_id == checkpoint_id, Task.type == "exercise_generate")
        .order_by(Task.id.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"task_id": None}
    from app.api.tasks import _snapshot
    return _snapshot(task)


@router.post("/exercises/{exercise_id}/submit")
async def submit_exercise(
    exercise_id: int,
    req: CodeRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """T8: judge user code against the exercise's test cases.
    Returns per-case results (passed/expected/actual)."""
    exercise = (await db.execute(
        select(Exercise).where(Exercise.id == exercise_id)
    )).scalar_one_or_none()
    if not exercise:
        raise HTTPException(404, "Exercise not found")
    test_cases = exercise.test_cases or []
    if not test_cases:
        return {"passed": 0, "total": 0, "results": [], "error": "该题没有测试用例"}

    from app.services.exercise_agent import ExerciseAgent
    results = ExerciseAgent.verify_exercise(req.code, test_cases)
    passed = sum(1 for r in results if r["passed"])
    return {"passed": passed, "total": len(results), "results": results}
