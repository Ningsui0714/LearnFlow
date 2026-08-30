"""Persistent contracts for the LearnFlow plugin host.

The rows in this module deliberately separate executable package metadata from
learner-owned plugin state and immutable plugin-produced truth.  Plugin code is
never given an ORM object or a database connection; these models are owned by
the deterministic host.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


class PluginPublisher(Base):
    """One operator-managed signing identity."""

    __tablename__ = "plugin_publishers"

    id = Column(Integer, primary_key=True)
    publisher_key = Column(String(160), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=False, default="")
    key_id = Column(String(160), nullable=False, unique=True, index=True)
    public_key = Column(Text, nullable=False)
    trust_status = Column(String(30), nullable=False, default="untrusted", index=True)
    revoked_reason = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    revoked_at = Column(DateTime, nullable=True)

    releases = relationship("PluginRelease", back_populates="publisher")


class PluginRelease(Base):
    """Immutable imported ``.lfplugin`` release plus mutable revocation state."""

    __tablename__ = "plugin_releases"
    __table_args__ = (
        UniqueConstraint("plugin_id", "version", name="uq_plugin_release_version"),
        UniqueConstraint("plugin_id", "root_hash", name="uq_plugin_release_root_hash"),
    )

    id = Column(Integer, primary_key=True)
    publisher_id = Column(Integer, ForeignKey("plugin_publishers.id"), nullable=True, index=True)
    plugin_id = Column(String(160), nullable=False, index=True)
    version = Column(String(64), nullable=False)
    package_protocol = Column(
        String(80), nullable=False, default="learnflow.plugin-package.v1"
    )
    manifest = Column(JSON, default=dict, nullable=False)
    signature = Column(JSON, default=dict, nullable=False)
    root_hash = Column(String(64), nullable=False, index=True)
    package_artifact_uri = Column(Text, nullable=False)
    runner_artifacts = Column(JSON, default=dict, nullable=False)
    trust_state = Column(String(40), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="active", index=True)
    imported_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    deprecated_at = Column(DateTime, nullable=True)

    publisher = relationship("PluginPublisher", back_populates="releases")
    instances = relationship("PluginInstance", back_populates="release")


class PluginInstance(Base):
    """Project-scoped enablement, configuration, grants and release pin."""

    __tablename__ = "plugin_instances"
    __table_args__ = (
        UniqueConstraint(
            "learner_id", "project_id", "plugin_id", name="uq_plugin_instance_project"
        ),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    plugin_id = Column(String(160), nullable=False, index=True)
    release_id = Column(Integer, ForeignKey("plugin_releases.id"), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="enabled", index=True)
    configuration = Column(JSON, default=dict, nullable=False)
    granted_host_ports = Column(JSON, default=list, nullable=False)
    current_snapshot_id = Column(Integer, ForeignKey("plugin_snapshots.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    disabled_at = Column(DateTime, nullable=True)

    release = relationship("PluginRelease", back_populates="instances")
    snapshots = relationship(
        "PluginSnapshot",
        back_populates="instance",
        foreign_keys="PluginSnapshot.instance_id",
        cascade="all, delete-orphan",
        order_by="PluginSnapshot.version",
    )
    runs = relationship("PluginRun", back_populates="instance", cascade="all, delete-orphan")


class PluginSnapshot(Base):
    """Immutable, content-addressed plugin domain snapshot."""

    __tablename__ = "plugin_snapshots"
    __table_args__ = (
        UniqueConstraint("instance_id", "version", name="uq_plugin_snapshot_version"),
        UniqueConstraint("instance_id", "root_hash", name="uq_plugin_snapshot_root_hash"),
    )

    id = Column(Integer, primary_key=True)
    instance_id = Column(Integer, ForeignKey("plugin_instances.id"), nullable=False, index=True)
    release_id = Column(Integer, ForeignKey("plugin_releases.id"), nullable=False, index=True)
    parent_snapshot_id = Column(Integer, ForeignKey("plugin_snapshots.id"), nullable=True, index=True)
    version = Column(Integer, nullable=False)
    schema_version = Column(String(100), nullable=False)
    root_hash = Column(String(64), nullable=False, index=True)
    components = Column(JSON, default=list, nullable=False)
    source_refs = Column(JSON, default=list, nullable=False)
    validation = Column(JSON, default=dict, nullable=False)
    provenance = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    instance = relationship(
        "PluginInstance",
        back_populates="snapshots",
        foreign_keys=[instance_id],
    )
    object_index = relationship(
        "PluginObjectIndex",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class PluginObjectIndex(Base):
    """Rebuildable locator metadata; plugin truth remains in the snapshot."""

    __tablename__ = "plugin_object_index"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "object_id", name="uq_plugin_object_snapshot"),
    )

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(Integer, ForeignKey("plugin_snapshots.id"), nullable=False, index=True)
    plugin_id = Column(String(160), nullable=False, index=True)
    object_type = Column(String(120), nullable=False, index=True)
    object_id = Column(String(255), nullable=False, index=True)
    label = Column(String(500), nullable=False, default="")
    schema_version = Column(String(100), nullable=False)
    component = Column(String(255), nullable=False)
    json_pointer = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    lifecycle = Column(String(30), nullable=False, default="active", index=True)
    references = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    snapshot = relationship("PluginSnapshot", back_populates="object_index")


class PluginRun(Base):
    """Idempotent workflow or tool invocation owned by one instance."""

    __tablename__ = "plugin_runs"
    __table_args__ = (
        UniqueConstraint("instance_id", "idempotency_key", name="uq_plugin_run_key"),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    instance_id = Column(Integer, ForeignKey("plugin_instances.id"), nullable=False, index=True)
    release_id = Column(Integer, ForeignKey("plugin_releases.id"), nullable=False, index=True)
    invocation_kind = Column(String(30), nullable=False, default="workflow", index=True)
    operation_id = Column(String(160), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="queued", index=True)
    idempotency_key = Column(String(180), nullable=False)
    request_hash = Column(String(64), nullable=False)
    request = Column(JSON, default=dict, nullable=False)
    contract = Column(JSON, default=dict, nullable=False)
    expected_snapshot_id = Column(Integer, ForeignKey("plugin_snapshots.id"), nullable=True)
    result_snapshot_id = Column(Integer, ForeignKey("plugin_snapshots.id"), nullable=True)
    result = Column(JSON, default=dict, nullable=False)
    execution_boundary = Column(JSON, default=dict, nullable=False)
    error = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    instance = relationship("PluginInstance", back_populates="runs")
    events = relationship(
        "PluginRunEvent",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="PluginRunEvent.sequence",
    )


class PluginRunEvent(Base):
    """Append-only, bounded audit trace for a plugin run."""

    __tablename__ = "plugin_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_plugin_run_event_sequence"),
    )

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("plugin_runs.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(100), nullable=False, index=True)
    direction = Column(String(30), nullable=False, default="host")
    payload = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    run = relationship("PluginRun", back_populates="events")
