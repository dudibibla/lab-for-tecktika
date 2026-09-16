from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services.azure_search import _rerank_for_intent, hybrid_search


def test_hybrid_search_returns_structured_results():
    mock_client = MagicMock()
    mock_client.search.return_value = [
        {
            settings.aas_field_chunk_id: "chunk-1",
            settings.aas_field_parent_document_id: "doc-1",
            settings.aas_field_file_name: "contract.pdf",
            settings.aas_field_content: "Example content",
            settings.aas_field_page: 3,
            settings.aas_field_source_url: "https://example.test/contract.pdf",
            "@search.score": 1.25,
            "@search.reranker_score": 3.75,
        }
    ]

    with patch(
        "app.services.azure_search.get_search_client",
        return_value=mock_client,
    ):
        results = hybrid_search(
            query="What is the rent?",
            query_vector=[0.1, 0.2, 0.3],
            top=5,
        )

    assert results == [
        {
            "chunk_id": "chunk-1",
            "parent_document_id": "doc-1",
            "file_name": "contract.pdf",
            "content": "Example content",
            "page": 3,
            "source_url": "https://example.test/contract.pdf",
            "score": 1.25,
            "reranker_score": 3.75,
        }
    ]

    mock_client.search.assert_called_once()


def test_hybrid_search_builds_parent_document_filter():
    mock_client = MagicMock()
    mock_client.search.return_value = []

    with patch(
        "app.services.azure_search.get_search_client",
        return_value=mock_client,
    ):
        hybrid_search(
            query="test",
            query_vector=[0.1],
            parent_document_id="doc-123",
        )

    kwargs = mock_client.search.call_args.kwargs

    assert kwargs["filter"] == (
        f"{settings.aas_field_parent_document_id} eq 'doc-123'"
    )


def test_hybrid_search_uses_semantic_reranking_when_configured():
    mock_client = MagicMock()
    mock_client.search.return_value = []

    with patch(
        "app.services.azure_search.get_search_client",
        return_value=mock_client,
    ):
        hybrid_search(query="apartment address", query_vector=[0.1])

    kwargs = mock_client.search.call_args.kwargs
    assert kwargs["query_type"] == "semantic"
    assert kwargs["semantic_configuration_name"] == "document-content-semantic"


def test_hybrid_search_rejects_empty_query():
    with pytest.raises(ValueError, match="query must not be empty"):
        hybrid_search(
            query="   ",
            query_vector=[0.1],
        )


def test_hybrid_search_rejects_empty_vector():
    with pytest.raises(ValueError, match="query_vector must not be empty"):
        hybrid_search(
            query="test",
            query_vector=[],
        )


def test_property_address_outranks_party_contact_address():
    results = [
        {
            "content": "כתובות: האלון 71 שורש",
            "page": 31,
            "reranker_score": 3.8,
        },
        {
            "content": "הבניין: בניין ברחוב ים סוף 7 בירושלים, גוש 30245 חלקה 207",
            "page": 2,
            "reranker_score": 2.1,
        },
    ]

    reranked = _rerank_for_intent("מה כתובת הנכס?", results)

    assert [item["page"] for item in reranked] == [2, 31]


def test_non_address_query_keeps_azure_ranking():
    results = [
        {"content": "second", "reranker_score": 1.0},
        {"content": "first", "reranker_score": 4.0},
    ]

    assert _rerank_for_intent("מה גובה שכר הדירה?", results) == results
