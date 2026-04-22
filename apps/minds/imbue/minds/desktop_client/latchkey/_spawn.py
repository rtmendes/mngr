"""Private helper: spawn a detached ``latchkey gateway`` subprocess.

Why this file uses raw ``subprocess.Popen`` (triggering a narrow exclusion
from ``check_direct_subprocess``): we need the spawned process to *outlive*
the minds desktop client so agents running in containers/VMs can keep
making authenticated API calls across desktop-client restarts. That is the
exact opposite of what ``ConcurrencyGroup`` is built for -- it guarantees
that every spawned process is cleaned up when the group exits.

Confining the ``Popen`` call to this tiny helper keeps the ratchet
exception obvious and well-scoped. The rest of the latchkey package still
goes through ``ConcurrencyGroup`` for any managed subprocess work.
"""

import os
import subprocess
from pathlib import Path


def spawn_detached_latchkey_gateway(
    latchkey_binary: str,
    listen_host: str,
    listen_port: int,
    log_path: Path,
) -> int:
    """Start a detached ``latchkey gateway`` and return its PID.

    The child is placed in its own session (``setsid`` via
    ``start_new_session=True``) so it survives the caller's death. Its
    stdout/stderr are appended to ``log_path`` (the parent directory is
    created if needed). It reads listen host/port from the environment
    variables latchkey documents (``LATCHKEY_GATEWAY_LISTEN_*``).

    The returned ``Popen`` object is intentionally allowed to go out of
    scope. Python's ``subprocess`` module parks finished children on an
    internal ``_active`` list for zombie reaping, but never kills a
    still-running child during garbage collection, so the gateway keeps
    running until something explicitly terminates it.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["LATCHKEY_GATEWAY_LISTEN_HOST"] = listen_host
    env["LATCHKEY_GATEWAY_LISTEN_PORT"] = str(listen_port)

    log_file = log_path.open("ab")
    try:
        process = subprocess.Popen(
            [latchkey_binary, "gateway"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        # Our copy of the log file descriptor can be closed; the child
        # inherited its own dup via Popen's stdio setup.
        log_file.close()
    return process.pid
