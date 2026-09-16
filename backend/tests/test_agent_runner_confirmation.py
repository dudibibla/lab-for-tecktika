from types import SimpleNamespace
from unittest.mock import patch

from app.agent.runner import stream_agent
from app.schemas.chat import ChatHistoryMessage
from app.services.file_resolver import ResolvedDocument


def test_delete_tool_creates_confirmation_event() -> None:
    tool_call = SimpleNamespace(
        id="call_delete_1",
        function=SimpleNamespace(
            name="delete_document",
            arguments='{"file_name":"Q3-report.pdf"}',
        ),
    )

    assistant_message = SimpleNamespace(
        content=None,
        tool_calls=[tool_call],
    )

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=assistant_message,
            )
        ]
    )

    resolved = ResolvedDocument(
        file_name="Q3-report.pdf",
        blob_name="Q3-report.pdf",
        document_id="doc_123",
        etag='"etag_123"',
    )

    with (
        patch(
            "app.agent.runner.create_chat_completion",
            return_value=response,
        ),
        patch(
            "app.agent.runner.resolve_document",
            return_value=[resolved],
        ),
        patch(
            "app.agent.runner.confirmation_store.create",
        ) as create_confirmation,
    ):
        create_confirmation.return_value = SimpleNamespace(
            confirmation_id="cf_test_123",
        )

        events = list(
            stream_agent(
                "Delete Q3-report.pdf",
                requested_by="conv_123",
            )
        )

    assert len(events) == 1

    event = events[0]

    assert event.type == "confirmation"
    assert event.confirmation is not None
    assert event.confirmation.confirmation_id == "cf_test_123"
    assert event.confirmation.action == "delete"
    assert event.confirmation.files == ["Q3-report.pdf"]
    assert event.confirmation.destructive is True

    create_confirmation.assert_called_once_with(
        action="DELETE",
        file_name="Q3-report.pdf",
        blob_name="Q3-report.pdf",
        document_id="doc_123",
        requested_by="conv_123",
        source_blob_path=None,
        etag='"etag_123"',
    )


def test_delete_prefers_exact_library_file_named_in_current_message() -> None:
    tool_call = SimpleNamespace(
        id="call_delete_wrong_history_file",
        function=SimpleNamespace(
            name="delete_document",
            arguments='{"file_name":"old-file.pdf"}',
        ),
    )
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=None,
        tool_calls=[tool_call],
    ))])
    resolved = ResolvedDocument(
        file_name="111.pdf",
        blob_name="111.pdf",
        document_id="doc_111",
        etag='"etag_111"',
    )

    with (
        patch("app.agent.runner.create_chat_completion", return_value=response),
        patch(
            "app.agent.runner.list_library_documents",
            return_value=["111.pdf", "old-file.pdf"],
        ),
        patch(
            "app.agent.runner.resolve_document",
            return_value=[resolved],
        ) as resolve,
        patch("app.agent.runner.confirmation_store.create") as create_confirmation,
    ):
        create_confirmation.return_value = SimpleNamespace(
            confirmation_id="cf_delete_111",
        )
        events = list(stream_agent(
            "מחק את 111.pdf",
            requested_by="conv_123",
        ))

    resolve.assert_called_once_with("111.pdf")
    assert events[0].confirmation is not None
    assert events[0].confirmation.files == ["111.pdf"]
    assert create_confirmation.call_args.kwargs["blob_name"] == "111.pdf"


def test_delete_rejects_multiple_exact_library_files_in_current_message() -> None:
    tool_call = SimpleNamespace(
        id="call_delete_multiple",
        function=SimpleNamespace(
            name="delete_document",
            arguments='{"file_name":"unrelated.pdf"}',
        ),
    )
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=None,
        tool_calls=[tool_call],
    ))])

    with (
        patch("app.agent.runner.create_chat_completion", return_value=response),
        patch(
            "app.agent.runner.list_library_documents",
            return_value=["111.pdf", "13122.pdf"],
        ),
    ):
        import pytest

        with pytest.raises(ValueError, match="More than one existing document"):
            list(stream_agent(
                "מחק את 111.pdf ואת 13122.pdf",
                requested_by="conv_123",
            ))


