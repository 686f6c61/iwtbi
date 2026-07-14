"""Tests del repositorio PostgreSQL de análisis."""

from contextlib import contextmanager
from unittest.mock import MagicMock

from app.database.analyses_repo import AnalysesRepo


def _patch_connect(monkeypatch, connection):
    @contextmanager
    def fake_connect():
        yield connection

    monkeypatch.setattr("app.database.analyses_repo.postgres_client.connect", fake_connect)


def test_find_by_url_returns_none_when_not_found(monkeypatch):
    """find_by_url devuelve None si no hay entrada para esa URL."""
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = None
    _patch_connect(monkeypatch, connection)

    assert AnalysesRepo().find_by_url("https://github.com/user/repo") is None


def test_find_by_url_returns_dict_when_found(monkeypatch):
    """find_by_url devuelve el dict del análisis si existe."""
    row = {
        "id": "abc",
        "repo_url": "https://github.com/user/repo",
        "git_sha": "abc123",
        "document": "# Doc",
    }
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = row
    _patch_connect(monkeypatch, connection)

    assert AnalysesRepo().find_by_url("https://github.com/user/repo") == row


def test_list_all_excludes_document_field(monkeypatch):
    """list_all consulta sin el campo document."""
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = []
    _patch_connect(monkeypatch, connection)

    AnalysesRepo().list_all()

    query = connection.execute.call_args.args[0].as_string()
    assert "document" not in query


def test_list_page_uses_count_order_and_limit(monkeypatch):
    """list_page cuenta, ordena y limita en PostgreSQL."""
    connection = MagicMock()
    count_result = MagicMock()
    count_result.fetchone.return_value = {"count": 21}
    rows_result = MagicMock()
    rows_result.fetchall.return_value = [{"id": "1"}]
    connection.execute.side_effect = [count_result, rows_result]
    _patch_connect(monkeypatch, connection)

    result = AnalysesRepo().list_page(page=2, page_size=20, sort="name_asc")

    list_query = connection.execute.call_args_list[1].args[0].as_string()
    list_params = connection.execute.call_args_list[1].args[1]
    assert 'ORDER BY "repo_full_name" ASC' in list_query
    assert "LIMIT %s OFFSET %s" in list_query
    assert list_params == (20, 20)
    assert result == {
        "items": [{"id": "1"}],
        "total": 21,
        "page": 2,
        "page_size": 20,
        "total_pages": 2,
        "sort": "name_asc",
    }


def test_list_page_filters_count_and_rows_with_query(monkeypatch):
    """El filtro global debe aplicarse al total y a las filas de forma parametrizada."""
    connection = MagicMock()
    count_result = MagicMock()
    count_result.fetchone.return_value = {"count": 1}
    rows_result = MagicMock()
    rows_result.fetchall.return_value = [{"id": "1"}]
    connection.execute.side_effect = [count_result, rows_result]
    _patch_connect(monkeypatch, connection)

    AnalysesRepo().list_page(query="Hello-World")

    count_query, count_params = connection.execute.call_args_list[0].args
    list_query, list_params = connection.execute.call_args_list[1].args
    count_query = count_query.as_string()
    list_query = list_query.as_string()
    assert "strpos(lower(repo_full_name), lower(%s)) > 0" in count_query
    assert "strpos(lower(repo_full_name), lower(%s)) > 0" in list_query
    assert count_params == ("Hello-World",)
    assert list_params == ("Hello-World", 21, 0)


def test_save_upserts_by_repo_url(monkeypatch):
    """save hace upsert por repo_url."""
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {"repo_full_name": "user/repo"}
    _patch_connect(monkeypatch, connection)

    result = AnalysesRepo().save(
        repo_url="https://github.com/user/repo",
        repo_full_name="user/repo",
        document="# Doc",
        git_sha="abc123",
        tags=["python"],
    )

    assert result == {"repo_full_name": "user/repo"}
    query = connection.execute.call_args.args[0]
    assert "ON CONFLICT (repo_url)" in query


def test_find_by_url_returns_none_on_exception(monkeypatch):
    """find_by_url devuelve None si PostgreSQL lanza una excepción."""
    connection = MagicMock()
    connection.execute.side_effect = Exception("timeout")
    _patch_connect(monkeypatch, connection)
    repo = AnalysesRepo()

    assert repo.find_by_url("https://github.com/user/repo") is None
    assert repo.last_error is not None


def test_find_by_url_clears_previous_error(monkeypatch):
    """Una consulta exitosa posterior debe limpiar el error anterior."""
    failing_connection = MagicMock()
    failing_connection.execute.side_effect = Exception("timeout")
    healthy_connection = MagicMock()
    healthy_connection.execute.return_value.fetchone.return_value = None
    connections = iter([failing_connection, healthy_connection])

    @contextmanager
    def fake_connect():
        yield next(connections)

    monkeypatch.setattr("app.database.analyses_repo.postgres_client.connect", fake_connect)
    repo = AnalysesRepo()

    assert repo.find_by_url("https://github.com/user/repo") is None
    assert repo.last_error is not None

    assert repo.find_by_url("https://github.com/user/repo") is None
    assert repo.last_error is None
