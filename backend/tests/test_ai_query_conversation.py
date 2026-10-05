"""Conversational /ai/query end to end with a fake provider.

Proves the thread lifecycle: user questions persist, answers persist,
history reaches the prompt as delimited context, stateless calls stay
stateless, provider failures leave only the user message, and concurrent
appends keep a contiguous sequence. Citation behavior from Phase 7/8 is
re-exercised through the threaded path (regression).
"""

import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm_client
from app.main import create_app
from app.services.groq_client import GroqTimeoutError, LLMResponse
from tests.conftest import is_database_reachable, tenant_who

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


class FakeGroqClient:
    def __init__(self, text: str = "Done. [CALC-1]", error=None) -> None:
        self.text = text
        self.error = error
        self.calls: list[dict] = []

    def complete(self, *, messages, model, temperature, max_tokens, timeout_s):
        self.calls.append({"messages": messages, "model": model})
        if self.error is not None:
            raise self.error
        return LLMResponse(text=self.text, model=model, usage={}, latency_ms=2)


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def analyst(clients: TestClient) -> dict:
    return tenant_who(clients, role="analyst")


def _routed(fake) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app()
    app.dependency_overrides[get_llm_client] = lambda: fake
    return TestClient(app)


def _thread(routed: TestClient, headers: dict, title: str = "E2E") -> str:
    response = routed.post("/conversations", json={"title": title}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _messages(routed: TestClient, headers: dict, thread_id: str) -> list[dict]:
    detail = routed.get(f"/conversations/{thread_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    return detail.json()["messages"]


def _seed_revenue(routed: TestClient, headers: dict) -> None:
    for amount, year in (("1000.00", 2024), ("1200.00", 2025)):
        response = routed.post(
            "/revenue",
            json={
                "amount": amount,
                "currency": "USD",
                "record_date": f"{year}-10-15",
                "fiscal_year": year,
                "fiscal_quarter": 4,
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text


def test_multiturn_thread_persists_and_uses_context(
    analyst: dict,
) -> None:
    routed = _routed(FakeGroqClient("Revenue was 1200.00. [CALC-1]"))
    _seed_revenue(routed, analyst["headers"])
    thread = _thread(routed, analyst["headers"])

    first = routed.post(
        "/ai/query",
        json={
            "question": "What was total revenue in FY2025?",
            "conversation_id": thread,
        },
        headers=analyst["headers"],
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "grounded"

    history = _messages(routed, analyst["headers"], thread)
    assert [(m["role"], m["sequence"]) for m in history] == [
        ("user", 0),
        ("assistant", 1),
    ]
    assert history[0]["content"] == "What was total revenue in FY2025?"

    # Follow-up resolves via dataset carryforward ("revenue … FY2024") into
    # the SQL list route; seed a fake matching that route's citations.
    fake2 = FakeGroqClient("FY2024 rows: [DATA-1].")
    routed2 = _routed(fake2)
    second = routed2.post(
        "/ai/query",
        json={"question": "What about FY2024?", "conversation_id": thread},
        headers=analyst["headers"],
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "grounded"
    history = _messages(routed, analyst["headers"], thread)
    assert [m["sequence"] for m in history] == [0, 1, 2, 3]
    assert history[2]["content"] == "What about FY2024?"
    # The follow-up prompt carried the prior turn as delimited context.
    followup_prompt = fake2.calls[0]["messages"][1]["content"]
    assert "<CONVERSATION_CONTEXT>" in followup_prompt
    assert "What was total revenue in FY2025?" in followup_prompt


def test_stateless_query_writes_nothing(analyst: dict) -> None:
    fake = FakeGroqClient("Revenue was 1200.00. [CALC-1]")
    routed = _routed(fake)
    thread = _thread(routed, analyst["headers"])
    response = routed.post(
        "/ai/query",
        json={
            "question": "What was total revenue in FY2025?",
            "calculation": {
                "dataset": "revenue",
                "operation": "sum",
                "filters": {"fiscal_year": 2025},
            },
        },
        headers=analyst["headers"],
    )
    assert response.status_code == 200
    # No conversation_id: the thread stays empty, nothing persisted anywhere.
    assert _messages(routed, analyst["headers"], thread) == []


def test_invalid_conversation_id_is_404(analyst: dict) -> None:
    fake = FakeGroqClient("Never used.")
    routed = _routed(fake)
    response = routed.post(
        "/ai/query",
        json={
            "question": "What was revenue?",
            "conversation_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=analyst["headers"],
    )
    assert response.status_code == 404
    assert fake.calls == []


def test_provider_failure_keeps_user_message_only(analyst: dict) -> None:
    fake = FakeGroqClient(error=GroqTimeoutError("slow"))
    routed = _routed(fake)
    thread = _thread(routed, analyst["headers"])
    response = routed.post(
        "/ai/query",
        json={
            "question": "What was total revenue in FY2025?",
            "conversation_id": thread,
        },
        headers=analyst["headers"],
    )
    assert response.status_code == 503
    history = _messages(routed, analyst["headers"], thread)
    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "What was total revenue in FY2025?")
    ]


def test_citation_regression_through_thread(analyst: dict) -> None:
    fake = FakeGroqClient("Revenue was 1200.00. [CALC-1] See [CALC-9].")
    routed = _routed(fake)
    thread = _thread(routed, analyst["headers"])
    response = routed.post(
        "/ai/query",
        json={
            "question": "What was total revenue in FY2025?",
            "conversation_id": thread,
        },
        headers=analyst["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "citation_invalid"
    assert "[CALC-9]" not in body["answer"]
    history = _messages(routed, analyst["headers"], thread)
    assert len(history) == 2
    assert "[CALC-9]" not in history[1]["content"]


def test_insufficient_evidence_persists_both_sides(analyst: dict) -> None:
    fake = FakeGroqClient("Must never be used.")
    routed = _routed(fake)
    thread = _thread(routed, analyst["headers"])
    response = routed.post(
        "/ai/query",
        json={"question": "Tell me stuff.", "conversation_id": thread},
        headers=analyst["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert fake.calls == []
    history = _messages(routed, analyst["headers"], thread)
    assert [m["role"] for m in history] == ["user", "assistant"]


def test_concurrent_appends_keep_contiguous_sequences(analyst: dict) -> None:
    from app.db.engine import dispose_engine, get_engine, session_scope

    from app.models.conversation import MessageRole
    from app.services import conversation_service
    from app.services.tenancy import TenantContext
    from app.models.user_role import Role
    from app.repositories import (
        company_repository,
        membership_repository,
        user_repository,
    )

    fake = FakeGroqClient("x")
    routed = _routed(fake)
    thread = _thread(routed, analyst["headers"])
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        # Shared process engine (pool-backed); disposed once below, never here.
        local_engine = get_engine()
        try:
            with session_scope(local_engine) as session:
                db_user = user_repository.get_by_id(
                    session, uuid.UUID(analyst["user_id"])
                )
                assert db_user is not None
                memberships = membership_repository.list_for_user(
                    session, user_id=db_user.id
                )
                company = company_repository.get_by_id(
                    session, memberships[0].company_id
                )
                assert company is not None
                ctx = TenantContext(
                    user=db_user,
                    company=company,
                    role=Role.analyst,
                    company_id=company.id,
                )
                conversation_service.append_message(
                    session,
                    ctx=ctx,
                    conversation_id=uuid.UUID(thread),
                    role=MessageRole.user,
                    content=f"concurrent {index}",
                )
        except BaseException as exc:  # collected, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for thread_handle in threads:
        thread_handle.start()
    for thread_handle in threads:
        thread_handle.join()
    dispose_engine()
    assert errors == []
    history = _messages(routed, analyst["headers"], thread)
    assert sorted(m["sequence"] for m in history) == [0, 1, 2, 3, 4]
