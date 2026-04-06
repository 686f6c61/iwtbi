"""Tests para el servicio de validación y clonado de repositorios."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services.git_cloner import validate_github_url, GitCloner
from app.services.git_cloner import _is_retryable_clone_error


def test_valid_github_urls():
    """URLs de repos GitHub válidos deben pasar la validación."""
    assert validate_github_url("https://github.com/user/repo") is True
    assert validate_github_url("https://github.com/org/project-name") is True
    assert validate_github_url("https://github.com/kelseyhightower/nocode") is True


def test_invalid_urls():
    """URLs no GitHub o malformadas deben rechazarse."""
    assert validate_github_url("https://gitlab.com/user/repo") is False
    assert validate_github_url("https://github.com/user") is False
    assert validate_github_url("not-a-url") is False
    assert validate_github_url("https://github.com/") is False


def test_repo_path_generation():
    """El path de clonado debe incluir el job_id e 'iwtbi'."""
    cloner = GitCloner()
    path = cloner.get_clone_path("test-job-id")
    assert "test-job-id" in str(path)
    assert "iwtbi" in str(path)


def test_cleanup_nonexistent_path_is_safe():
    """cleanup sobre un path inexistente no debe lanzar excepción."""
    cloner = GitCloner()
    cloner.cleanup("id-que-nunca-existio")  # no debe explotar


def test_retryable_clone_error_detection():
    """Los errores transitorios de red/TLS deben marcarse como reintentables."""
    assert _is_retryable_clone_error("Recv failure: Connection reset by peer")
    assert _is_retryable_clone_error("GnuTLS recv error (-110)")
    assert not _is_retryable_clone_error("Repository not found")


class _FakeProc:
    def __init__(self, *, returncode: int, stderr: bytes):
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self):
        return b"", self._stderr

    async def wait(self):
        return None

    def kill(self):
        return None


@pytest.mark.asyncio
async def test_clone_retries_on_transient_git_network_error(monkeypatch, tmp_path):
    """Un fallo de red transitorio en git clone debe reintentarse."""
    cloner = GitCloner()
    monkeypatch.setattr(
        "app.services.git_cloner.CLONE_BASE",
        tmp_path,
    )
    monkeypatch.setattr(cloner, "_check_repo_size", AsyncMock())
    monkeypatch.setattr(cloner, "_get_head_sha", AsyncMock(return_value="abc123"))
    monkeypatch.setattr("app.services.git_cloner.asyncio.sleep", AsyncMock())

    procs = [
        _FakeProc(
            returncode=128,
            stderr=(
                b"fatal: unable to access 'https://github.com/org/repo/': "
                b"Recv failure: Connection reset by peer"
            ),
        ),
        _FakeProc(returncode=0, stderr=b""),
    ]

    async def fake_create_subprocess_exec(*args, **kwargs):
        return procs.pop(0)

    monkeypatch.setattr(
        "app.services.git_cloner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    dest, git_sha = await cloner.clone("https://github.com/org/repo", "job-1")

    assert dest == Path(tmp_path) / "repo-job-1"
    assert git_sha == "abc123"
