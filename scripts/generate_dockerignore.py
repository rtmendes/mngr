"""Generate .dockerignore from .gitignore.

.dockerignore and .gitignore have slightly different semantics for bare names:
in .gitignore, `foo` matches at any depth; in .dockerignore, `foo` matches only
at root. We normalize by prefixing bare names with `**/`.

Usage:
    python scripts/generate_dockerignore.py          # write .dockerignore
    python scripts/generate_dockerignore.py --check  # exit 1 if stale
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GITIGNORE = REPO_ROOT / ".gitignore"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

HEADER = """\
# AUTO-GENERATED from .gitignore by scripts/generate_dockerignore.py
# Do not edit manually -- edit .gitignore instead, then run:
#   uv run python scripts/generate_dockerignore.py
#
# The Docker image only needs current.tar.gz; all other repo files are
# delivered inside the tarball. We exclude everything .gitignore excludes
# plus docker-specific entries at the bottom.
"""

# Patterns to add that are not in .gitignore (docker-specific).
DOCKER_EXTRA = """\

# Docker-specific (not in .gitignore)
.git/
"""

# Patterns from .gitignore that must NOT appear in .dockerignore because
# they are needed in the Docker build context.
EXCLUDE_PATTERNS = {
    "current.tar.gz",
}


def _is_bare_name(pattern: str) -> bool:
    """Return True if the pattern is a bare name (no directory separator).

    A bare name in .gitignore matches at any depth, but in .dockerignore it
    only matches at root. These need a **/ prefix.

    Trailing `/` doesn't count as a directory separator for this purpose --
    `foo/` is still a bare name that should match at any depth.
    """
    stripped = pattern.rstrip("/")
    return "/" not in stripped


def transform_line(line: str) -> str | None:
    """Transform a single .gitignore line to .dockerignore format.

    Returns None if the line should be excluded from .dockerignore.
    """
    # Preserve blank lines and comments as-is.
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return line.rstrip()

    # Check if this pattern should be excluded.
    clean = stripped.lstrip("!")
    if clean in EXCLUDE_PATTERNS:
        return None

    # Handle negation: transform the inner pattern, then re-add `!`.
    negated = stripped.startswith("!")
    pattern = stripped[1:] if negated else stripped

    # Strip leading `/` -- in .gitignore it means root-only, which is already
    # the default behavior in .dockerignore for patterns containing `/`.
    pattern = pattern.lstrip("/")

    # Prefix bare names with `**/` so they match at any depth.
    if _is_bare_name(pattern) and not pattern.startswith("**/"):
        pattern = f"**/{pattern}"

    return f"!{pattern}" if negated else pattern


def generate() -> str:
    """Generate .dockerignore content from .gitignore."""
    lines = GITIGNORE.read_text().splitlines()
    out = [HEADER]
    for line in lines:
        transformed = transform_line(line)
        if transformed is not None:
            out.append(transformed)
    out.append(DOCKER_EXTRA)
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    expected = generate()

    if args.check:
        if not DOCKERIGNORE.exists():
            print(".dockerignore does not exist", file=sys.stderr)
            sys.exit(1)
        actual = DOCKERIGNORE.read_text()
        if actual != expected:
            print(
                ".dockerignore is stale -- run: uv run python scripts/generate_dockerignore.py",
                file=sys.stderr,
            )
            sys.exit(1)
        sys.exit(0)

    DOCKERIGNORE.write_text(expected)


if __name__ == "__main__":
    main()
