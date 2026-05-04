"""``minds run``: spawn ``mngr forward`` and serve the bare-origin minds UI.

Replaces the deleted ``desktop_client/runner.py``. The auth + subdomain-
forwarding logic lives in the ``mngr_forward`` plugin now; this command:

1. Spawns ``mngr forward --service system_interface --preauth-cookie ...`` as
   a subprocess via ``EnvelopeStreamConsumer`` (which feeds the surviving
   ``MngrCliBackendResolver`` from the plugin's envelope stream).
2. Registers minds' ``LocalAgentDiscoveryHandler`` on the consumer so local
   agents still get their ``minds_api_url`` files written and stored
   Cloudflare tunnel tokens get re-injected on (re-)discovery.
3. Registers ``MindsApiUrlWriter`` on the consumer's
   ``reverse_tunnel_established`` callback so remote agents get their
   ``minds_api_url`` written after each tunnel (re-)establishment.
4. Builds the slimmed minds-side bare-origin FastAPI app and runs it on
   ``--port`` (default 8420).
5. Emits a ``mngr_forward_started`` JSONL event on stdout carrying the
   preauth cookie value, so the Electron shell can pre-set
   ``mngr_forward_session=<value>`` on ``localhost:<mngr-forward-port>``
   before the first agent-subdomain navigation.
"""

import os
import secrets
import threading
import webbrowser
from pathlib import Path
from typing import Final

import click
import uvicorn
from loguru import logger

from imbue.concurrency_group.concurrency_group import ConcurrencyGroup
from imbue.minds.bootstrap import minds_data_dir_for
from imbue.minds.bootstrap import resolve_minds_root_name
from imbue.minds.config.data_types import DEFAULT_DESKTOP_CLIENT_HOST
from imbue.minds.config.data_types import DEFAULT_DESKTOP_CLIENT_PORT
from imbue.minds.config.data_types import WorkspacePaths
from imbue.minds.desktop_client.agent_creator import AgentCreator
from imbue.minds.desktop_client.app import create_desktop_client
from imbue.minds.desktop_client.auth import FileAuthStore
from imbue.minds.desktop_client.backend_resolver import MngrCliBackendResolver
from imbue.minds.desktop_client.forward_cli import ForwardSubprocessConfig
from imbue.minds.desktop_client.forward_cli import LocalAgentDiscoveryHandler
from imbue.minds.desktop_client.forward_cli import MindsApiUrlWriter
from imbue.minds.desktop_client.forward_cli import start_mngr_forward
from imbue.minds.desktop_client.imbue_cloud_cli import ImbueCloudCli
from imbue.minds.desktop_client.latchkey.core import LATCHKEY_BINARY
from imbue.minds.desktop_client.latchkey.core import Latchkey
from imbue.minds.desktop_client.latchkey.core import LatchkeyDestructionHandler
from imbue.minds.desktop_client.latchkey.core import LatchkeyDiscoveryHandler
from imbue.minds.desktop_client.latchkey.core import LatchkeyReconcileCallback
from imbue.minds.desktop_client.latchkey.permissions import LatchkeyPermissionGrantHandler
from imbue.minds.desktop_client.latchkey.permissions import MngrMessageSender
from imbue.minds.desktop_client.latchkey.services_catalog import LatchkeyServicesCatalogError
from imbue.minds.desktop_client.latchkey.services_catalog import ServicePermissionInfo
from imbue.minds.desktop_client.latchkey.services_catalog import load_services_catalog
from imbue.minds.desktop_client.minds_config import MindsConfig
from imbue.minds.desktop_client.notification import NotificationDispatcher
from imbue.minds.desktop_client.request_events import RequestInbox
from imbue.minds.desktop_client.request_events import load_response_events
from imbue.minds.desktop_client.session_store import MultiAccountSessionStore
from imbue.minds.desktop_client.sharing_handler import SharingRequestHandler
from imbue.minds.desktop_client.ssh_tunnel import SSHTunnelManager
from imbue.minds.primitives import OneTimeCode
from imbue.minds.primitives import OutputFormat
from imbue.minds.telegram.setup import TelegramSetupOrchestrator
from imbue.minds.utils.output import emit_event

_DEFAULT_MNGR_FORWARD_PORT: Final[int] = 8421


