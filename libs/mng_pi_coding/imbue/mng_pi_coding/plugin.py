from pydantic import Field

from imbue.mng import hookimpl
from imbue.mng.config.data_types import AgentTypeConfig
from imbue.mng.interfaces.agent import AgentInterface
from imbue.mng.primitives import CommandString


class PiCodingAgentConfig(AgentTypeConfig):
    """Config for the pi-coding agent type."""

    command: CommandString = Field(
        default=CommandString("pi"),
        description="Command to run the pi coding agent",
    )


@hookimpl
def register_agent_type() -> tuple[str, type[AgentInterface] | None, type[AgentTypeConfig]]:
    """Register the pi-coding agent type."""
    return ("pi-coding", None, PiCodingAgentConfig)
