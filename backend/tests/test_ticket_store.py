"""Tests del subsistema de tickets efímeros del JobStore."""

import time

from app.store.job_store import JobStore


def test_issue_ticket_returns_uuid():
    store = JobStore()
    ticket = store.issue_ticket(client_ip="1.2.3.4", user_agent="pytest")
    assert len(ticket) == 36
    assert ticket.count("-") == 4


def test_consume_ticket_valid():
    store = JobStore()
    ticket = store.issue_ticket(client_ip="1.2.3.4", user_agent="pytest")
    assert (
        store.consume_ticket(
            ticket,
            client_ip="1.2.3.4",
            user_agent="pytest",
        )
        is True
    )


def test_consume_ticket_is_one_shot():
    store = JobStore()
    ticket = store.issue_ticket(client_ip="1.2.3.4", user_agent="pytest")
    assert store.consume_ticket(ticket, client_ip="1.2.3.4", user_agent="pytest")
    assert not store.consume_ticket(ticket, client_ip="1.2.3.4", user_agent="pytest")


def test_consume_ticket_rejects_other_client():
    store = JobStore()
    ticket = store.issue_ticket(client_ip="1.2.3.4", user_agent="pytest")
    assert not store.consume_ticket(
        ticket,
        client_ip="8.8.8.8",
        user_agent="pytest",
    )


def test_consume_ticket_rejects_other_user_agent():
    store = JobStore()
    ticket = store.issue_ticket(client_ip="1.2.3.4", user_agent="pytest")
    assert not store.consume_ticket(
        ticket,
        client_ip="1.2.3.4",
        user_agent="otro-agent",
    )


def test_consume_ticket_expired():
    store = JobStore()
    ticket = store.issue_ticket(client_ip="1.2.3.4", user_agent="pytest")
    store._tickets[ticket].created_at = time.time() - (store._TICKET_TTL_SECONDS + 1)
    assert not store.consume_ticket(ticket, client_ip="1.2.3.4", user_agent="pytest")


def test_cleanup_removes_expired_tickets():
    store = JobStore()
    ticket = store.issue_ticket(client_ip="1.2.3.4", user_agent="pytest")
    store._tickets[ticket].created_at = time.time() - (store._TICKET_TTL_SECONDS + 1)
    store._cleanup_expired_tickets()
    assert ticket not in store._tickets
