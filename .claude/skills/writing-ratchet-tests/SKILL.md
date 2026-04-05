---
name: writing-ratchet-tests
description: Write ratchet tests to prevent accumulation of code anti-patterns. Use when asked to create a "ratchet test" for tracking and preventing specific code patterns (e.g., TODO comments, inline imports, broad exception handling).
---

# Writing Ratchet Tests

This skill provides guidelines for writing ratchet tests that prevent accumulation of code anti-patterns across all projects.

## What are Ratchet Tests?

Ratchet tests track the current count of a specific anti-pattern in the codebase. The count can only stay the same or decrease -- increasing it fails the test. They use inline-snapshot to store the current violation count.

## Architecture

The ratchet system has three layers:

1. **Rule definitions** in `libs/imbue_common/imbue/imbue_common/ratchet_testing/common_ratchets.py` -- `RegexRatchetRule` and `RatchetRuleInfo` objects
2. **Wrapper functions** in `libs/imbue_common/imbue/imbue_common/ratchet_testing/standard_ratchet_checks.py` -- one function per ratchet rule
3. **Test functions** in each project's `test_ratchets.py` -- call the wrapper with a snapshot count

All projects must have the same set of test functions (enforced by `test_meta_ratchets.py`).

## Adding a New Common Ratchet

### Step 1: Define the Rule

Add a `RegexRatchetRule` to `common_ratchets.py`:

```python
PREVENT_MY_PATTERN = RegexRatchetRule(
    rule_name="my pattern usages",
    rule_description="Explain why this pattern is problematic and what to do instead",
    pattern_string=r"my_regex_pattern",
    is_multiline=False,  # set True if using ^ or $ anchors
)
```

Or a `RatchetRuleInfo` for AST-based checks (add the detection function to `ratchets.py`).

### Step 2: Add a Wrapper Function

Add to `standard_ratchet_checks.py`:

```python
def check_my_pattern(source_dir: Path, max_count: int) -> None:
    assert_ratchet(PREVENT_MY_PATTERN, source_dir, max_count)
```

Remember to import the rule at the top of the file.

### Step 3: Add the Test to ONE Project

Add the test function to any one project's `test_ratchets.py`, in the appropriate section:

```python
def test_prevent_my_pattern() -> None:
    rc.check_my_pattern(_DIR, snapshot(0))
```

### Step 4: Sync to All Projects

```bash
uv run python scripts/sync_common_ratchets.py
```

This propagates the test to all other `test_ratchets.py` files with `snapshot(0)`.

### Step 5: Set Actual Counts

```bash
uv run pytest --inline-snapshot=update -k test_ratchets
```

This updates each project's snapshot with the actual violation count.

## Important Rules

- **Never add per-project code quality ratchets to `test_meta_ratchets.py`**. Meta ratchets are for repo-wide structural checks only. Use the sync script instead.
- Keep test function names descriptive: `test_prevent_<anti_pattern>`
- Place tests in the correct section (Code safety, Exception handling, Import style, etc.)
- Provide clear `rule_description` that explains WHY the pattern is bad and WHAT to do instead
- Never blindly update snapshots -- investigate why a count increased

## Troubleshooting

**Ratchet test fails after your code change:**
- Read the `rule_description` to understand why
- Fix your code to avoid the anti-pattern
- Never run `--inline-snapshot=fix` to paper over violations

**Pattern not matching expected violations:**
- Check if `is_multiline=True` is needed for patterns using `^` or `$`
- Verify the regex is correct
- Check that violations are in git-tracked `.py` files
