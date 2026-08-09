from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


# Lightweight migrations: columns added to existing models after the table
# was created. create_all() does not alter existing tables, so we add them
# explicitly (SQLite ADD COLUMN).
EXTRA_COLUMNS = {
    "checkpoints": [
        ("brief", "TEXT"),        # CheckpointBrief handoff contract (T2)
        ("archived", "BOOLEAN"), # T10: removed-but-kept checkpoints
        ("progress", "TEXT"),    # T10: learning progress stats
    ],
    "sources": [
        ("role", "TEXT"),        # T10: main | auxiliary
    ],
    "lectures": [
        ("plan", "TEXT"),        # T10: persisted section plan (resume stability)
        ("concept_graph", "TEXT"),  # concept map {nodes, edges}
    ],
    "exercises": [
        ("files", "TEXT"),        # project-mode: [{name, content, read_only}]
        ("entrypoint", "TEXT"),   # main file to run
        ("requirements", "TEXT"), # ["torch", "scikit-learn"]
        ("judge_mode", "TEXT"),  # test_cases | stdout_check
        ("judge_config", "TEXT"),# {pattern, min_accuracy} for stdout_check
    ],
    "process_animations": [
        ("kind", "TEXT"),         # animation | static（表已存在时补列）
    ],
}


async def _ensure_columns():
    async with engine.begin() as conn:
        for table, cols in EXTRA_COLUMNS.items():
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result.fetchall()}
            for col, coltype in cols:
                if col not in existing:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
                    print(f"[migrate] added column {table}.{col} ({coltype})")


async def init_db():
    async with engine.begin() as conn:
        from app.models import project  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_columns()
