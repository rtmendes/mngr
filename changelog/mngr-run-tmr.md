- `mngr create -vv` now emits a `Transferring agent files` log span around the
  per-file `write_file` loop in agent provisioning, so the total time spent
  pushing plugin-declared files (e.g. Claude Code config) is visible in timing
  output.
- `mngr tmr` no longer crashes the whole orchestrator when a single agent
  fails its initial-message send (e.g. `SendMessageError` from the tmux
  paste-detection timeout). The launching loops now also catch `AgentError`
  alongside `MngrError` / `HostError`, log a warning, and continue with the
  remaining agents. This applies to test-agent launching (both batched and
  pre-launched modes) and to the integrator launch.
- Fix `mngr tmr` integrator launch (and any local-provider test-agent
  launch), which always failed with `Failed to generate a unique host name
  after 100 attempts`. The local provider has a single fixed host
  ("localhost"), so the new-host path can never find a free name; TMR now
  reuses the existing local host when the target provider is `local`,
  matching what `mngr create` already does.
- `mngr tmr` HTML reports now include rows for tests whose agent failed to
  launch (e.g. `SendMessageError` from a paste-detection timeout). They are
  rendered as errored entries instead of being silently dropped.
