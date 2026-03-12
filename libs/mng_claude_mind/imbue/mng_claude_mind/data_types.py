from __future__ import annotations

from typing import Any
from typing import Final

from pydantic import Field

from imbue.imbue_common.event_envelope import EventEnvelope
from imbue.imbue_common.event_envelope import EventSource
from imbue.imbue_common.frozen_model import FrozenModel
from imbue.imbue_common.primitives import NonEmptyStr
from imbue.imbue_common.primitives import NonNegativeInt
from imbue.imbue_common.primitives import PositiveInt
from imbue.mng_llm.data_types import ChatModel
from imbue.mng_llm.data_types import LlmSettings
from imbue.mng_recursive.watcher_common import DEFAULT_CEL_FILTER


class ConversationId(NonEmptyStr):
    """Unique identifier for a conversation thread (matches llm's conversation_id format)."""


class MessageRole(NonEmptyStr):
    """Role of a message sender (e.g. 'user', 'assistant')."""


# -- Event log sources --
# These constants define the source names and corresponding log paths.
# Event sources write to events/<SOURCE>/events.jsonl (proper EventEnvelope format).
# Log sources write to logs/<SOURCE>/events.jsonl (raw format, not EventEnvelope).

SOURCE_MESSAGES: Final[EventSource] = EventSource("messages")
SOURCE_SCHEDULED: Final[EventSource] = EventSource("scheduled")
SOURCE_MNG_AGENTS: Final[EventSource] = EventSource("mng/agents")
SOURCE_STOP: Final[EventSource] = EventSource("stop")
SOURCE_MONITOR: Final[EventSource] = EventSource("monitor")
SOURCE_DELIVERY_FAILURES: Final[EventSource] = EventSource("delivery_failures")
SOURCE_COMMON_TRANSCRIPT: Final[EventSource] = EventSource("common_transcript")


class MessageEvent(EventEnvelope):
    """An event in events/messages/events.jsonl recording a conversation message."""

    conversation_id: ConversationId
    role: MessageRole
    content: str


class MindEvent(EventEnvelope):
    """A generic event with a data payload, used for sources like scheduled,
    mng/agents, stop, and monitor.
    """

    data: dict[str, Any] = {}


# -- Common transcript types --


class CommonToolCallSummary(FrozenModel):
    """Summary of a single tool invocation within an assistant message."""

    tool_call_id: NonEmptyStr = Field(description="Unique ID for this tool call (from the API response).")
    tool_name: NonEmptyStr = Field(description="Name of the tool invoked (e.g. 'Bash', 'Read', 'Edit').")
    input_preview: str = Field(description="Truncated serialization of the tool input arguments.")


class CommonTokenUsage(FrozenModel):
    """Token usage counts for an assistant message."""

    input_tokens: NonNegativeInt = Field(description="Number of input tokens consumed.")
    output_tokens: NonNegativeInt = Field(description="Number of output tokens generated.")
    cache_read_tokens: NonNegativeInt | None = Field(
        default=None, description="Cache-read input tokens (None if not reported)."
    )
    cache_write_tokens: NonNegativeInt | None = Field(
        default=None, description="Cache-write input tokens (None if not reported)."
    )


class CommonUserMessageEvent(EventEnvelope):
    """A user message in the common transcript."""

    role: MessageRole = Field(default=MessageRole("user"), description="Always 'user'.")
    content: str = Field(description="The user's message text.")
    message_uuid: str | None = Field(
        default=None, description="UUID from the raw Claude JSONL event (for traceability)."
    )


class CommonAssistantMessageEvent(EventEnvelope):
    """An assistant response in the common transcript."""

    role: MessageRole = Field(default=MessageRole("assistant"), description="Always 'assistant'.")
    model: ChatModel = Field(description="Model that generated this response (e.g. 'claude-opus-4.6').")
    text: str = Field(description="Concatenated text content blocks from the response.")
    tool_calls: tuple[CommonToolCallSummary, ...] = Field(default=(), description="Tool calls made in this response.")
    stop_reason: str | None = Field(default=None, description="Why the response ended (e.g. 'end_turn', 'tool_use').")
    usage: CommonTokenUsage | None = Field(default=None, description="Token usage for this response.")
    message_uuid: str | None = Field(
        default=None, description="UUID from the raw Claude JSONL event (for traceability)."
    )


class CommonToolResultEvent(EventEnvelope):
    """A tool result in the common transcript."""

    tool_call_id: NonEmptyStr = Field(description="ID of the tool call this result corresponds to.")
    tool_name: NonEmptyStr = Field(description="Name of the tool (resolved from the preceding assistant message).")
    output: str = Field(description="Truncated output text from the tool.")
    is_error: bool = Field(description="Whether the tool returned an error.")
    message_uuid: str | None = Field(
        default=None, description="UUID from the raw Claude JSONL event (for traceability)."
    )


# -- Settings types --
# These model the structure of minds.toml.
# Each section corresponds to a TOML table.


class WatcherSettings(FrozenModel):
    """Settings for the [watchers] TOML section."""

    conversation_poll_interval_seconds: PositiveInt = Field(
        default=PositiveInt(5),
        description="Poll interval for the conversation watcher (seconds).",
    )
    event_poll_interval_seconds: PositiveInt = Field(
        default=PositiveInt(3),
        description="Poll interval for the event watcher (seconds).",
    )
    transcript_poll_interval_seconds: PositiveInt = Field(
        default=PositiveInt(5),
        description="Poll interval for the transcript watcher (seconds).",
    )
    event_cel_filter: str = Field(
        default=DEFAULT_CEL_FILTER,
        description="CEL filter expression passed to 'mng events --filter'. "
        "Controls which event sources the event watcher receives.",
    )
    event_burst_size: PositiveInt = Field(
        default=PositiveInt(5),
        description="Number of messages allowed in the initial burst before rate limiting kicks in.",
    )
    max_event_messages_per_minute: PositiveInt = Field(
        default=PositiveInt(10),
        description="Maximum event messages delivered to the agent per minute (sustained rate).",
    )
    high_rate_warning_threshold_per_minute: PositiveInt = Field(
        default=PositiveInt(8),
        description="When messages per minute exceeds this, include a rate warning in the delivery envelope.",
    )
    max_delivery_retries: PositiveInt = Field(
        default=PositiveInt(3),
        description="Maximum consecutive delivery failures before notifying the user. "
        "Uses exponential backoff between retries.",
    )


class ClaudeMindSettings(LlmSettings):
    """Top-level settings loaded from minds.toml.

    Extends LlmSettings (chat, provisioning) with mind-specific sections
    (agent_type, watchers). All fields have defaults, so an empty or missing
    settings file produces a valid settings object with the standard defaults.
    """

    agent_type: str | None = Field(
        default=None,
        description="Agent type for this mind (e.g. 'elena-code', 'claude-mind'). "
        "Used by mind deploy to determine the agent type when --agent-type is not provided on the CLI.",
    )
    watchers: WatcherSettings = Field(
        default_factory=WatcherSettings,
        description="Watcher settings ([watchers] section).",
    )
