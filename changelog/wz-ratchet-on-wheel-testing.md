Add the `exclude = ["*_test.py", "test_*.py", "**/conftest.py"]` line under `[tool.hatch.build.targets.wheel]` to all remaining workspace packages that were missing it (18 packages across `apps/` and `libs/`). Without this, hatchling includes every `_test.py` and `conftest.py` in the published wheel.

Add a meta ratchet (`test_every_project_excludes_tests_from_wheel` in `test_meta_ratchets.py`) that fails if any new project regresses on this hygiene rule.
