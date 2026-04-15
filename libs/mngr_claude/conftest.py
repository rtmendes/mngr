"""Project-level conftest for mngr-claude.

When running tests from libs/mngr_claude/, this conftest provides the common pytest hooks
that would otherwise come from the monorepo root conftest.py (which is not discovered
when pytest runs from a subdirectory).

When running from the monorepo root, the root conftest.py registers the hooks first,
and this file's register_conftest_hooks() call is a no-op (guarded by a module-level flag).
"""

from imbue.imbue_common.conftest_hooks import register_conftest_hooks
from imbue.imbue_common.conftest_hooks import register_marker
from imbue.mngr.utils.logging import suppress_warnings
from imbue.resource_guards.resource_guards import register_resource_guard

suppress_warnings()

# Register marks and guards used directly by mngr-claude tests.
# These must be registered here (not just in the inherited conftest files via
# pytest_plugins below) because pytest_configure runs before pytest_plugins
# modules are imported.
register_marker("tmux: marks tests that create real tmux sessions or mngr agents")
register_marker("rsync: marks tests that invoke rsync for file transfer")
register_marker("modal: marks tests that connect to the Modal cloud service")
register_resource_guard("tmux")
register_resource_guard("rsync")

register_conftest_hooks(globals())

# Inherit fixtures from mngr's conftest (base test infrastructure) and
# mngr_modal's conftest (modal token loading, modal_subprocess_env, etc.)
pytest_plugins = ["imbue.mngr.conftest", "imbue.mngr_modal.conftest"]
