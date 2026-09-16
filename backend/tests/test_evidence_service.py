from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.evidence_service import (
    EvidenceCandidate,
    EvidenceReview,
    review_evidence,
)


RESULTS = [
    {"chunk_id": "party", "file_name": "lease.pdf", "page": 31, "content": "כתובות: האלון 71 שורש"},
    {"chunk_id": "property", "file_name": "lease.pdf", "page": 2, "content": "הנכס נמצא ברחוב ים סוף 7 ירושלים"},
    {"chunk_id": "other", "file_name": "lease.pdf", "page": 8, "content": "כתובת למשלוח הודעות"},
]


def completion(review: EvidenceReview):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=review))])


def candidate(index: int, value: str, relationship: str) -> EvidenceCandidate:
    return EvidenceCandidate(
        result_index=index,
        label=f"Option {index + 1}",
        value=value,
        relationship=relationship,
        reason="The passage explicitly states this relationship",
        confidence=0.9,
    )


def test_clear_review_selects_only_supported_passage():
    review = EvidenceReview(
        status="clear",
        explanation="One passage explicitly identifies the property.",
        candidates=[candidate(1, "ים סוף 7, ירושלים", "property address")],
    )
    client = MagicMock()
    client.beta.chat.completions.parse.return_value = completion(review)

    with patch("app.services.evidence_service.get_openai_client", return_value=client):
        selected = review_evidence("מה כתובת הנכס?", RESULTS)

    assert [item["chunk_id"] for item in selected] == ["property"]
    assert selected[0]["evidence_status"] == "clear"
    assert selected[0]["candidate_value"] == "ים סוף 7, ירושלים"


def test_ambiguous_review_returns_each_candidate_with_original_source():
    review = EvidenceReview(
        status="ambiguous",
        explanation="The passages associate different addresses with unclear roles.",
        candidates=[
            candidate(0, "האלון 71, שורש", "possible address"),
            candidate(1, "ים סוף 7, ירושלים", "possible address"),
        ],
    )
    client = MagicMock()
    client.beta.chat.completions.parse.return_value = completion(review)

    with patch("app.services.evidence_service.get_openai_client", return_value=client):
        selected = review_evidence("מה הכתובת?", RESULTS)

    assert [item["page"] for item in selected] == [31, 2]
    assert all(item["evidence_status"] == "ambiguous" for item in selected)


def test_insufficient_review_returns_no_evidence():
    review = EvidenceReview(
        status="insufficient",
        explanation="No passage explicitly answers the question.",
        candidates=[],
    )
    client = MagicMock()
    client.beta.chat.completions.parse.return_value = completion(review)

    with patch("app.services.evidence_service.get_openai_client", return_value=client):
        assert review_evidence("What is the cancellation fee?", RESULTS) == []


def test_reviewer_failure_returns_cautious_options_instead_of_asserting_fact():
    with patch(
        "app.services.evidence_service.get_openai_client",
        side_effect=RuntimeError("model unavailable"),
    ):
        selected = review_evidence("מה הכתובת?", RESULTS)

    assert len(selected) == 3
    assert all(item["evidence_status"] == "ambiguous" for item in selected)
    assert all(item["candidate_confidence"] == 0.0 for item in selected)


def test_invalid_ambiguous_single_candidate_falls_back_to_multiple_options():
    review = EvidenceReview(
        status="ambiguous",
        explanation="Unclear.",
        candidates=[candidate(1, "ים סוף 7", "possible address")],
    )
    client = MagicMock()
    client.beta.chat.completions.parse.return_value = completion(review)

    with patch("app.services.evidence_service.get_openai_client", return_value=client):
        selected = review_evidence("מה הכתובת?", RESULTS)

    assert len(selected) == 3
    assert all(item["candidate_confidence"] == 0.0 for item in selected)


def test_conflicting_values_cannot_be_returned_as_clear():
    review = EvidenceReview(
        status="clear",
        explanation="Incorrectly marked clear by reviewer.",
        candidates=[
            candidate(0, "האלון 71", "address"),
            candidate(1, "ים סוף 7", "address"),
        ],
    )
    client = MagicMock()
    client.beta.chat.completions.parse.return_value = completion(review)

    with patch("app.services.evidence_service.get_openai_client", return_value=client):
        selected = review_evidence("מה הכתובת?", RESULTS)

    assert len(selected) == 2
    assert all(item["evidence_status"] == "ambiguous" for item in selected)