def test_replace_tool_uses_trusted_staged_attachment() -> None:
    tool_call = SimpleNamespace(
        id="call_replace_1",
        function=SimpleNamespace(
            name="replace_document",
            arguments='{"file_name":"Q3-report.pdf"}',
        ),
    )

    assistant_message = SimpleNamespace(
        content=None,
        tool_calls=[tool_call],
    )

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=assistant_message,
            )
        ]
    )

    resolved = ResolvedDocument(
        file_name="Q3-report.pdf",
        blob_name="Q3-report.pdf",
        document_id="doc_123",
        etag='"etag_123"',
    )

    with (
        patch(
            "app.agent.runner.create_chat_completion",
            return_value=response,
        ),
        patch(
            "app.agent.runner.resolve_document",
            return_value=[resolved],
        ),
        patch(
            "app.agent.runner.confirmation_store.create",
        ) as create_confirmation,
    ):
        create_confirmation.return_value = SimpleNamespace(
            confirmation_id="cf_replace_123",
        )

        events = list(
            stream_agent(
                "Replace Q3-report.pdf with the attached file",
                requested_by="conv_123",
                source_blob_path="f_1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d/report.pdf",
            )
        )

    assert len(events) == 1

    event = events[0]

    assert event.type == "confirmation"
    assert event.confirmation is not None
    assert event.confirmation.confirmation_id == "cf_replace_123"
    assert event.confirmation.action == "replace"
    assert event.confirmation.files == ["Q3-report.pdf"]
    assert event.confirmation.destructive is True

    create_confirmation.assert_called_once()

    call = create_confirmation.call_args.kwargs

    assert call["file_name"] == "Q3-report.pdf"
    assert call["document_id"] == "doc_123"
    assert call["requested_by"] == "conv_123"
    assert call["source_blob_path"] == "f_1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d/report.pdf"


def test_delete_allowed_when_attachment_is_stale_not_fresh() -> None:
    """
    A carried-over source_blob_path (fallback from an earlier turn, see the
    chat endpoint's pending-attachment lookup) must not block an unrelated
    delete request once nothing is actually attached to this message.
    """
    tool_call = SimpleNamespace(
        id="call_delete_stale",
        function=SimpleNamespace(
            name="delete_document",
            arguments='{"file_name":"Q3-report.pdf"}',
        ),
    )

    assistant_message = SimpleNamespace(
        content=None,
        tool_calls=[tool_call],
    )

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=assistant_message,
            )
        ]
    )

    resolved = ResolvedDocument(
        file_name="Q3-report.pdf",
        blob_name="Q3-report.pdf",
        document_id="doc_123",
        etag='"etag_123"',
    )

    with (
        patch(
            "app.agent.runner.create_chat_completion",
            return_value=response,
        ),
        patch(
            "app.agent.runner.resolve_document",
            return_value=[resolved],
        ),
        patch(
            "app.agent.runner.confirmation_store.create",
        ) as create_confirmation,
    ):
        create_confirmation.return_value = SimpleNamespace(
            confirmation_id="cf_test_stale",
        )

        events = list(
            stream_agent(
                "Delete Q3-report.pdf",
                requested_by="conv_123",
                source_blob_path="f_stale/leftover.pdf",
                fresh_attachment=False,
            )
        )

    assert len(events) == 1
    assert events[0].type == "confirmation"
    assert events[0].confirmation is not None
    assert events[0].confirmation.action == "delete"


def test_stream_agent_sends_previous_turns_to_model() -> None:
    assistant_message = SimpleNamespace(
        content="It is 30 days.",
        tool_calls=[],
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=assistant_message)]
    )
    history = [
        ChatHistoryMessage(
            id="msg_1", role="user", content="Read contract.pdf"
        ),
        ChatHistoryMessage(
            id="msg_2",
            role="assistant",
            content="It is the vendor agreement.",
        ),
    ]

    with patch(
        "app.agent.runner.create_chat_completion",
        return_value=response,
    ) as create_completion:
        events = list(
            stream_agent(
                "What is its notice period?",
                requested_by="conv_123",
                history=history,
            )
        )

    messages = create_completion.call_args.args[0]
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert messages[1]["content"] == "Read contract.pdf"
    assert messages[2]["content"] == "It is the vendor agreement."
    assert messages[3]["content"] == "What is its notice period?"
    assert events[0].delta == "It is 30 days."
