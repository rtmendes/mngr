"""llm plugin that provides an echo model for testing.

The echo model returns a configurable response for any input.
By default it echoes back the user's message with a prefix.

Response behavior can be customized via:
- LLM_ECHO_RESPONSE env var: if set, always return this exact string
- LLM_ECHO_RESPONSES_FILE env var: path to a JSON file mapping
  input substrings to responses. If the user's message contains a key,
  the corresponding value is returned. Falls back to the default
  echo behavior if no key matches.

The responses file format is:
    {
        "hello": "Hello! I am the echo model.",
        "help": "I am a test model that echoes responses."
    }
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path

import llm


class EchoModel(llm.Model):
    """A test model that returns predictable responses.

    Useful for end-to-end testing of systems that use llm without
    requiring real API keys or network access.
    """

    model_id = "echo"
    can_stream = True

    def execute(
        self,
        prompt: llm.Prompt,
        stream: bool,
        response: llm.Response,
        conversation: llm.Conversation | None = None,
    ) -> Iterator[str]:
        user_message = prompt.prompt or ""

        reply = _resolve_response(user_message)

        response.set_usage(
            input=len(user_message.split()),
            output=len(reply.split()),
        )

        yield reply


def _resolve_response(user_message: str) -> str:
    """Determine the response to return for a given user message.

    Checks (in order):
    1. LLM_ECHO_RESPONSE env var (static response for all inputs)
    2. LLM_ECHO_RESPONSES_FILE env var (substring-matched mapping)
    3. Default: "Echo: <user_message>"
    """
    static_response = os.environ.get("LLM_ECHO_RESPONSE")
    if static_response is not None:
        return static_response

    responses_file = os.environ.get("LLM_ECHO_RESPONSES_FILE")
    if responses_file is not None:
        file_path = Path(responses_file)
        if file_path.exists():
            mapping = json.loads(file_path.read_text())
            for substring, mapped_response in mapping.items():
                if substring in user_message:
                    return mapped_response

    if not user_message:
        return "Echo: (empty message)"

    return "Echo: " + user_message


@llm.hookimpl
def register_models(register):  # type: ignore[no-untyped-def]
    register(EchoModel())
