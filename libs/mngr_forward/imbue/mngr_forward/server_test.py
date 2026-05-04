"""Bare-origin and subdomain-routing tests for the FastAPI app.

The middleware and forwarding handlers depend on real network I/O
(``httpx`` / paramiko); those paths are exercised via the acceptance
test, not here. This file covers the deterministic auth + routing
surfaces using ``starlette.testclient.TestClient``.
"""

import io
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from imbue.mngr_forward.auth import FileAuthStore
from imbue.mngr_forward.cookie import create_session_cookie
from imbue.mngr_forward.data_types import ForwardServiceStrategy
from imbue.mngr_forward.envelope import EnvelopeWriter
from imbue.mngr_forward.primitives import MNGR_FORWARD_SESSION_COOKIE_NAME
from imbue.mngr_forward.primitives import OneTimeCode
from imbue.mngr_forward.resolver import ForwardResolver
from imbue.mngr_forward.server import create_forward_app
from imbue.mngr_forward.ssh_tunnel import SSHTunnelManager


@pytest.fixture
def app_setup(tmp_path: Path) -> tuple[TestClient, FileAuthStore, ForwardResolver]:
    auth_store = FileAuthStore(data_directory=tmp_path)
    resolver = ForwardResolver(strategy=ForwardServiceStrategy(service_name="system_interface"))
    tunnel_manager = SSHTunnelManager()
    envelope_writer = EnvelopeWriter(output=io.StringIO())
    app = create_forward_app(
        auth_store=auth_store,
        resolver=resolver,
        tunnel_manager=tunnel_manager,
        envelope_writer=envelope_writer,
        listen_host="127.0.0.1",
        listen_port=18421,
    )
    client = TestClient(app, follow_redirects=False)
    return client, auth_store, resolver


def test_bare_origin_unauthenticated_returns_login_page(
    app_setup: tuple[TestClient, FileAuthStore, ForwardResolver],
) -> None:
    client, _store, _resolver = app_setup
    response = client.get("/")
    assert response.status_code == 200
    assert "Sign in" in response.text


def test_login_url_redirect_renders_js_redirect_page(
    app_setup: tuple[TestClient, FileAuthStore, ForwardResolver],
) -> None:
    client, store, _resolver = app_setup
    code = OneTimeCode("test-code-12345")
    store.add_one_time_code(code=code)
    response = client.get(f"/login?one_time_code={code}")
    assert response.status_code == 200
    # The page is the JS-redirect shim; it must reference /authenticate.
    assert "/authenticate" in response.text


def test_authenticate_consumes_otp_and_sets_cookie(
    app_setup: tuple[TestClient, FileAuthStore, ForwardResolver],
) -> None:
    client, store, _resolver = app_setup
    code = OneTimeCode("auth-test-code-1")
    store.add_one_time_code(code=code)
    response = client.get(f"/authenticate?one_time_code={code}")
    assert response.status_code == 307
    assert response.headers["location"] == "/"
    assert MNGR_FORWARD_SESSION_COOKIE_NAME in response.cookies
    # Code is single-use: re-presenting it returns 403.
    response2 = client.get(f"/authenticate?one_time_code={code}")
    assert response2.status_code == 403


def test_invalid_otp_returns_403(
    app_setup: tuple[TestClient, FileAuthStore, ForwardResolver],
) -> None:
    client, _store, _resolver = app_setup
    response = client.get("/authenticate?one_time_code=never-issued")
    assert response.status_code == 403


def test_empty_otp_on_authenticate_returns_403_not_500(
    app_setup: tuple[TestClient, FileAuthStore, ForwardResolver],
) -> None:
    """Empty `?one_time_code=` must produce a clean 403, not a 500 from OneTimeCode validation."""
    client, _store, _resolver = app_setup
    response = client.get("/authenticate?one_time_code=")
    assert response.status_code == 403


def test_empty_otp_on_login_returns_403_not_500(
    app_setup: tuple[TestClient, FileAuthStore, ForwardResolver],
) -> None:
    """Empty `?one_time_code=` against /login must produce a clean 403, not a 500."""
    client, _store, _resolver = app_setup
    response = client.get("/login?one_time_code=")
    assert response.status_code == 403


def test_whitespace_otp_on_authenticate_returns_403_not_500(
    app_setup: tuple[TestClient, FileAuthStore, ForwardResolver],
) -> None:
    """Whitespace-only `?one_time_code=   ` must produce a clean 403, not a 500."""
    client, _store, _resolver = app_setup
    response = client.get("/authenticate?one_time_code=%20%20%20")
    assert response.status_code == 403


def test_bare_origin_authenticated_renders_debug_index(
    app_setup: tuple[TestClient, FileAuthStore, ForwardResolver],
) -> None:
    client, store, _resolver = app_setup
    cookie = create_session_cookie(store.get_signing_key())
    response = client.get("/", cookies={MNGR_FORWARD_SESSION_COOKIE_NAME: cookie})
    assert response.status_code == 200
    assert "Discovered agents" in response.text


def test_goto_unauthenticated_redirects_to_root(
    app_setup: tuple[TestClient, FileAuthStore, ForwardResolver],
) -> None:
    client, _store, _resolver = app_setup
    response = client.get("/goto/agent-deadbeef/")
    assert response.status_code == 302
    assert response.headers["location"] == "/"


def test_goto_authenticated_redirects_to_subdomain_with_token(
    app_setup: tuple[TestClient, FileAuthStore, ForwardResolver],
) -> None:
    client, store, _resolver = app_setup
    cookie = create_session_cookie(store.get_signing_key())
    # Use a 32-hex AgentId so the AgentId() validator accepts it.
    valid_agent_id = "agent-" + "0" * 31 + "a"
    response = client.get(
        f"/goto/{valid_agent_id}/",
        cookies={MNGR_FORWARD_SESSION_COOKIE_NAME: cookie},
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"http://{valid_agent_id}.localhost:18421/_subdomain_auth?token=")
    assert "next=%2F" in location


def test_preauth_cookie_short_circuit(tmp_path: Path) -> None:
    """A pre-shared cookie value is accepted without a signature check."""
    auth_store = FileAuthStore(data_directory=tmp_path)
    resolver = ForwardResolver(strategy=ForwardServiceStrategy(service_name="system_interface"))
    tunnel_manager = SSHTunnelManager()
    envelope_writer = EnvelopeWriter(output=io.StringIO())
    app = create_forward_app(
        auth_store=auth_store,
        resolver=resolver,
        tunnel_manager=tunnel_manager,
        envelope_writer=envelope_writer,
        listen_host="127.0.0.1",
        listen_port=18421,
        preauth_cookie_value="opaque-pre-shared-token",
    )
    client = TestClient(app, follow_redirects=False)
    response = client.get("/", cookies={MNGR_FORWARD_SESSION_COOKIE_NAME: "opaque-pre-shared-token"})
    assert response.status_code == 200
    assert "Discovered agents" in response.text
