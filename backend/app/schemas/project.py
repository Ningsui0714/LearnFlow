from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ── Project ──

class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    user_level: str = "beginner"


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    user_level: str
    source_count: int = 0
    checkpoint_count: int = 0
    completed_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectDetail(BaseModel):
    id: int
    name: str
    description: str
    user_level: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Source ──

class SourceCreate(BaseModel):
    type: str  # github, url, file
    url: str = ""


class SourceOut(BaseModel):
    id: int
    project_id: int
    type: str
    url: str
    status: str
    error: str
    chunk_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


# ── Chunk ──

class ChunkOut(BaseModel):
    id: int
    source_id: int
    index: int
    content: str
    tokens: int
    metadata: dict

    class Config:
        from_attributes = True


# ── Roadmap / Checkpoint ──

class RoadmapNode(BaseModel):
    id: int
    title: str
    description: str
    order: int
    prerequisites: List[int]
    completed: bool
    chunk_ids: List[int]
    brief: dict = {}


class RoadmapOut(BaseModel):
    id: int
    project_id: int
    checkpoints: List[RoadmapNode]


# ── Lecture ──

class LectureSection(BaseModel):
    title: str
    content: str
    keywords: List[str] = []
    questions: List[str] = []


class LectureOut(BaseModel):
    id: int
    checkpoint_id: int
    sections: List[LectureSection]
    status: str


# ── Exercise ──

class ExerciseOut(BaseModel):
    id: int
    checkpoint_id: int
    title: str
    description: str
    starter_code: str
    test_cases: List[dict]
    hints: List[str]
    order: int

    class Config:
        from_attributes = True


class CodeRunRequest(BaseModel):
    code: str
    selection: str = ""


class CodeRunResult(BaseModel):
    stdout: str
    stderr: str
    passed: bool = False


class CodeReviewRequest(BaseModel):
    code: str
    selection: str = ""


class CodeAskRequest(BaseModel):
    code: str
    selection: str
    question: str


# ── Agent Chat ──

class AgentMessage(BaseModel):
    role: str  # user, assistant
    content: str


class AgentChatRequest(BaseModel):
    message: str
    history: List[AgentMessage] = []


class AgentChatResponse(BaseModel):
    message: str
    updated_roadmap: Optional[dict] = None


class LectureAskRequest(BaseModel):
    selection: str
    question: str
    history: List[AgentMessage] = []
