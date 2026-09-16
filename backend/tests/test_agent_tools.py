import pytest
from pydantic import ValidationError

from app.agent.tools.document_tools import (
    AddDocumentTool,
    DeleteDocumentTool,
    ReplaceDocumentTool,
)
from app.schemas.tools import (
    AddDocumentArgs,
    DeleteDocumentArgs,
    ReplaceDocumentArgs,
)


def test_add_document_tool_validates_arguments() -> None:
    tool = AddDocumentTool()

    arguments = tool.validate_args(
        {
            "file_name": "contract.pdf",
        }
    )

    assert arguments.file_name == "contract.pdf"


def test_replace_document_tool_validates_arguments() -> None:
    tool = ReplaceDocumentTool()

    arguments = tool.validate_args(
        {
            "file_name": "contract.pdf",
        }
    )

    assert arguments.file_name == "contract.pdf"


def test_delete_document_tool_validates_arguments() -> None:
    tool = DeleteDocumentTool()

    result = tool.validate_args(
        {
            "file_name": "contract.pdf",
        }
    )

    assert isinstance(result, DeleteDocumentArgs)


def test_add_document_tool_rejects_unknown_source_blob_path() -> None:
    tool = AddDocumentTool()

    with pytest.raises(ValidationError):
        tool.validate_args(
            {
                "file_name": "contract.pdf",
                "source_blob_path": "staging/untrusted.pdf",
            }
        )


def test_delete_document_tool_rejects_empty_file_name() -> None:
    tool = DeleteDocumentTool()

    with pytest.raises(ValidationError):
        tool.validate_args(
            {
                "file_name": "",
            }
        )


def test_delete_document_tool_rejects_unknown_fields() -> None:
    tool = DeleteDocumentTool()

    with pytest.raises(ValidationError):
        tool.validate_args(
            {
                "file_name": "contract.pdf",
                "force": True,
            }
        )


def test_to_openai_tool_builds_function_schema() -> None:
    from app.agent.tools.base import to_openai_tool

    tool = DeleteDocumentTool()

    schema = to_openai_tool(tool)

    assert schema["type"] == "function"

    function = schema["function"]

    assert isinstance(function, dict)
    assert function["name"] == "delete_document"
    assert function["description"] == "Delete an existing document"

    parameters = function["parameters"]

    assert isinstance(parameters, dict)
    assert parameters["type"] == "object"
    assert "file_name" in parameters["properties"]
    assert "file_name" in parameters["required"]
    assert parameters["additionalProperties"] is False


def test_search_documents_tool_executes_embedding_and_search() -> None:
    from unittest.mock import patch

    from app.agent.tools.search_tool import SearchDocumentsTool

    tool = SearchDocumentsTool()
    arguments = tool.validate_args(
        {
            "query": "What is the rent?",
            "file_name": "contract.pdf",
        }
    )

    expected_results = [
        {
            "content": "Monthly rent is 5,000 NIS",
            "file_name": "contract.pdf",
            "page": 2,
        }
    ]

    with (
        patch(
            "app.agent.tools.search_tool.create_query_embedding",
            return_value=[0.1, 0.2, 0.3],
        ) as mock_embedding,
        patch(
            "app.agent.tools.search_tool.hybrid_search",
            return_value=expected_results,
        ) as mock_search,
    ):
        result = tool.execute(arguments)

    mock_embedding.assert_called_once_with("What is the rent?")

    mock_search.assert_called_once_with(
        "What is the rent?",
        [0.1, 0.2, 0.3],
        file_name="contract.pdf",
        parent_document_id=None,
    )

    assert result == expected_results


def test_parse_tool_arguments_returns_validated_model() -> None:
    from app.agent.runner import parse_tool_arguments
    from app.agent.tools.document_tools import DeleteDocumentTool

    tool = DeleteDocumentTool()

    result = parse_tool_arguments(
        tool,
        '{"file_name":"contract.pdf"}',
    )

    assert result.file_name == "contract.pdf"


