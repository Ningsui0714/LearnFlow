from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, JSON, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.db.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    user_level = Column(String(50), default="beginner")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sources = relationship("Source", back_populates="project", cascade="all, delete-orphan")
    roadmap = relationship("Roadmap", back_populates="project", uselist=False, cascade="all, delete-orphan")


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    type = Column(String(50), nullable=False)  # github, url, file
    url = Column(Text, default="")
    status = Column(String(50), default="pending")  # pending, processing, processed, failed
    error = Column(Text, default="")
    meta_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="sources")
    chunks = relationship("Chunk", back_populates="source", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    tokens = Column(Integer, default=0)
    meta_data = Column(JSON, default=dict)

    source = relationship("Source", back_populates="chunks")
    checkpoints = relationship("CheckpointChunk", back_populates="chunk", cascade="all, delete-orphan")


class Roadmap(Base):
    __tablename__ = "roadmaps"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True)
    raw_json = Column(JSON, default=dict)
    conversation_history = Column(JSON, default=list)  # Persistent chat history
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="roadmap")
    checkpoints = relationship("Checkpoint", back_populates="roadmap", cascade="all, delete-orphan")


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id = Column(Integer, primary_key=True, index=True)
    roadmap_id = Column(Integer, ForeignKey("roadmaps.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    order = Column(Integer, nullable=False)
    prerequisites = Column(JSON, default=list)  # list of checkpoint ids
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    roadmap = relationship("Roadmap", back_populates="checkpoints")
    chunk_assignments = relationship("CheckpointChunk", back_populates="checkpoint", cascade="all, delete-orphan")
    lecture = relationship("Lecture", back_populates="checkpoint", uselist=False, cascade="all, delete-orphan")
    exercises = relationship("Exercise", back_populates="checkpoint", cascade="all, delete-orphan")


class CheckpointChunk(Base):
    __tablename__ = "checkpoint_chunks"

    id = Column(Integer, primary_key=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False)
    chunk_id = Column(Integer, ForeignKey("chunks.id"), nullable=False)

    checkpoint = relationship("Checkpoint", back_populates="chunk_assignments")
    chunk = relationship("Chunk", back_populates="checkpoints")


class Lecture(Base):
    __tablename__ = "lectures"

    id = Column(Integer, primary_key=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False, unique=True)
    sections = Column(JSON, default=list)  # list of {title, content, keywords, questions}
    status = Column(String(50), default="draft")  # draft, published
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    checkpoint = relationship("Checkpoint", back_populates="lecture")


class Exercise(Base):
    __tablename__ = "exercises"

    id = Column(Integer, primary_key=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    starter_code = Column(Text, default="")
    solution = Column(Text, default="")
    test_cases = Column(JSON, default=list)
    hints = Column(JSON, default=list)
    order = Column(Integer, default=0)

    checkpoint = relationship("Checkpoint", back_populates="exercises")
