"""Tests para la derivación y fusión de tags de biblioteca."""

from app.services.analysis_tags import derive_analysis_tags, merge_tags


def test_derive_analysis_tags_prefers_repo_signals_from_document():
    document = """
    ## Stack tecnológico

    Backend en Python con FastAPI y Redis.
    Frontend en Astro y TypeScript.
    Despliegue con Docker Compose y persistencia en Supabase/Postgres.
    """

    assert derive_analysis_tags(document) == [
        "python",
        "typescript",
        "fastapi",
        "astro",
        "docker",
        "supabase",
        "postgresql",
        "redis",
    ]


def test_merge_tags_preserves_priority_and_removes_duplicates():
    assert merge_tags(
        ["fastapi", "python", "redis"],
        ["python", "backend", "redis", "api"],
    ) == ["fastapi", "python", "redis", "backend", "api"]
