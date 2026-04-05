from __future__ import annotations

from typing import Any
from typing import Final

from loguru import logger
from pydantic import Field

from imbue.mngr import hookimpl
from imbue.mngr.config.agent_class_registry import get_agent_class
from imbue.mngr.config.data_types import AgentTypeConfig
from imbue.mngr.config.data_types import MngrContext
from imbue.mngr.errors import MngrError
from imbue.mngr.errors import PluginMngrError
from imbue.mngr.interfaces.agent import AgentInterface
from imbue.mngr.interfaces.host import CreateAgentOptions
from imbue.mngr.interfaces.host import OnlineHostInterface
from imbue.mngr.primitives import CommandString
from imbue.mngr_claude.plugin import ClaudeAgent
from imbue.mngr_claude.plugin import ClaudeAgentConfig

# Extra tmux window names and commands.
BOOTSTRAP_WINDOW_NAME: Final[str] = "bootstrap"
BOOTSTRAP_COMMAND: Final[str] = "uv run bootstrap"

TELEGRAM_WINDOW_NAME: Final[str] = "telegram"
TELEGRAM_COMMAND: Final[str] = "uv run telegram-bot"


class ForeverClaudeConfig(ClaudeAgentConfig):
    """Config for the forever-claude agent type.

    A persistent Claude agent that runs continuously, communicates via Telegram,
    and manages its own services via a bootstrap service manager.
    """

    trust_working_directory: bool = Field(
        default=True,
        description="Automatically trust the agent's working directory. "
        "Enabled by default since forever-claude agents run in their own repo.",
    )
    model: str | None = Field(
        default="opus[1m]",
        description="Model to use for this agent.",
    )
    is_fast: bool = Field(
        default=True,
        description="Whether to enable fast mode for this agent.",
    )


class ForeverClaudeAgent(ClaudeAgent):
    """A persistent Claude agent that runs continuously.

    Extends ClaudeAgent with:
    - Telegram bot and bootstrap service manager injected as extra tmux windows
    - Env var validation for TELEGRAM_BOT_TOKEN and TELEGRAM_USER_NAME
    - bypassPermissionsModeAccepted set to True
    """

    agent_config: ForeverClaudeConfig = Field(frozen=True, repr=False, description="Agent type config")

    def on_before_provisioning(
        self,
        host: OnlineHostInterface,
        options: CreateAgentOptions,
        mngr_ctx: MngrContext,
    ) -> None:
        """Validate that required Telegram env vars are set."""
        super().on_before_provisioning(host, options, mngr_ctx)
        _validate_telegram_env_vars(options)

    def _build_per_agent_claude_json(
        self, options: CreateAgentOptions, config: ClaudeAgentConfig
    ) -> dict[str, Any]:
        data = super()._build_per_agent_claude_json(options, config)
        data["bypassPermissionsModeAccepted"] = True
        return data


def _validate_telegram_env_vars(options: CreateAgentOptions) -> None:
    """Validate that TELEGRAM_BOT_TOKEN and TELEGRAM_USER_NAME are available.

    Checks the agent's environment options (--env, --pass-env, .env file).
    Raises PluginMngrError with a clear message if either is missing.
    """
    env_var_names = {env_var.key for env_var in options.environment.env_vars}

    missing = []
    for required_var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_NAME"):
        if required_var not in env_var_names:
            missing.append(required_var)

    if missing:
        missing_str = ", ".join(missing)
        raise PluginMngrError(
            f"Missing required environment variable(s): {missing_str}\n"
            "The forever-claude agent type requires Telegram credentials.\n"
            "Provide them via --pass-env, --env, or a .env file in the project directory."
        )


def _inject_extra_windows(params: dict[str, Any]) -> None:
    """Inject bootstrap and telegram tmux windows into the create command parameters."""
    existing = params.get("extra_window", ())
    params["extra_window"] = (
        *existing,
        f'{BOOTSTRAP_WINDOW_NAME}="{BOOTSTRAP_COMMAND}"',
        f'{TELEGRAM_WINDOW_NAME}="{TELEGRAM_COMMAND}"',
    )


def _get_agent_type_from_params(params: dict[str, Any]) -> str | None:
    """Extract the agent type from create command parameters."""
    return params.get("type") or params.get("positional_agent_type")


def _is_forever_claude_agent_type(agent_type_name: str) -> bool:
    """Check whether the given agent type name resolves to a ForeverClaudeAgent subclass."""
    try:
        agent_class = get_agent_class(agent_type_name)
    except MngrError as e:
        logger.debug("Could not resolve agent type '{}': {}", agent_type_name, e)
        return False
    return issubclass(agent_class, ForeverClaudeAgent)


@hookimpl
def register_agent_type() -> tuple[str, type[AgentInterface], type[AgentTypeConfig]]:
    """Register the forever-claude agent type."""
    return ("forever-claude", ForeverClaudeAgent, ForeverClaudeConfig)


@hookimpl
def override_command_options(
    command_name: str,
    command_class: type,
    params: dict[str, Any],
) -> None:
    """Add bootstrap and telegram windows when creating forever-claude agents."""
    if command_name != "create":
        return

    agent_type = _get_agent_type_from_params(params)
    if agent_type is None:
        return

    if not _is_forever_claude_agent_type(agent_type):
        return

    _inject_extra_windows(params)
