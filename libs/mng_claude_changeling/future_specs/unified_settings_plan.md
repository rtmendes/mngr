# Unified plan: refactor .mng/settings.toml handling for changelings

This document is a coherent implementation plan that addresses all three settings-related specs:

1. **optional_mng_settings.md** -- make `.mng/settings.toml` purely optional
2. **per_role_mng_settings.md** -- per-role `.mng/settings.toml` with symlink trick
3. **generate_mng_settings.md** -- generate `.mng/settings.toml` from role directories

## Current state

Today, the `changeling deploy` command in `apps/changelings`:
- Writes a `.mng/settings.toml` file with `[create_templates.entrypoint]` containing the agent type
- Validates that this file exists before proceeding (`_validate_settings_exist`)
- Passes `-t entrypoint` to `mng create`, which reads the template from `.mng/settings.toml` to determine the agent type

The plugin (`mng_claude_changeling`) does not interact with `.mng/settings.toml` at all during provisioning. It reads `changelings.toml` (a separate file) for its own settings.

During provisioning, the plugin creates three symlinks so Claude Code discovers the right files from the repo root:
- `.claude/` -> `<active_role>/.claude/` (directory symlink)
- `CLAUDE.md` -> `GLOBAL.md`
- `CLAUDE.local.md` -> `<active_role>/PROMPT.md`

## Key insight: run Claude Code from within the role directory

Instead of symlinking everything to the repo root, we can have Claude Code run from within the role directory itself (e.g., `thinking/`). This solves multiple problems at once:

- `.claude/` is found naturally (no symlink needed)
- `.mng/settings.toml` per-role comes for free (mng reads project config from the git root or cwd)
- `CLAUDE.md` at the repo root (symlinked to `GLOBAL.md`) is still discovered by Claude Code walking up the directory tree
- `PROMPT.md` becomes `CLAUDE.local.md` within the role directory (or we symlink it)

## Design decisions

### 1. Stop generating `.mng/settings.toml` in `changeling deploy`

The deploy command should stop writing `.mng/settings.toml`. Instead:
- When `--agent-type` is provided, pass it directly to `mng create --agent-type <type>` instead of going through the template indirection.
- Remove `_write_mng_settings_toml()` from `deploy.py`.
- Remove `_validate_settings_exist()` from `deploy.py`.
- Remove `-t entrypoint` from the `mng create` invocation in `local.py`.

This is the simplest path: the deploy command knows the agent type, so it should pass it directly rather than writing a file for mng to read back.

### 2. Pass a ROLE environment variable to the agent

The deploy command passes the primary role name (default: `"thinking"`) as a `ROLE` environment variable. This is set on the `mng create` invocation and becomes available to the agent at runtime.

The `ClaudeChangelingConfig.active_role` field already exists and defaults to `"thinking"`. It maps naturally to this env var. The deploy command can pass `--env ROLE=thinking` (or whatever role) to `mng create`.

### 3. Override `assemble_command()` to `cd $ROLE`

In `ClaudeChangelingAgent`, override `assemble_command()` to prepend `cd $ROLE && ` to the command. This causes Claude Code to run from within the role directory.

**Effect:** Claude Code's cwd is now `<work_dir>/<role>/` (e.g., `~/.changelings/<agent-id>/thinking/`). It naturally finds:
- `.claude/settings.json`, `.claude/skills/`, etc. in the role directory
- `CLAUDE.md` at the repo root (Claude Code walks up the tree)
- `.mng/settings.toml` can optionally exist at `<role>/.mng/settings.toml` for per-role mng config

### 4. Remove the `.claude/` symlink from provisioning

Since Claude Code now runs from within the role directory, we no longer need the `.claude/` -> `<role>/.claude/` symlink. This removes:
- The directory symlink creation in `create_changeling_symlinks()`
- The workaround in `_configure_role_hooks()` that bypasses the `git check-ignore` failure caused by the symlink

