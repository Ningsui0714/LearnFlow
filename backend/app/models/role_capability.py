from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.database import Base


class RoleCapabilityPackage(Base):
    """Learner-owned plugin root. Mutable pointers never contain role truth."""

    __tablename__ = "role_capability_packages"
    __table_args__ = (
        UniqueConstraint("learner_id", "project_id", name="uq_role_capability_project"),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    role_title = Column(String(255), nullable=False)
    status = Column(String(30), nullable=False, default="draft", index=True)
    current_snapshot_id = Column(Integer, ForeignKey("role_capability_snapshots.id"), nullable=True)
    policy_version = Column(String(80), nullable=False, default="learnflow.role-capability.v1")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    snapshots = relationship(
        "RoleCapabilitySnapshot",
        back_populates="package",
        foreign_keys="RoleCapabilitySnapshot.package_id",
        cascade="all, delete-orphan",
        order_by="RoleCapabilitySnapshot.version",
    )
    runs = relationship("RoleCapabilityRun", back_populates="package", cascade="all, delete-orphan")


class RoleCapabilitySnapshot(Base):
    """Immutable, validated role graph snapshot used by tools and dialogue."""

    __tablename__ = "role_capability_snapshots"
    __table_args__ = (
        UniqueConstraint("package_id", "version", name="uq_role_capability_snapshot_version"),
        UniqueConstraint("package_id", "root_hash", name="uq_role_capability_snapshot_hash"),
    )

    id = Column(Integer, primary_key=True)
    package_id = Column(Integer, ForeignKey("role_capability_packages.id"), nullable=False, index=True)
    parent_snapshot_id = Column(Integer, ForeignKey("role_capability_snapshots.id"), nullable=True, index=True)
    version = Column(Integer, nullable=False)
    snapshot_key = Column(String(180), nullable=False, unique=True, index=True)
    root_hash = Column(String(64), nullable=False, index=True)
    role_title = Column(String(255), nullable=False)
    status = Column(String(30), nullable=False, default="ready", index=True)
    graph = Column(JSON, default=dict, nullable=False)
    source_refs = Column(JSON, default=list, nullable=False)
    validation = Column(JSON, default=dict, nullable=False)
    provenance = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    package = relationship(
        "RoleCapabilityPackage",
        back_populates="snapshots",
        foreign_keys=[package_id],
    )


class RoleCapabilityRun(Base):
    """Idempotent workflow record for generation and bounded iteration."""

    __tablename__ = "role_capability_runs"
    __table_args__ = (
        UniqueConstraint("learner_id", "idempotency_key", name="uq_role_capability_run_key"),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    package_id = Column(Integer, ForeignKey("role_capability_packages.id"), nullable=True, index=True)
    kind = Column(String(30), nullable=False, index=True)  # generate | iterate
    status = Column(String(30), nullable=False, default="running", index=True)
    idempotency_key = Column(String(160), nullable=False, index=True)
    request = Column(JSON, default=dict, nullable=False)
    contract = Column(JSON, default=dict, nullable=False)
    inspection = Column(JSON, default=dict, nullable=False)
    diff = Column(JSON, default=dict, nullable=False)
    result_snapshot_id = Column(Integer, ForeignKey("role_capability_snapshots.id"), nullable=True)
    summary = Column(Text, default="")
    error = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    package = relationship("RoleCapabilityPackage", back_populates="runs")
