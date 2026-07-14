"""Tests para el job store en memoria."""

import pytest
from app.store.job_store import JobStore
from app.models.job import JobStatus


@pytest.fixture
def store():
    return JobStore()


def test_create_and_get_job(store):
    """El job creado debe recuperarse por su ID."""
    job = store.create("https://github.com/a/b")
    retrieved = store.get(job.job_id)
    assert retrieved is not None
    assert retrieved.repo_url == "https://github.com/a/b"


def test_create_and_get_job_preserves_llm_profile_id(store):
    """El store en memoria conserva únicamente el identificador del perfil."""
    job = store.create("https://github.com/a/b", llm_profile_id="revision")

    assert store.get(job.job_id).llm_profile_id == "revision"


def test_get_nonexistent_returns_none(store):
    """Buscar un ID inexistente debe devolver None."""
    assert store.get("no-existe") is None


def test_update_status(store):
    """update_status debe cambiar el estado del job correctamente."""
    job = store.create("https://github.com/a/b")
    store.update_status(job.job_id, JobStatus.ANALYZING)
    assert store.get(job.job_id).status == JobStatus.ANALYZING


def test_set_document_marks_complete(store):
    """set_document debe guardar el documento y marcar el job como COMPLETE."""
    job = store.create("https://github.com/a/b")
    store.set_document(job.job_id, "# Documento final")
    updated = store.get(job.job_id)
    assert updated.document == "# Documento final"
    assert updated.status == JobStatus.COMPLETE


def test_set_error_marks_error(store):
    """set_error debe registrar el mensaje y marcar el job como ERROR."""
    job = store.create("https://github.com/a/b")
    store.set_error(job.job_id, "Repo no encontrado")
    updated = store.get(job.job_id)
    assert updated.error == "Repo no encontrado"
    assert updated.status == JobStatus.ERROR