We still need:
- `CLAUDE.md` -> `GLOBAL.md` symlink at the repo root (for Claude Code's parent directory walk)
- `CLAUDE.local.md` in the role directory, which can be either:
  - A symlink from `CLAUDE.local.md` -> `PROMPT.md` within the role directory
  - Or we just rename `PROMPT.md` to `CLAUDE.local.md` in defaults (simpler, but changes the convention)

Decision: **create a symlink `<role>/CLAUDE.local.md` -> `<role>/PROMPT.md`** during provisioning. This keeps `PROMPT.md` as the user-facing name (more descriptive) while ensuring Claude Code discovers it.

### 5. Per-role `.mng/settings.toml` comes for free

Because Claude Code runs from `<role>/`, and mng reads project config from the working directory, placing a `.mng/settings.toml` inside a role directory (e.g., `thinking/.mng/settings.toml`) will naturally be picked up. No special handling needed.

### 6. No need to generate `.mng/settings.toml` during provisioning

The agent type is passed directly via `--agent-type` on the CLI. The plugin doesn't need to generate settings files. If users want per-role mng config, they put `.mng/settings.toml` in the role directory manually.

### 7. Add `agent_type` field to `changelings.toml`

For repos that want to declare their agent type without CLI flags:

```toml
# changelings.toml
agent_type = "elena-code"

[chat]
model = "claude-opus-4.6"
```

Resolution order for agent type: CLI `--agent-type` flag -> `changelings.toml` `agent_type` field -> `.mng/settings.toml` entrypoint template (backward compat) -> error.

## Implementation plan

### Phase 1: Override `assemble_command()` in `ClaudeChangelingAgent`

**Files changed:**
- `libs/mng_claude_changeling/imbue/mng_claude_changeling/plugin.py`:
  - Override `assemble_command()` to prepend `cd "$ROLE" && ` to the base command
  - The `$ROLE` env var is resolved at runtime from the agent's environment

**How it works:**
```python
def assemble_command(self, host, agent_args, command_override):
    base_command = super().assemble_command(host, agent_args, command_override)
    return CommandString(f'cd "$ROLE" && {base_command}')
```

### Phase 2: Update provisioning to remove `.claude/` symlink

**Files changed:**
- `libs/mng_claude_changeling/imbue/mng_claude_changeling/provisioning.py`:
  - In `create_changeling_symlinks()`: remove the `.claude/` directory symlink creation
  - In `create_changeling_symlinks()`: remove the `CLAUDE.local.md` -> `<role>/PROMPT.md` symlink at repo root
  - Add a new symlink: `<role>/CLAUDE.local.md` -> `<role>/PROMPT.md` (within the role directory)
  - Keep the `CLAUDE.md` -> `GLOBAL.md` symlink at repo root
- `libs/mng_claude_changeling/imbue/mng_claude_changeling/plugin.py`:
  - In `_configure_role_hooks()`: simplify to write directly to `.claude/settings.local.json` (no longer needs to bypass symlink workaround)
  - In `provision()`: the `_configure_readiness_hooks()` workaround comment can be simplified
  - Update `setup_memory_directory()` calls: the memory directory path changes because Claude Code now sees the project root as the role directory, so the claude project dir name is based on `<work_dir>/<role>/` instead of `<work_dir>/`

### Phase 3: Update `changeling deploy` to pass `--agent-type` directly

**Files changed:**
- `apps/changelings/imbue/changelings/cli/deploy.py`:
  - Remove `_write_mng_settings_toml()` function
  - Remove `_validate_settings_exist()` function and its call
  - Update `_prepare_repo()` to not generate `.mng/settings.toml`
  - Add agent type resolution: CLI flag -> `changelings.toml` -> error
- `apps/changelings/imbue/changelings/deployment/local.py`:
  - Update `_create_mng_agent()` to accept `agent_type` parameter
  - Pass `--agent-type <type>` instead of `-t entrypoint`
  - Pass `--env ROLE=<role>` (defaulting to `thinking`)
  - Remove the `-t entrypoint` flag
- `apps/changelings/imbue/changelings/errors.py`:
  - Remove or rename `MissingSettingsError` to `MissingAgentTypeError`

### Phase 4: Add `agent_type` field to `changelings.toml` schema

**Files changed:**
- `libs/mng_claude_changeling/imbue/mng_claude_changeling/data_types.py`:
  - Add `agent_type: AgentTypeName | None` field to `ClaudeChangelingSettings`

### Phase 5: Update tests and clean up

**Files changed:**
- Update tests in both `libs/mng_claude_changeling` and `apps/changelings` to reflect:
  - No `.claude/` symlink
  - `CLAUDE.local.md` symlink within role directory instead of at root
  - `assemble_command()` prepends `cd "$ROLE"`
  - Deploy no longer generates `.mng/settings.toml`
  - Deploy passes `--agent-type` and `--env ROLE=...` directly

## Migration / backward compatibility

- Existing deployed changelings continue working (they have the old symlinks, which are harmless).
- New deployments use the new structure (no `.claude/` symlink, Claude Code runs from role dir).
- Re-provisioning an existing changeling (`mng provision`) will set up the new structure. The old symlinks will be overwritten/cleaned up during provisioning.
- `.mng/settings.toml` at the repo root is still read by mng if present (backward compat for cloned repos).

## What this simplifies

1. **No more `.claude/` symlink** -- eliminates the `git check-ignore` workaround in `_configure_role_hooks()`
2. **No more `.mng/settings.toml` generation** -- deploy passes agent type directly
3. **Per-role `.mng/settings.toml` for free** -- just put one in the role directory
4. **Per-role `.claude/` for free** -- already there, no symlink needed
5. **Cleaner `CLAUDE.local.md`** -- lives in the role directory where it belongs, not at root via symlink
