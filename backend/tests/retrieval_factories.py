"""Eval fixtures: finance PDFs with page-pinned facts (PyMuPDF-built)."""

import fitz

REVENUE_PAGE = (
    "Annual report fiscal year 2025. Total revenue for fiscal year 2025 was "
    "4.2 million dollars, up from 3.8 million dollars in fiscal 2024. Growth "
    "came from enterprise subscriptions and renewals across all regions. "
)
OPEX_PAGE = (
    "Operating expenses for fiscal 2025 totaled 1.1 million dollars, driven "
    "by research staffing and cloud infrastructure spending. Management "
    "expects expense discipline to continue into the next fiscal year. "
)
EBITDA_PAGE = (
    "EBITDA for fiscal 2025 reached 900 thousand dollars, a margin of twenty "
    "one percent. Depreciation and amortization remained stable year over "
    "year while operating leverage improved substantially overall. "
)
DISTRACTOR_PAGE = (
    "The company relocated its headquarters to a larger office downtown. "
    "Hiring continued across engineering and support teams throughout the "
    "spring season with new onboarding programs and training workshops. "
)
MEMO_PAGE = (
    "Quarterly office memo about facilities and schedules. The cafeteria "
    "will extend lunch hours. Parking permits renew in June for all staff "
    "members across both buildings downtown starting next Monday morning. "
)


def _pages(*texts: str) -> bytes:
    doc = fitz.open()
    for text in texts:
        doc.new_page().insert_text((72, 72), text * 4)
    return doc.tobytes()


def annual_report_pdf() -> bytes:
    return _pages(REVENUE_PAGE, OPEX_PAGE, EBITDA_PAGE, DISTRACTOR_PAGE)


def memo_pdf() -> bytes:
    return _pages(MEMO_PAGE, DISTRACTOR_PAGE)


EVAL_CASES = [
    ("What was revenue in FY2025?", 1),
    ("What were operating expenses?", 2),
    ("What was EBITDA?", 3),
]
