import logging
from typing import Any

from azure.search.documents.models import VectorizedQuery

from app.azure_clients import get_search_client
from app.core.config import settings


logger = logging.getLogger(__name__)

_ADDRESS_TERMS = ("כתובת", "מען", "address", "located", "location")
_PROPERTY_TERMS = (
    "כתובת הנכס", "הנכס", "המושכר", "הדירה", "הבניין",
    "גוש", "חלקה", "property", "premises", "apartment", "building",
)
_PARTY_ADDRESS_TERMS = (
    "כתובות:", "כתובות הצדדים", "כתובת להודעות", "מען להודעות",
    "address for notices", "addresses of the parties",
)


def _rerank_for_intent(
    query: str,
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    query_text = query.casefold()
    if not any(term in query_text for term in _ADDRESS_TERMS):
        return results

    def intent_score(item: dict[str, Any]) -> tuple[float, float]:
        content = str(item.get("content") or "").casefold()
        role_score = sum(1.0 for term in _PROPERTY_TERMS if term in content)
        role_score -= sum(3.0 for term in _PARTY_ADDRESS_TERMS if term in content)
        azure_score = item.get("reranker_score")
        if azure_score is None:
            azure_score = item.get("score") or 0.0
        return role_score, float(azure_score)

    return sorted(results, key=intent_score, reverse=True)


def _escape_odata_string(value: str) -> str:
    return value.replace("'", "''")


def _build_filter(
    file_name: str | None = None,
    parent_document_id: str | None = None,
) -> str | None:
    filters: list[str] = []

    if file_name:
        escaped_file_name = _escape_odata_string(file_name)
        filters.append(
            f"{settings.aas_field_file_name} eq '{escaped_file_name}'"
        )

    if parent_document_id:
        escaped_document_id = _escape_odata_string(parent_document_id)
        filters.append(
            f"{settings.aas_field_parent_document_id} eq "
            f"'{escaped_document_id}'"
        )

    return " and ".join(filters) if filters else None


def hybrid_search(
    query: str,
    query_vector: list[float],
    *,
    top: int = 5,
    file_name: str | None = None,
    parent_document_id: str | None = None,
) -> list[dict[str, Any]]:
    if not query.strip():
        raise ValueError("query must not be empty")

    if not query_vector:
        raise ValueError("query_vector must not be empty")

    if top < 1:
        raise ValueError("top must be at least 1")

    client = get_search_client()

    candidate_count = max(top * 3, 15)
    vector_query = VectorizedQuery(
        vector=query_vector,
        k_nearest_neighbors=candidate_count,
        fields=settings.aas_field_vector,
    )

    search_kwargs: dict[str, Any] = {
        "search_text": query,
        "vector_queries": [vector_query],
        "filter": _build_filter(
            file_name=file_name,
            parent_document_id=parent_document_id,
        ),
        "select": [
            settings.aas_field_chunk_id,
            settings.aas_field_parent_document_id,
            settings.aas_field_file_name,
            settings.aas_field_content,
            settings.aas_field_page,
            settings.aas_field_source_url,
        ],
        "top": candidate_count,
    }

    if settings.azure_search_semantic_configuration_name:
        search_kwargs.update(
            {
                "query_type": "semantic",
                "semantic_configuration_name":
                    settings.azure_search_semantic_configuration_name,
            }
        )

    try:
        results = client.search(**search_kwargs)

        structured_results = [
            {
                "chunk_id": result.get(settings.aas_field_chunk_id),
                "parent_document_id": result.get(
                    settings.aas_field_parent_document_id
                ),
                "file_name": result.get(settings.aas_field_file_name),
                "content": result.get(settings.aas_field_content),
                "page": result.get(settings.aas_field_page),
                "source_url": result.get(settings.aas_field_source_url),
                "score": result.get("@search.score"),
                "reranker_score": result.get("@search.reranker_score"),
            }
            for result in results
        ]
        return _rerank_for_intent(query, structured_results)[:top]
    except Exception:
        logger.exception("Azure AI Search hybrid query failed")
        raise
