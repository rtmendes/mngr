#!/usr/bin/env python3
"""Upsert Modal secrets from local ``.minds/<env>/<service>.sh`` files.

Each ``.sh`` file is shell-style: one ``export KEY=value`` (or plain
``KEY=value``) line per variable. Lines starting with ``#`` and blank lines
are ignored. The script uses ``bash -c 'source <file>; declare -p'`` to parse
the file the same way the shell would, so quoting and escapes behave exactly
as they do when you source the file yourself.

Given ``.minds/production/cloudflare.sh`` and ``.minds/production/supertokens.sh``,
this pushes two Modal secrets: ``cloudflare-production`` and
``supertokens-production``. Existing secrets are overwritten (``--force``).

Usage:
    uv run scripts/push_modal_secrets.py <env-name>
    uv run scripts/push_modal_secrets.py <env-name> --dir <dir>   # override .minds

Examples:
    uv run scripts/push_modal_secrets.py production
    uv run scripts/push_modal_secrets.py staging
"""

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


def _parse_env_file(path: Path) -> dict[str, str]:
    """Return the ``KEY=value`` pairs defined in a shell-style env file.

    Uses ``bash`` to source the file and dump the resulting environment as a
    null-delimited list so quoting, ``export`` prefixes, and variable
    interpolation all behave exactly as they do in a real shell.
    """
    if not path.is_file():
        raise FileNotFoundError(f"env file not found: {path}")
    script = f"set -a; . {shlex.quote(str(path))}; env -0"
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    baseline = subprocess.run(
        ["bash", "-c", "env -0"],
        capture_output=True,
        text=True,
        check=True,
    )
    before = _parse_env_dump(baseline.stdout)
    after = _parse_env_dump(result.stdout)
    # Drop empty values: a blank ``export KEY=`` line is how we signal "leave this
    # key unset on the server" without having to comment the line out.
    return {k: v for k, v in after.items() if before.get(k) != v and v}


def _parse_env_dump(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in raw.split("\0"):
        if not entry:
            continue
        key, sep, value = entry.partition("=")
        if not sep:
            continue
        result[key] = value
    return result


def _upsert_modal_secret(name: str, values: dict[str, str], is_dry_run: bool) -> None:
    """Create or overwrite a Modal secret with the given key/value pairs."""
    if not values:
        print(f"[skip] {name}: no non-empty KEY=VALUE pairs found", file=sys.stderr)
        return
    args = ["uv", "run", "modal", "secret", "create", "--force", name]
    for key, value in values.items():
        args.append(f"{key}={value}")
    printable = [args[i] if "=" not in args[i] else f"{args[i].split('=', 1)[0]}=***" for i in range(len(args))]
    print(f"[push] {name}: {len(values)} key(s)")
    print(f"       {' '.join(shlex.quote(p) for p in printable)}")
    if is_dry_run:
        return
    subprocess.run(args, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("env_name", help="Environment name (e.g. production, staging)")
    parser.add_argument(
        "--dir",
        default=".minds",
        help="Root directory holding <env>/<service>.sh files (default: .minds)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the Modal commands without executing them",
    )
    args = parser.parse_args()

    env_dir = Path(args.dir) / args.env_name
    if not env_dir.is_dir():
        print(f"error: directory not found: {env_dir}", file=sys.stderr)
        return 2

    sh_files = sorted(env_dir.glob("*.sh"))
    if not sh_files:
        print(f"error: no .sh files found in {env_dir}", file=sys.stderr)
        return 2

    for sh_file in sh_files:
        service_name = sh_file.stem
        secret_name = f"{service_name}-{args.env_name}"
        values = _parse_env_file(sh_file)
        _upsert_modal_secret(secret_name, values, is_dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
