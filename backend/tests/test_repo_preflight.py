"""Tests del servicio de premedición de repositorios."""

from app.services.file_reader import ContextEstimate
from app.services.repo_preflight import RepoPreflightService


def test_preflight_marks_small_context_as_normal():
    service = RepoPreflightService()

    mode, reason = service._decide_mode(
        ContextEstimate(
            candidate_files=12,
            selected_files=12,
            total_candidate_chars=30_000,
            selected_chars=30_000,
            oversized_files=0,
            budget_truncated_files=0,
        )
    )

    assert mode == "normal"
    assert reason == "fits_context"


def test_preflight_marks_medium_over_budget_context_as_optimized():
    service = RepoPreflightService()

    mode, reason = service._decide_mode(
        ContextEstimate(
            candidate_files=80,
            selected_files=24,
            total_candidate_chars=150_000,
            selected_chars=80_000,
            oversized_files=1,
            budget_truncated_files=1,
        )
    )

    assert mode == "optimized"
    assert reason == "prioritized_context"


def test_preflight_marks_repo_over_750_candidate_files_as_too_large():
    service = RepoPreflightService()

    mode, reason = service._decide_mode(
        ContextEstimate(
            candidate_files=751,
            selected_files=32,
            total_candidate_chars=640_000,
            selected_chars=80_000,
            oversized_files=0,
            budget_truncated_files=1,
        )
    )

    assert mode == "too_large"
    assert reason == "file_count_limit"


def test_preflight_marks_sparse_context_as_too_large():
    service = RepoPreflightService()

    mode, reason = service._decide_mode(
        ContextEstimate(
            candidate_files=201,
            selected_files=3,
            total_candidate_chars=1_541_815,
            selected_chars=80_000,
            oversized_files=0,
            budget_truncated_files=1,
        )
    )

    assert mode == "too_large"
    assert reason == "context_budget_exceeded"


def test_preflight_marks_huge_but_still_coverable_context_as_optimized():
    service = RepoPreflightService()

    mode, reason = service._decide_mode(
        ContextEstimate(
            candidate_files=87,
            selected_files=26,
            total_candidate_chars=1_245_372,
            selected_chars=80_000,
            oversized_files=2,
            budget_truncated_files=1,
        )
    )

    assert mode == "optimized"
    assert reason == "prioritized_context"


def test_preflight_marks_sparse_huge_context_as_too_large():
    service = RepoPreflightService()

    mode, reason = service._decide_mode(
        ContextEstimate(
            candidate_files=499,
            selected_files=11,
            total_candidate_chars=2_195_694,
            selected_chars=80_000,
            oversized_files=0,
            budget_truncated_files=1,
        )
    )

    assert mode == "too_large"
    assert reason == "context_budget_exceeded"
