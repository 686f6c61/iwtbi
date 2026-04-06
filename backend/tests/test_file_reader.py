"""Tests para el lector de archivos del repositorio."""

from pathlib import Path
import pytest
from app.services.file_reader import FileReader, EXCLUDED_DIRS


def create_test_repo(tmp_path: Path) -> Path:
    """Crea una estructura de repositorio mínima para los tests."""
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "README.md").write_text("# Test")

    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "package.json").write_text("{}")

    git = tmp_path / ".git"
    git.mkdir()
    (git / "config").write_text("[core]")

    return tmp_path


def test_excludes_node_modules_and_git(tmp_path):
    """node_modules y .git no deben aparecer en el árbol ni en los archivos."""
    create_test_repo(tmp_path)
    reader = FileReader()
    ctx = reader.read(tmp_path)
    assert "node_modules" not in ctx.tree
    assert ".git" not in ctx.tree
    assert "node_modules/package.json" not in ctx.files


def test_reads_source_files(tmp_path):
    """Los archivos de código fuente deben estar en ctx.files."""
    create_test_repo(tmp_path)
    reader = FileReader()
    ctx = reader.read(tmp_path)
    assert "main.py" in ctx.files
    assert "README.md" in ctx.files


def test_tree_contains_readable_files(tmp_path):
    """El árbol ASCII debe incluir los archivos de código fuente."""
    create_test_repo(tmp_path)
    reader = FileReader()
    ctx = reader.read(tmp_path)
    assert "main.py" in ctx.tree
    assert "README.md" in ctx.tree


def test_binary_files_excluded(tmp_path):
    """Archivos con bytes nulos deben excluirse del contenido."""
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    reader = FileReader()
    ctx = reader.read(tmp_path)
    assert "image.png" not in ctx.files


def test_excluded_dirs_constant():
    """EXCLUDED_DIRS debe incluir los directorios estándar sin valor analítico."""
    assert "node_modules" in EXCLUDED_DIRS
    assert ".git" in EXCLUDED_DIRS
    assert "__pycache__" in EXCLUDED_DIRS
