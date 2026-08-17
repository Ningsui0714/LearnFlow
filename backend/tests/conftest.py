import os
import tempfile
from pathlib import Path


_test_dir = Path(tempfile.mkdtemp(prefix="learnflow-tutor-tests-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_dir / 'test.db'}"
os.environ["LLM_API_KEY"] = ""
# Background consolidation is tested explicitly. Keeping it stopped in the
# shared TestClient fixture prevents races with assertions on queued runs.
os.environ["MEMORY_AUTO_SYNTHESIS_ENABLED"] = "false"
