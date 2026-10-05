"""Citation-format regression tests: Unicode-tolerant detection, canonical validation.

Pure unit tests (no DB, no provider): the canonical API format stays
[CALC-n]/[DOC-n]/[DATA-n]; parsing additionally accepts common Unicode
bracket/hyphen/digit variants WITHOUT rewriting valid answer text.
Unknown citations are still stripped and flagged — validation is not weakened.
"""

from app.services.answer_service import validate_citations

VALID = frozenset({"[CALC-1]", "[DOC-1]", "[DOC-2]"})


def test_canonical_ascii_unchanged() -> None:
    cleaned, valid, unknown = validate_citations("Revenue was 1200.00. [CALC-1]", VALID)
    assert (cleaned, valid, unknown) == (
        "Revenue was 1200.00. [CALC-1]",
        ["[CALC-1]"],
        False,
    )


def test_cjk_brackets_recognized() -> None:
    cleaned, valid, unknown = validate_citations(
        "Revenue was 1200.00. 【CALC-1】", VALID
    )
    assert valid == ["[CALC-1]"] and unknown is False
    assert "【CALC-1】" in cleaned  # valid text left exactly as written


def test_nonbreaking_hyphen_recognized() -> None:
    for variant in ("DOC‑1", "DOC‐1", "DOC–1"):  # U+2011, U+2010, U+2013
        cleaned, valid, unknown = validate_citations(f"See [{variant}].", VALID)
        assert valid == ["[DOC-1]"], variant
        assert unknown is False
        assert variant in cleaned


def test_fullwidth_brackets_and_digits_recognized() -> None:
    cleaned, valid, unknown = validate_citations("See ［DOC－２］.", VALID)
    assert valid == ["[DOC-2]"] and unknown is False


def test_unknown_unicode_citation_stripped_and_flagged() -> None:
    cleaned, valid, unknown = validate_citations(
        "Revenue was 1200.00. 【CALC-999】", VALID
    )
    assert valid == [] and unknown is True
    assert "CALC-999" not in cleaned and "【" not in cleaned
    assert cleaned == "Revenue was 1200.00."


def test_unknown_ascii_still_stripped() -> None:
    cleaned, valid, unknown = validate_citations("See [DOC-9].", VALID)
    assert (cleaned, valid, unknown) == ("See .", [], True)


def test_duplicates_deduped_across_spellings() -> None:
    cleaned, valid, unknown = validate_citations(
        "[CALC-1] confirms it, see also 【CALC-1】.", VALID
    )
    assert valid == ["[CALC-1]"] and unknown is False
    assert "[CALC-1]" in cleaned and "【CALC-1】" in cleaned


def test_wrong_kinds_ignored() -> None:
    cleaned, valid, unknown = validate_citations("See [PAGE-42] and (DOC-1).", VALID)
    assert (cleaned, valid, unknown) == ("See [PAGE-42] and (DOC-1).", [], False)


def test_empty_after_strip_falls_back() -> None:
    cleaned, valid, unknown = validate_citations("【CALC-999】", VALID)
    assert unknown is True and valid == []
    assert cleaned == "The generated answer failed citation validation."