def test_parse_tool_arguments_rejects_invalid_json() -> None:
    import pytest

    from app.agent.runner import parse_tool_arguments
    from app.agent.tools.document_tools import DeleteDocumentTool

    tool = DeleteDocumentTool()

    with pytest.raises(
        ValueError,
        match="Tool arguments are not valid JSON",
    ):
        parse_tool_arguments(
            tool,
            '{"file_name":"contract.pdf"',
        )


def test_parse_tool_arguments_rejects_non_object_json() -> None:
    import pytest

    from app.agent.runner import parse_tool_arguments
    from app.agent.tools.document_tools import DeleteDocumentTool

    tool = DeleteDocumentTool()

    with pytest.raises(
        ValueError,
        match="Tool arguments must be a JSON object",
    ):
        parse_tool_arguments(
            tool,
            '["contract.pdf"]',
        )


def test_run_agent_executes_search_tool_and_returns_final_answer() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from app.agent.runner import run_agent

    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="search_documents",
            arguments='{"query":"What is the rent?"}',
        ),
    )

    first_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[tool_call],
                )
            )
        ]
    )

    second_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="The monthly rent is 5,000.",
                    tool_calls=None,
                )
            )
        ]
    )

    search_tool = MagicMock()
    search_tool.name = "search_documents"
    search_tool.execute.return_value = [
        {
            "chunk_id": "chunk_1",
            "file_name": "contract.pdf",
            "content": "Monthly rent: 5,000.",
            "page": 2,
            "source_url": None,
            "score": 10.0,
        }
    ]

    with (
        patch(
            "app.agent.runner.create_chat_completion",
            side_effect=[first_response, second_response],
        ),
        patch(
            "app.agent.runner.get_tool_by_name",
            return_value=search_tool,
        ),
        patch(
            "app.agent.runner.parse_tool_arguments",
            return_value=MagicMock(),
        ),
    ):
        result = run_agent("What is the rent?")

    assert result == "The monthly rent is 5,000."
    search_tool.execute.assert_called_once()

def test_stream_agent_executes_search_tool_and_streams_final_answer() -> None:
    from unittest.mock import MagicMock, patch

    from app.agent.runner import stream_agent

    first_response = MagicMock()
    tool_call = MagicMock()
    tool_call.id = "call_1"
    tool_call.function.name = "search_documents"
    tool_call.function.arguments = '{"query":"rent"}'

    first_response.choices[0].message.tool_calls = [tool_call]

    search_tool = MagicMock()
    search_tool.name = "search_documents"
    search_tool.execute.return_value = [
        {
            "file_name": "contract.pdf",
            "content": "The monthly rent is 5,000.",
        }
    ]

    with (
        patch(
            "app.agent.runner.create_chat_completion",
            return_value=first_response,
        ),
        patch(
            "app.agent.runner.stream_chat_completion",
            return_value=iter(
                [
                    "The monthly ",
                    "rent is 5,000.",
                ]
            ),
        ) as mock_stream,
        patch(
            "app.agent.runner.get_tool_by_name",
            return_value=search_tool,
        ),
        patch(
            "app.agent.runner.parse_tool_arguments",
            return_value=MagicMock(),
        ),
    ):
        events = list(
            stream_agent(
                "What is the rent?",
                requested_by="conv_test",
            )
        )

    assert [event.type for event in events] == [
        "delta",
        "delta",
    ]

    assert [event.delta for event in events] == [
        "The monthly ",
        "rent is 5,000.",
    ]

    search_tool.execute.assert_called_once()
    mock_stream.assert_called_once()


def test_citations_are_deduplicated_and_capped() -> None:
    from app.agent.runner import MAX_CITATIONS, _citations_from_results

    results = [
        {
            "chunk_id": f"chunk-{index if index != 1 else 0}",
            "file_name": "contract.pdf",
            "content": f"result {index}",
            "page": index + 1,
        }
        for index in range(MAX_CITATIONS + 3)
    ]

    citations = _citations_from_results(results)

    assert len(citations) == MAX_CITATIONS
    assert len({citation.id for citation in citations}) == MAX_CITATIONS
