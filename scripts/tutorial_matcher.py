#!/usr/bin/env python3
"""Find unmatched blocks between a tutorial shell script and its pytest test directory.

Usage: python scripts/tutorial_matcher.py <script_file> <test_directory>

The script file is a shell script split into "blocks" by empty lines. The test
directory contains pytest functions that reference blocks via write_tutorial_block()
calls or docstrings. This script identifies blocks without tests and tests without
blocks.

Matching is purely text-based: no AST walking. A function is identified by a line
starting with "def test_", and its body is all subsequent indented lines. The block
text is extracted from either a write_tutorial_block(\"\"\"...\"\"\") call or a
docstring, dedented, and compared against the script blocks.
"""

import re
import sys
import textwrap
from pathlib import Path


def parse_script_blocks(script_path: Path) -> list[str]:
    """Parse a shell script into command blocks, filtering out shebangs and comment-only blocks."""
    content = script_path.read_text()
    raw_blocks = content.split("\n\n")

    blocks: list[str] = []
    for i, block in enumerate(raw_blocks):
        stripped = block.strip()
        if not stripped:
            continue
        # Discard the first block if it starts with a shebang.
        if i == 0 and stripped.startswith("#!"):
            continue
        # Discard blocks where every line is empty or a comment.
        lines = stripped.splitlines()
        if all(line.strip() == "" or line.strip().startswith("#") for line in lines):
            continue
        blocks.append(stripped)

    return blocks


def _parse_test_functions(source: str) -> list[tuple[str, str]]:
    """Parse test functions from Python source using simple text heuristics.

    Returns list of (signature, body) tuples where body is the full indented
    text of the function body.
    """
    lines = source.splitlines()
    functions: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Look for "def test_..." at any indentation level
        stripped = line.lstrip()
        if not stripped.startswith("def test_"):
            i += 1
            continue

        # Collect the full signature (may span multiple lines)
        sig_lines = [line]
        # If the line doesn't have both ')' and ':', it continues
        while i + 1 < len(lines) and (")" not in sig_lines[-1] or ":" not in sig_lines[-1]):
            i += 1
            sig_lines.append(lines[i])
        signature = "\n".join(sig_lines)
        i += 1

        # Determine the body indentation (first non-empty line after signature)
        body_lines: list[str] = []
        while i < len(lines):
            if lines[i].strip() == "":
                body_lines.append("")
                i += 1
                continue
            # Check if this line is indented more than the def line
            if lines[i][0] in (" ", "\t"):
                body_lines.append(lines[i])
                i += 1
            else:
                break

        body = "\n".join(body_lines)
        functions.append((signature, body))

    return functions


def _extract_block_text(body: str) -> str | None:
    """Extract tutorial block text from a function body.

    Looks for write_tutorial_block(\"\"\"...\"\"\") first, then falls back to
    a docstring (\"\"\"...\"\"\"). In both cases, the content is dedented and
    stripped.
    """
    # Try write_tutorial_block("""...""") -- match the triple-quoted string argument
    m = re.search(r'write_tutorial_block\(\s*"""(.*?)"""\s*\)', body, re.DOTALL)
    if m:
        return textwrap.dedent(m.group(1)).strip()

    # Fall back to docstring: first triple-quoted string in the body
    m = re.search(r'"""(.*?)"""', body, re.DOTALL)
    if m:
        return textwrap.dedent(m.group(1)).strip()

    return None


def find_pytest_functions(test_dir: Path) -> list[tuple[str, str | None, Path]]:
    """Find all test functions in a directory.

    Returns (signature, block_text, file_path) tuples.
    """
    results: list[tuple[str, str | None, Path]] = []

    for py_file in sorted(test_dir.rglob("*.py")):
        if py_file.name == "conftest.py" or py_file.name == "serve_test_output.py":
            continue
        source = py_file.read_text()
        for signature, body in _parse_test_functions(source):
            block_text = _extract_block_text(body)
            results.append((signature, block_text, py_file))

    return results


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <script_file> <test_directory>", file=sys.stderr)
        sys.exit(1)

    script_path = Path(sys.argv[1])
    test_dir = Path(sys.argv[2])

    if not script_path.is_file():
        print(f"Error: {script_path} is not a file", file=sys.stderr)
        sys.exit(1)
    if not test_dir.is_dir():
        print(f"Error: {test_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    blocks = parse_script_blocks(script_path)
    pytest_funcs = find_pytest_functions(test_dir)

    # Find blocks with no corresponding pytest function.
    unmatched_blocks: list[str] = []
    for block in blocks:
        has_match = any(text is not None and block in text for _, text, _ in pytest_funcs)
        if not has_match:
            unmatched_blocks.append(block)

    # Find pytest functions with no corresponding block.
    unmatched_funcs: list[tuple[str, str | None, Path]] = []
    for signature, text, file_path in pytest_funcs:
        if text is None:
            unmatched_funcs.append((signature, text, file_path))
            continue
        has_match = any(block in text for block in blocks)
        if not has_match:
            unmatched_funcs.append((signature, text, file_path))

    # Output results.
    if not unmatched_blocks and not unmatched_funcs:
        print("All script blocks have corresponding pytest functions and vice versa.")
        sys.exit(0)

    if unmatched_blocks:
        print("The following script blocks don't have corresponding pytest functions:\n")
        for block in unmatched_blocks:
            print(f"```\n{block}\n```\n")

    if unmatched_funcs:
        print("The following pytest functions don't correspond to any script block:\n")
        for signature, text, file_path in unmatched_funcs:
            print(f"```\n# {file_path}\n{signature}")
            if text is not None:
                indented = textwrap.indent(text, "    ")
                print(f"    # extracted block text:\n{indented}")
            print("```\n")

    sys.exit(1)


if __name__ == "__main__":
    main()
