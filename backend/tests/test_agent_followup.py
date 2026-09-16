from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from openai.types.chat import ChatCompletionMessage

from app.agent.runner import MAX_TOOL_ROUNDS, run_agent, stream_agent
from app.services.azure_openai import stream_chat_completion


def search_message(call_id: str = "search_1") -> ChatCompletionMessage:
    return ChatCompletionMessage(
        role="assistant", content=None,
        tool_calls=[{
            "id": call_id, "type": "function",
            "function": {"name": "search_documents", "arguments": '{"query":"address"}'},
        }],
    )


def response(message: ChatCompletionMessage) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def frame(content=None, calls=None, finish=None) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=content, tool_calls=calls), finish_reason=finish,
    )])


def fragment(index: int, call_id=None, name=None, arguments="") -> SimpleNamespace:
    return SimpleNamespace(index=index, id=call_id, function=SimpleNamespace(
        name=name, arguments=arguments,
    ))


def test_followup_search_fragments_produce_answer_and_preserve_tool_history():
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        iter([
            frame(calls=[fragment(0, "search_2", "search_documents", '{"query":')]),
            frame(calls=[fragment(0, arguments='"apartment address"}')]),
            frame(finish="tool_calls"),
        ]),
        iter([frame("The address is "), frame("10 Test Street.", finish="stop")]),
    ]
    with (
        patch("app.agent.runner.create_chat_completion", return_value=response(search_message())),
        patch("app.services.azure_openai.get_openai_client", return_value=client),
        patch("app.agent.tools.search_tool.create_query_embedding", return_value=[0.1]),
        patch("app.agent.tools.search_tool.hybrid_search", return_value=[{
            "chunk_id": "chunk1", "file_name": "contract.pdf", "content": "10 Test Street",
        }]) as search,
    ):
        events = list(stream_agent("Where is the apartment?", requested_by="user1"))
    assert "".join(event.delta or "" for event in events) == "The address is 10 Test Street."
    assert sum(event.type == "citations" for event in events) == 2
    assert search.call_count == 2
    assert search.call_args.args[0] == "apartment address"
    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert [m["tool_call_id"] for m in messages if isinstance(m, dict) and m["role"] == "tool"] == ["search_1", "search_2"]


@pytest.mark.parametrize("streaming", [False, True])
def test_tool_loop_is_bounded(streaming):
    with (
        patch("app.agent.runner.create_chat_completion", return_value=response(search_message())) as completion,
        patch("app.agent.runner.stream_chat_completion", side_effect=lambda *a, **k: iter([search_message()])),
        patch("app.agent.tools.search_tool.create_query_embedding", return_value=[0.1]),
        patch("app.agent.tools.search_tool.hybrid_search", return_value=[]) as search,
    ):
        with pytest.raises(ValueError, match="search limit"):
            if streaming:
                list(stream_agent("address", requested_by="user1"))
            else:
                run_agent("address")
    assert search.call_count == MAX_TOOL_ROUNDS
    assert completion.call_count == (1 if streaming else MAX_TOOL_ROUNDS + 1)


@pytest.mark.parametrize("streaming", [False, True])
def test_initial_empty_answer_is_reported(streaming):
    with patch("app.agent.runner.create_chat_completion", return_value=response(
        ChatCompletionMessage(role="assistant", content="   "),
    )):
        with pytest.raises(ValueError, match="empty answer"):
            if streaming:
                list(stream_agent("address", requested_by="user1"))
            else:
                run_agent("address")


@pytest.mark.parametrize("frames,match", [
    ([], "empty answer"),
    ([frame(" "), frame(finish="stop")], "empty answer"),
    ([frame(finish="length")], "could not complete"),
    ([frame(finish="content_filter")], "could not complete"),
])
def test_stream_does_not_silently_accept_empty_or_incomplete_answer(frames, match):
    client = MagicMock()
    client.chat.completions.create.return_value = iter(frames)
    with patch("app.services.azure_openai.get_openai_client", return_value=client):
        with pytest.raises(ValueError, match=match):
            list(stream_chat_completion([]))


def test_followup_delete_still_requires_confirmation():
    delete = ChatCompletionMessage(role="assistant", content=None, tool_calls=[{
        "id": "delete1", "type": "function",
        "function": {"name": "delete_document", "arguments": '{"file_name":"contract.pdf"}'},
    }])
    from app.schemas.confirmation import ConfirmationEvent
    confirmation = ConfirmationEvent(
        confirmationId="cf_test", action="delete", summary="Delete?",
        files=["contract.pdf"], destructive=True,
    )
    with (
        patch("app.agent.runner.create_chat_completion", return_value=response(search_message())),
        patch("app.agent.runner.stream_chat_completion", return_value=iter([delete])),
        patch("app.agent.tools.search_tool.create_query_embedding", return_value=[0.1]),
        patch("app.agent.tools.search_tool.hybrid_search", return_value=[]),
        patch("app.agent.runner._prepare_confirmation", return_value=confirmation) as prepare,
        patch("app.agent.runner.create_job_and_enqueue") as enqueue,
    ):
        events = list(stream_agent("Find then delete", requested_by="user1"))
    assert [event.type for event in events] == ["confirmation"]
    prepare.assert_called_once()
    enqueue.assert_not_called()


def test_non_streaming_followup_search_returns_final_answer():
    with (
        patch("app.agent.runner.create_chat_completion", side_effect=[
            response(search_message()), response(search_message("search_2")),
            response(ChatCompletionMessage(role="assistant", content="10 Test Street.")),
        ]),
        patch("app.agent.tools.search_tool.create_query_embedding", return_value=[0.1]),
        patch("app.agent.tools.search_tool.hybrid_search", return_value=[]) as search,
    ):
        assert run_agent("address") == "10 Test Street."
    assert search.call_count == 2


def test_empty_answer_after_citations_reaches_client_as_sse_error():
    from app.api.v1.endpoints.chat import _sse_response

    client = MagicMock()
    client.chat.completions.create.return_value = iter([frame(finish="stop")])
    with (
        patch("app.agent.runner.create_chat_completion", return_value=response(search_message())),
        patch("app.services.azure_openai.get_openai_client", return_value=client),
        patch("app.agent.tools.search_tool.create_query_embedding", return_value=[0.1]),
        patch("app.agent.tools.search_tool.hybrid_search", return_value=[{
            "chunk_id": "chunk1", "file_name": "contract.pdf", "content": "address",
        }]),
    ):
        frames = "".join(_sse_response(
            "conv_test", stream_agent("address", requested_by="user1"), "user1",
        ))
    assert "event: citations" in frames
    assert "event: error" in frames
    assert "empty answer" in frames
    assert "event: done" not in frames


def test_interleaved_stream_tool_calls_keep_their_ids_and_arguments():
    client = MagicMock()
    client.chat.completions.create.return_value = iter([
        frame(calls=[fragment(1, "b", "search_documents", '{"query":"second')]),
        frame(calls=[fragment(0, "a", "search_documents", '{"query":"first')]),
        frame(calls=[fragment(1, arguments='"}'), fragment(0, arguments='"}')]),
        frame(finish="tool_calls"),
    ])
    with patch("app.services.azure_openai.get_openai_client", return_value=client):
        result = list(stream_chat_completion([]))
    assert len(result) == 1
    assert isinstance(result[0], ChatCompletionMessage)
    assert [(call.id, call.function.arguments) for call in result[0].tool_calls] == [
        ("a", '{"query":"first"}'), ("b", '{"query":"second"}'),
    ]