@click.command()
@click.option(
    "--host",
    default=DEFAULT_DESKTOP_CLIENT_HOST,
    show_default=True,
    help="Host to bind the minds bare-origin server to",
)
@click.option(
    "--port",
    default=DEFAULT_DESKTOP_CLIENT_PORT,
    show_default=True,
    help="Port to bind the minds bare-origin server to",
)
@click.option(
    "--mngr-forward-port",
    default=_DEFAULT_MNGR_FORWARD_PORT,
    show_default=True,
    help="Port to bind the spawned `mngr forward` subprocess to",
)
@click.option(
    "--no-browser",
    is_flag=True,
    default=False,
    help="Do not open the minds UI in the system browser",
)
@click.pass_context
def run(
    ctx: click.Context,
    host: str,
    port: int,
    mngr_forward_port: int,
    no_browser: bool,
) -> None:
    # noqa: PLR0913 — flag count matches the legacy `minds forward` interface
    """Run the minds bare-origin server with `mngr forward` as a subprocess."""
    root_name = resolve_minds_root_name()
    data_directory = minds_data_dir_for(root_name)
    minds_config = MindsConfig(data_dir=data_directory)
    output_format: OutputFormat = ctx.obj.get("output_format", OutputFormat.HUMAN)

    logger.info("Starting `minds run`...")
    logger.info("  Bare-origin: http://{}:{}", host, port)
    logger.info("  mngr forward: http://127.0.0.1:{}", mngr_forward_port)
    logger.info("  MINDS_ROOT_NAME: {}", root_name)
    logger.info("  Data directory: {}", data_directory)
    logger.info("  remote_service_connector_url: {}", minds_config.remote_service_connector_url)

    paths = WorkspacePaths(data_dir=data_directory)
    auth_store = FileAuthStore(data_directory=paths.auth_dir)
    is_electron = os.getenv("MINDS_ELECTRON") == "1"
    notification_dispatcher = NotificationDispatcher(is_electron=is_electron)
    backend_resolver = MngrCliBackendResolver()
    tunnel_manager = SSHTunnelManager()
    latchkey = _build_latchkey(data_directory=data_directory)
    latchkey.initialize(data_dir=data_directory)

    root_concurrency_group = ConcurrencyGroup(name="minds-run")
    root_concurrency_group.__enter__()

    latchkey_permission_handler = LatchkeyPermissionGrantHandler(
        data_dir=data_directory,
        latchkey=latchkey,
        services_catalog=_try_load_latchkey_services_catalog(),
        mngr_message_sender=MngrMessageSender(),
    )
    imbue_cloud_cli = ImbueCloudCli(parent_concurrency_group=root_concurrency_group)
    agent_creator = AgentCreator(
        paths=paths,
        server_port=port,
        latchkey=latchkey,
        imbue_cloud_cli=imbue_cloud_cli,
        root_concurrency_group=root_concurrency_group,
        notification_dispatcher=notification_dispatcher,
    )
    telegram_orchestrator = TelegramSetupOrchestrator(paths=paths)
    session_store = MultiAccountSessionStore(data_dir=data_directory)
    sharing_request_handler = SharingRequestHandler(session_store=session_store)
    response_events = load_response_events(data_directory)
    request_inbox = RequestInbox()
    for resp in response_events:
        request_inbox = request_inbox.add_response(resp)

    # Spawn the plugin and attach the envelope consumer that feeds the
    # surviving resolver from the plugin's stdout stream.
    mngr_host_dir_str = os.environ.get("MNGR_HOST_DIR")
    mngr_host_dir = Path(mngr_host_dir_str).expanduser() if mngr_host_dir_str else (Path.home() / ".mngr")
    forward_config = ForwardSubprocessConfig(
        port=mngr_forward_port,
        reverse_specs=(f"0:{port}",),
        mngr_host_dir=mngr_host_dir,
    )
    consumer, preauth_cookie = start_mngr_forward(
        config=forward_config,
        resolver=backend_resolver,
        notification_dispatcher=notification_dispatcher,
    )

    # Local-agent ``minds_api_url`` writes + Cloudflare token re-injection.
    consumer.add_on_agent_discovered_callback(
        LocalAgentDiscoveryHandler(
            minds_api_port=port,
            data_dir=data_directory,
            mngr_host_dir=mngr_host_dir,
        )
    )
    # Remote-agent ``minds_api_url`` writes happen via the plugin's
    # reverse_tunnel_established envelope.
    consumer.add_on_reverse_tunnel_established_callback(MindsApiUrlWriter(resolver=backend_resolver))
    # Latchkey gateway lifecycle (separate spec migrates this to the plugin).
    latchkey_discovery_handler = LatchkeyDiscoveryHandler(latchkey=latchkey, tunnel_manager=tunnel_manager)
    latchkey_destruction_handler = LatchkeyDestructionHandler(latchkey=latchkey)
    consumer.add_on_agent_discovered_callback(latchkey_discovery_handler)
    consumer.add_on_agent_destroyed_callback(latchkey_destruction_handler)
    reconcile_callback = LatchkeyReconcileCallback(latchkey=latchkey, resolver=backend_resolver)
    backend_resolver.add_on_change_callback(reconcile_callback)
    tunnel_manager.start_reverse_tunnel_health_check()

    # All callbacks registered -- now safe to start the envelope reader
    # threads. Doing this earlier (e.g. inside ``start_mngr_forward``)
    # would open a race window where envelopes arriving before the
    # callbacks were registered would be dispatched against an empty
    # callback list and silently dropped.
    consumer.start(root_concurrency_group)

    # Emit the started event so Electron can pre-set the cookie before the
    # first navigation. ``minds run`` itself does not open the browser at
    # the agent subdomain — it opens the minds bare-origin URL.
    emit_event(
        "mngr_forward_started",
        {
            "preauth_cookie": preauth_cookie,
            "mngr_forward_port": mngr_forward_port,
        },
        output_format,
    )

    # Mint a one-time code for the minds bare-origin auth flow (the plugin
    # uses its own ``mngr_forward_session`` cookie on the agent subdomains).
    code = OneTimeCode(secrets.token_urlsafe(32))
    auth_store.add_one_time_code(code=code)
    minds_login_url = f"http://localhost:{port}/login?one_time_code={code}"
    logger.info("Minds login URL (one-time use): {}", minds_login_url)
    emit_event("login_url", {"login_url": minds_login_url, "message": minds_login_url}, output_format)

    app = create_desktop_client(
        auth_store=auth_store,
        backend_resolver=backend_resolver,
        http_client=None,
        tunnel_manager=tunnel_manager,
        latchkey=latchkey,
        agent_creator=agent_creator,
        imbue_cloud_cli=imbue_cloud_cli,
        telegram_orchestrator=telegram_orchestrator,
        notification_dispatcher=notification_dispatcher,
        paths=paths,
        envelope_stream_consumer=consumer,
        session_store=session_store,
        minds_config=minds_config,
        request_inbox=request_inbox,
        request_event_handlers=(latchkey_permission_handler, sharing_request_handler),
        server_port=port,
        output_format=output_format,
        root_concurrency_group=root_concurrency_group,
    )

    if not no_browser:
        thread = threading.Thread(target=_sleep_then_open, args=(f"http://{host}:{port}/",), daemon=True)
        thread.start()

    try:
        uvicorn.run(app, host=host, port=port, timeout_graceful_shutdown=1)
    finally:
        consumer.terminate()
        tunnel_manager.cleanup()


def _try_load_latchkey_services_catalog() -> dict[str, ServicePermissionInfo]:
    try:
        return load_services_catalog()
    except LatchkeyServicesCatalogError as e:
        logger.warning("Could not load latchkey services catalog; permission dialogs disabled: {}", e)
        return {}


def _build_latchkey(data_directory: Path) -> Latchkey:
    binary_override = os.environ.get("MINDS_LATCHKEY_BINARY")
    latchkey_binary = binary_override if binary_override else LATCHKEY_BINARY
    directory_override = os.environ.get("MINDS_LATCHKEY_DIRECTORY")
    latchkey_directory: Path | None
    if directory_override:
        latchkey_directory = Path(directory_override).expanduser()
    else:
        latchkey_directory = data_directory / "latchkey"
    return Latchkey(latchkey_binary=latchkey_binary, latchkey_directory=latchkey_directory)


def _sleep_then_open(url: str, delay: float = 1.0) -> None:
    """Wait ``delay`` seconds before opening ``url`` in the system browser.

    Uses ``threading.Event().wait`` instead of ``time.sleep`` so we honor
    the project ratchet against ``time.sleep``.
    """
    threading.Event().wait(timeout=delay)
    webbrowser.open(url)
