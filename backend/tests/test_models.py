"""Tests para los modelos de dominio: Job, AgentEvent y RepoContext."""

from app.models.job import Job, JobStatus, AgentEvent
from app.models.repo_context import RepoContext


def test_job_initial_status():
    """Un job recién creado debe estar en estado PENDING sin documento."""
    job = Job(job_id="test-123", repo_url="https://github.com/a/b")
    assert job.status == JobStatus.PENDING
    assert job.document is None


def test_agent_event_serialization():
    """AgentEvent debe serializar correctamente agent y section."""
    event = AgentEvent(agent="sherlock", section="## Stack\n\nPython 3.12")
    data = event.model_dump()
    assert data["agent"] == "sherlock"
    assert "Stack" in data["section"]


def test_repo_context_file_count():
    """RepoContext debe almacenar todos los archivos pasados."""
    ctx = RepoContext(
        tree="├── main.py\n└── README.md",
        files={"main.py": "print('hello')", "README.md": "# Test"},
    )
    assert len(ctx.files) == 2


def test_repo_context_as_text_contains_tree():
    """as_text debe incluir el árbol de directorios."""
    ctx = RepoContext(tree="└── main.py", files={"main.py": "x = 1"})
    text = ctx.as_text
    assert "main.py" in text
    assert "x = 1" in text
