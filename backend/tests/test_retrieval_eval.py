"""Retrieval evaluation: tiny deterministic smoke set, NOT a benchmark.

Dataset: one annual report (3 fact pages + 1 distractor) + recall/precision
at K=1..3 over three pinned questions. Historical K=1/2/3 numbers from an
older setup are explicitly NOT targets (higher K ≠ better quality); this
file only guards against regressions on the current pipeline. The report
prints; the gates stay modest by design.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import is_database_reachable, tenant_who
from tests.retrieval_factories import EVAL_CASES, annual_report_pdf

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def evaluator(clients: TestClient) -> dict:
    return tenant_who(clients, role="analyst")


@pytest.fixture(scope="module")
def indexed_report(clients: TestClient, evaluator: dict) -> str:
    uploaded = clients.post(
        "/documents/upload",
        files={"file": ("annual.pdf", annual_report_pdf(), "application/pdf")},
        data={"title": "Eval Annual Report", "fiscal_year": "2025"},
        headers=evaluator["headers"],
    )
    assert uploaded.status_code == 201, uploaded.text
    doc_id = uploaded.json()["document"]["id"]
    indexed = clients.post(f"/documents/{doc_id}/index", headers=evaluator["headers"])
    assert indexed.status_code == 200, indexed.text
    return doc_id


def _recall_precision(results: list[dict], expected_page: int, k: int):
    top = results[:k]
    hits = sum(1 for hit in top if hit["page_number"] == expected_page)
    recall = 1.0 if hits else 0.0  # single relevant page per question
    precision = hits / len(top) if top else 0.0
    reciprocal_rank = next(
        (
            1.0 / (rank + 1)
            for rank, hit in enumerate(top)
            if hit["page_number"] == expected_page
        ),
        0.0,
    )
    return recall, precision, reciprocal_rank


def test_retrieval_evaluation_report(
    clients: TestClient,
    evaluator: dict,
    indexed_report: str,
    capsys: pytest.CaptureFixture,
) -> None:
    headers = evaluator["headers"]
    rows = []
    for query, expected_page in EVAL_CASES:
        response = clients.post(
            "/documents/search", json={"query": query, "top_k": 3}, headers=headers
        )
        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert results, f"no results for {query!r}"
        row = {"query": query, "expected_page": expected_page}
        for k in (1, 2, 3):
            recall, precision, rr = _recall_precision(results, expected_page, k)
            row[f"recall@{k}"] = recall
            row[f"precision@{k}"] = precision
            if k == 3:
                row["mrr@3"] = rr
        rows.append(row)

    with capsys.disabled():
        print("\n=== retrieval eval (smoke set: 3 questions, 1 report) ===")
        for row in rows:
            print(
                f"- {row['query']!r} (p.{row['expected_page']}): "
                f"recall@1={row['recall@1']:.2f} recall@3={row['recall@3']:.2f} "
                f"precision@3={row['precision@3']:.2f} mrr@3={row['mrr@3']:.2f}"
            )
        mean_recall3 = sum(r["recall@3"] for r in rows) / len(rows)
        mean_rr = sum(r["mrr@3"] for r in rows) / len(rows)
        print(f"mean recall@3={mean_recall3:.2f} mean mrr@3={mean_rr:.2f}")

    # Smoke gates (modest by design — see module docstring).
    assert all(row["recall@3"] == 1.0 for row in rows)
    assert sum(row["recall@1"] for row in rows) / len(rows) >= 2 / 3
