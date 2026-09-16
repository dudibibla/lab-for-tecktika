import logging
from dataclasses import dataclass
from collections.abc import Iterable, Iterator

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

from app.azure_clients import get_openai_client
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class _ToolCall:
    id: str = ""
    name: str = ""
    arguments: str = ""


def create_query_embedding(text: str) -> list[float]:
    if not text.strip():
        raise ValueError("text must not be empty")

    try:
        client = get_openai_client()

        response = client.embeddings.create(
            model=settings.openai_embedding_deployment,
            input=text,
            dimensions=1536,
        )

        if not response.data:
            raise RuntimeError("Azure OpenAI returned no embedding data")

        return response.data[0].embedding

    except Exception:
        logger.exception("Azure OpenAI embedding request failed")
        raise


def create_chat_completion(
    messages: Iterable[ChatCompletionMessageParam],
    *,
    tools: Iterable[ChatCompletionToolParam] | None = None,
) -> ChatCompletion:
    client = get_openai_client()

    kwargs = {
        "model": settings.openai_chat_deployment,
        "messages": messages,
    }

    if tools is not None:
        kwargs["tools"] = tools

    try:
        response = client.chat.completions.create(**kwargs)

        if not isinstance(response, ChatCompletion):
            raise RuntimeError(
                "Azure OpenAI returned an unexpected chat response type"
            )

        return response

    except Exception:
        logger.exception("Azure OpenAI chat completion request failed")
        raise


def stream_chat_completion(
    messages: Iterable[ChatCompletionMessageParam],
    *,
    tools: Iterable[ChatCompletionToolParam] | None = None,
) -> Iterator[str | ChatCompletionMessage]:
    client = get_openai_client()

    kwargs = {
        "model": settings.openai_chat_deployment,
        "messages": messages,
        "stream": True,
    }

    if tools is not None:
        kwargs["tools"] = tools

    try:
        stream = client.chat.completions.create(**kwargs)

        tool_calls: dict[int, _ToolCall] = {}
        text_parts: list[str] = []
        for chunk in stream:
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            if getattr(choice, "finish_reason", None) in {"length", "content_filter"}:
                raise ValueError("The model could not complete its answer. Please try again.")
            delta = choice.delta
            for call in getattr(delta, "tool_calls", None) or []:
                entry = tool_calls.setdefault(call.index, _ToolCall())
                if call.id:
                    entry.id = call.id
                if call.function:
                    if call.function.name:
                        entry.name += call.function.name
                    if call.function.arguments:
                        entry.arguments += call.function.arguments
            content = delta.content

            if content:
                text_parts.append(content)
                yield content

        if tool_calls:
            yield ChatCompletionMessage(
                role="assistant",
                content="".join(text_parts) or None,
                tool_calls=[{
                    "id": tool_calls[index].id,
                    "type": "function",
                    "function": {
                        "name": tool_calls[index].name,
                        "arguments": tool_calls[index].arguments,
                    },
                } for index in sorted(tool_calls)],
            )
        elif not "".join(text_parts).strip():
            raise ValueError("The model returned an empty answer. Please try again.")

    except Exception:
        logger.exception("Azure OpenAI streaming request failed")
        raise
