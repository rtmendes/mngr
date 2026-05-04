"""Per-agent reverse-tunnel setup driven by ``--reverse <remote>:<local>``.

For every agent discovered with SSH info, opens each configured reverse
tunnel pair and emits a ``forward.reverse_tunnel_established`` envelope. The
underlying ``SSHTunnelManager`` health-checks tunnels every ~30s and
re-establishes any that go stale; the repair callback re-emits the same
envelope (with a possibly-different remote port if sshd reassigned one).
"""

from collections.abc import Sequence

import paramiko
from loguru import logger
from pydantic import Field

from imbue.imbue_common.mutable_model import MutableModel
from imbue.imbue_common.primitives import PositiveInt
from imbue.mngr.primitives import AgentId
from imbue.mngr_forward.data_types import ReverseTunnelEstablishedPayload
from imbue.mngr_forward.envelope import EnvelopeWriter
from imbue.mngr_forward.primitives import ReverseTunnelSpec
from imbue.mngr_forward.ssh_tunnel import RemoteSSHInfo
from imbue.mngr_forward.ssh_tunnel import ReverseTunnelInfo
from imbue.mngr_forward.ssh_tunnel import SSHTunnelError
from imbue.mngr_forward.ssh_tunnel import SSHTunnelManager


class ReverseTunnelHandler(MutableModel):
    """``on_agent_discovered`` callback that maintains per-agent reverse tunnels."""

    tunnel_manager: SSHTunnelManager = Field(frozen=True, description="Underlying SSH tunnel manager")
    envelope_writer: EnvelopeWriter = Field(frozen=True, description="Where envelope events are emitted")
    specs: tuple[ReverseTunnelSpec, ...] = Field(
        frozen=True,
        description="One reverse tunnel pair per --reverse <remote>:<local>",
    )

    def model_post_init(self, __context: object) -> None:
        if self.specs:
            self.tunnel_manager.add_on_tunnel_repaired_callback(self._on_tunnel_repaired)

    def __call__(
        self,
        agent_id: AgentId,
        ssh_info: RemoteSSHInfo | None,
        provider_name: str,
    ) -> None:
        del provider_name
        if ssh_info is None or not self.specs:
            return
        for spec in self.specs:
            self._setup_one(agent_id, ssh_info, spec)

    def setup_for_snapshot(
        self,
        agents_with_ssh: Sequence[tuple[AgentId, RemoteSSHInfo]],
    ) -> None:
        """Set up reverse tunnels for a fixed snapshot of agents (--no-observe mode)."""
        if not self.specs:
            return
        for agent_id, ssh_info in agents_with_ssh:
            for spec in self.specs:
                self._setup_one(agent_id, ssh_info, spec)

    def _setup_one(
        self,
        agent_id: AgentId,
        ssh_info: RemoteSSHInfo,
        spec: ReverseTunnelSpec,
    ) -> None:
        try:
            assigned_remote_port = self.tunnel_manager.setup_reverse_tunnel(
                ssh_info=ssh_info,
                local_port=spec.local_port,
                remote_port=spec.remote_port,
            )
        except (SSHTunnelError, OSError, paramiko.SSHException) as e:
            logger.warning(
                "Failed to set up reverse tunnel for agent {} ({}:{}): {}",
                agent_id,
                spec.remote_port,
                spec.local_port,
                e,
            )
            return
        self.envelope_writer.emit_reverse_tunnel_established(
            ReverseTunnelEstablishedPayload(
                agent_id=agent_id,
                remote_port=PositiveInt(assigned_remote_port),
                local_port=spec.local_port,
                ssh_host=ssh_info.host,
                ssh_port=PositiveInt(ssh_info.port),
            )
        )

    def _on_tunnel_repaired(self, info: ReverseTunnelInfo) -> None:
        # The plugin emits one envelope per repaired tunnel. We don't know
        # which agent the tunnel belongs to (multiple agents can share an
        # SSH host); fan out one envelope per agent_state_dir tracked. If
        # no agent_state_dirs were registered (the plugin's normal path),
        # we still emit one envelope tagged with a synthesized agent id of
        # the local port string so consumers can at least detect the
        # repair.
        if info.agent_state_dirs:
            for state_dir in info.agent_state_dirs:
                agent_id = self._agent_id_from_state_dir(state_dir)
                if agent_id is None:
                    continue
                self._emit_repaired(agent_id, info)
        else:
            logger.debug(
                "Reverse tunnel repaired (host={}, local={}, remote={}); no agent_state_dir tracked",
                info.ssh_info.host,
                info.local_port,
                info.remote_port,
            )

    def _emit_repaired(self, agent_id: AgentId, info: ReverseTunnelInfo) -> None:
        self.envelope_writer.emit_reverse_tunnel_established(
            ReverseTunnelEstablishedPayload(
                agent_id=agent_id,
                remote_port=PositiveInt(info.remote_port),
                local_port=PositiveInt(info.local_port),
                ssh_host=info.ssh_info.host,
                ssh_port=PositiveInt(info.ssh_info.port),
            )
        )

    @staticmethod
    def _agent_id_from_state_dir(state_dir: str) -> AgentId | None:
        # State dirs follow ``<host_dir>/agents/<agent-id>``; strip the
        # trailing directory component if present.
        if "/" not in state_dir:
            return None
        last = state_dir.rstrip("/").rsplit("/", maxsplit=1)[-1]
        try:
            return AgentId(last)
        except ValueError:
            return None
