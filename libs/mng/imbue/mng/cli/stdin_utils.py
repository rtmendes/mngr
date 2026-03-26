import sys

from imbue.mng.errors import UserInputError

STDIN_PLACEHOLDER = "-"


def _read_identifiers_from_stdin() -> list[str]:
    """Read identifiers from stdin, one per line.

    Strips whitespace from each line and skips empty lines.
    """
    identifiers: list[str] = []
    for line in sys.stdin:
        stripped = line.strip()
        if stripped:
            identifiers.append(stripped)
    return identifiers


def expand_stdin_placeholder(identifiers: tuple[str, ...]) -> list[str]:
    """Expand the '-' stdin placeholder in a sequence of identifiers.

    If '-' appears in identifiers, it is replaced with newline-separated
    values read from stdin. Other identifiers are preserved as-is.

    Raises UserInputError if '-' appears more than once, or if '-' is
    specified but stdin is a TTY (no piped input).
    """
    dash_count = identifiers.count(STDIN_PLACEHOLDER)
    if dash_count == 0:
        return list(identifiers)
    if dash_count > 1:
        raise UserInputError("'-' can only be specified once (stdin can only be consumed once)")
    if sys.stdin.isatty():
        raise UserInputError("'-' requires piped input (stdin is a TTY)")

    stdin_values = _read_identifiers_from_stdin()
    result: list[str] = []
    for identifier in identifiers:
        if identifier == STDIN_PLACEHOLDER:
            result.extend(stdin_values)
        else:
            result.append(identifier)
    return result


def resolve_stdin_placeholder(identifier: str | None) -> str | None:
    """Resolve the '-' stdin placeholder for single-target commands.

    If identifier is '-', reads a single non-empty line from stdin.
    Returns the identifier unchanged otherwise, or None if identifier is None.

    Raises UserInputError if '-' is specified but stdin is a TTY, or if
    stdin contains no non-empty lines.
    """
    if identifier is None or identifier != STDIN_PLACEHOLDER:
        return identifier
    if sys.stdin.isatty():
        raise UserInputError("'-' requires piped input (stdin is a TTY)")
    for line in sys.stdin:
        stripped = line.strip()
        if stripped:
            return stripped
    raise UserInputError("'-' was specified but stdin is empty")
