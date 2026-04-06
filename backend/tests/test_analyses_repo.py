"""Tests del repositorio de análisis con cliente Supabase mockeado."""

from unittest.mock import MagicMock
import pytest

from app.database.analyses_repo import AnalysesRepo


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def repo(mock_client):
    return AnalysesRepo(client=mock_client)


def test_find_by_url_returns_none_when_not_found(repo, mock_client):
    """find_by_url devuelve None si no hay entrada para esa URL."""
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    assert repo.find_by_url("https://github.com/user/repo") is None


def test_find_by_url_returns_dict_when_found(repo, mock_client):
    """find_by_url devuelve el dict del análisis si existe."""
    row = {"id": "abc", "repo_url": "https://github.com/user/repo",
           "git_sha": "abc123", "document": "# Doc"}
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [row]
    assert repo.find_by_url("https://github.com/user/repo") == row


def test_list_all_excludes_document_field(repo, mock_client):
    """list_all consulta sin el campo document."""
    mock_client.table.return_value.select.return_value.order.return_value.execute.return_value.data = []
    repo.list_all()
    call_args = mock_client.table.return_value.select.call_args[0][0]
    assert "document" not in call_args


def test_list_page_uses_exact_count_and_requested_range(repo, mock_client):
    """list_page debe pedir count exacto, ordenar y limitar por rango."""
    execute_mock = (
        mock_client.table.return_value.select.return_value.order.return_value.range.return_value.execute
    )
    execute_mock.return_value.data = [{"id": "1"}]
    execute_mock.return_value.count = 21

    result = repo.list_page(page=2, page_size=20, sort="name_asc")

    mock_client.table.return_value.select.assert_called_once_with(
        "id,repo_url,repo_full_name,git_sha,tags,created_at,updated_at",
        count="exact",
    )
    mock_client.table.return_value.select.return_value.order.assert_called_once_with(
        "repo_full_name", desc=False
    )
    mock_client.table.return_value.select.return_value.order.return_value.range.assert_called_once_with(
        20, 39
    )
    assert result == {
        "items": [{"id": "1"}],
        "total": 21,
        "page": 2,
        "page_size": 20,
        "total_pages": 2,
        "sort": "name_asc",
    }


def test_save_calls_upsert(repo, mock_client):
    """save hace upsert en la tabla analyses."""
    mock_client.table.return_value.upsert.return_value.execute.return_value.data = [{"id": "1"}]
    repo.save(
        repo_url="https://github.com/user/repo",
        repo_full_name="user/repo",
        document="# Doc",
        git_sha="abc123",
    )
    mock_client.table.return_value.upsert.assert_called_once()


def test_find_by_url_returns_none_on_exception(repo, mock_client):
    """find_by_url devuelve None si Supabase lanza una excepción."""
    mock_client.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception("timeout")
    assert repo.find_by_url("https://github.com/user/repo") is None
