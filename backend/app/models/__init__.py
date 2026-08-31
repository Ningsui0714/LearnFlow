from app.models.project import (
    Project, Source, SourceVersion, Chunk, DomainKnowledgePacket,
    Roadmap, Checkpoint, Lecture, Exercise,
    LectureVersion, LectureNote, ArtifactAnnotation, ExerciseDraft,
    ProcessAnimation, ProjectWorkspace, WorkspaceOperation,
    LocalAgentProfile, LocalAgentRun, LocalAgentRunEvent,
)
from app.models import project, learning  # noqa: F401
from app.models.role_capability import (  # noqa: F401
    RoleCapabilityPackage, RoleCapabilityRun, RoleCapabilitySnapshot,
)
