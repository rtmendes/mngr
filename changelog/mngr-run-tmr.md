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
