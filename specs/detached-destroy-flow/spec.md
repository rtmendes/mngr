# Detached destroy flow

## Overview

Today, "destroy project" hangs the project-settings page until the underlying `mngr destroy` returns. The destroy runs in a Python daemon thread inside the minds backend, so it dies if minds restarts; while it runs, the settings page shows only a generic "Destroying..." spinner with no visibility into stdout/stderr; on failure the user gets an `alert()` with a single-line error and no way to inspect the actual logs. We need each of:

1. The destroy work moves into a **detached subprocess** (`subprocess.Popen` with `start_new_session=True`, mirroring `apps/minds/imbue/minds/desktop_client/latchkey/_spawn.py`). The process outlives the minds backend the same way the latchkey gateway does.
2. While the detached process is running, the **landing page (`/`)** shows a "Destroying..." marker on the corresponding workspace row.
3. The settings-page destroy button **redirects immediately to `/`** after firing the POST, so the user lands on the page where the marker is already visible (no spinner-on-settings stage).
4. Each destroy run keeps its **stdout/stderr in a per-destroy log file** and a **state file** that records pid, exit code, start/finish time, and a one-line error summary. The user can drill into a "destroy detail" page that tails the log live and surfaces the failure reason when the process exits non-zero or is killed.

## Expected Behavior

### POST `/api/destroy-agent/<agent_id>`

- Authenticated; otherwise `403`.
- Resolves the imbue_cloud account email (existing logic, unchanged) and disassociates the workspace from the session store *before* spawning so the workspace doesn't reappear under that account.
- **Spawns a detached subprocess** that performs the destroy. Returns immediately:
  - `202 Accepted`
  - body: `{"agent_id": "<id>", "status": "running", "redirect_url": "/"}`
- The detached subprocess is started exactly once per agent at a time. If a destroy is **already running for the same agent**, the endpoint returns `200 OK` with the existing record's status (idempotent) — same body shape — and does not start a second process.

### Detached destroy subprocess

- **Command**: `python -m imbue.minds.cli.destroy_agent <agent_id> [--account-email EMAIL]` (a new minds subcommand defined in `apps/minds/imbue/minds/cli/destroy_agent.py`). Reuses the body of today's `AgentCreator._destroy_agent_background` verbatim:
  1. Look up host id via `mngr list --include 'id == "<id>"' --format json`.
  2. If host id was found, run `mngr destroy <agent_id> -f` (and the existing fan-out that destroys every agent on the same host — preserves today's "destroying one Docker agent destroys its host-mates" semantics).
  3. If `--account-email` was passed, call `mngr imbue_cloud hosts release` for the matching lease.
- **Detached spawn**: `subprocess.Popen` with `start_new_session=True`, `stdin=DEVNULL`, `stdout=` and `stderr=` redirected to a single `output.log` file (combined). Inherits the parent's `MNGR_HOST_DIR` / `MNGR_PREFIX` (so it hits the right minds host dir). The Popen handle is intentionally allowed to go out of scope — same pattern as `spawn_detached_latchkey_gateway`.
- **State file** at `<paths.data_dir>/destructions/<agent_id>/state.json`. Written by the subprocess at three points:
  - On startup: `{"agent_id", "account_email", "pid", "started_at", "status": "running"}`.
  - On normal exit: adds `"finished_at"`, `"exit_code"`, sets `"status": "done"` (exit 0) or `"status": "failed"` with `"error": "<one-line summary>"` (exit non-zero or unhandled exception).
- **Output log** at `<paths.data_dir>/destructions/<agent_id>/output.log` (append-only).
- The subprocess terminates after completing; log file and state file persist for inspection.

### Landing-page marker

- Server reads `<paths.data_dir>/destructions/` on each `/` render.
- For each `<agent_id>` whose `state.json` has `status="running"` AND whose `pid` is alive (`os.kill(pid, 0)` doesn't `ProcessLookupError`), render an inline marker on that workspace row:
  - Text: "Destroying…" with a small spinner.
  - The marker links to `/destruction/<agent_id>` (clickable shortcut to the detail page).
  - The row's main click target (currently `window.location='<plugin>/goto/<id>/'`) is **disabled** while destroying.
- For `status="failed"` (or `"running"` but `pid` is not alive — i.e. the subprocess died without writing terminal state), render a "Destroy failed" badge with the same link to `/destruction/<agent_id>`. The agent row still shows because the agent likely wasn't actually destroyed.
- For `status="done"`, the detection code DELETES the destruction directory on next render — by that point the agent should already be gone from `mngr observe` discovery, so the row vanishes naturally. (If discovery hasn't caught up yet, no marker is shown for that beat; the row will disappear on the next refresh.)

### Settings-page destroy button

- The confirmation dialog on `/workspace/<agent_id>/settings` stays.
- On confirm:
  - Fire `POST /api/destroy-agent/<id>`.
  - As soon as the response arrives (status running OR already-running), `window.location.href = '/'`. No more spinner on the settings page; no more polling on the settings page.
  - On 4xx/5xx, surface an inline error inside the existing dialog and don't redirect.

### Destroy detail page `/destruction/<agent_id>`

- Authenticated; otherwise `403`.
- 404 if no record exists at `<paths.data_dir>/destructions/<agent_id>/`.
- Renders:
  - Workspace name (from minds' agent_names cache or the discovered agent — fall back to the bare id).
  - Status badge: "Running…" / "Done" / "Failed".
  - Started-at, finished-at (when present), exit code (when present).
  - Error summary (when present).
  - **Live log tail**: shows the contents of `output.log`. While `status="running"`, polls `GET /api/destruction/<agent_id>/log?after=<bytes>` every second and appends new bytes (matches the simpler-than-SSE pattern used in `creating.js`'s done-event flow). Once status flips to `done`/`failed`, polls one final time and stops.
- For `status="done"`, a "Dismiss" button removes the record (deletes the directory).
- For `status="failed"`, two buttons:
  - **Retry**: re-fires `POST /api/destroy-agent/<id>` (which spawns a fresh detached subprocess; the existing failed state.json is overwritten on first write).
  - **Dismiss**: removes the record.

### GET `/api/destruction/<agent_id>/status`

- Returns `state.json` contents directly (with the `pid_alive` field computed server-side via `os.kill(pid, 0)`).
- Used by the landing page's auto-refresh + the detail page's polling.

### GET `/api/destruction/<agent_id>/log?after=<bytes>`

- Reads `output.log` from byte offset `<after>` (default 0) to current EOF.
- Returns `{"bytes_read": N, "next_offset": M, "content": "<utf8 chunk>"}`.
- 404 if no record exists.

### Adoption on minds restart

- When minds backend starts, it does NOT actively reconcile in-flight destruction records — the polling endpoints already return live state from disk + `kill -0`. The user sees "Destroying…" on the landing page if the subprocess from the previous session is still running, and "Failed" (with the log) if it died in between (no terminal state, pid not alive).

## Out of Scope

- TTL-based auto-cleanup of old destruction records. Records persist until the user dismisses them. (One-line follow-up if the directory grows unboundedly in practice.)
- Cancelling an in-flight destroy from the UI. The detached process owns its lifecycle; if it hangs, the user kills the pid manually (the detail page surfaces the pid).
- Destroy-progress streaming via WebSocket / SSE. Polling `/api/destruction/<id>/log?after=<bytes>` is sufficient for a destroy that typically completes in <60 s.

## Implementation Plan

1. New module `apps/minds/imbue/minds/cli/destroy_agent.py`:
   - Click subcommand wired into `imbue.minds.main:main` as `minds destroy-agent`.
   - Body lifted from `AgentCreator._destroy_agent_background`, but operating on `agent_id` + `account_email` + `MNGR_HOST_DIR` directly (no AgentCreator instance).
   - Writes/updates `<destructions_dir>/<agent_id>/state.json` at startup and at exit.

2. New helper `apps/minds/imbue/minds/desktop_client/destruction.py`:
   - `Destruction` model: `agent_id`, `account_email`, `pid`, `started_at`, `finished_at`, `status` (`running`/`done`/`failed`), `exit_code`, `error`.
   - `start_destruction(agent_id, account_email, paths)` → spawns the detached subprocess, returns the destruction record.
   - `read_destruction(agent_id, paths)` → loads state.json + computes `pid_alive`. Treats `status=running` + `pid_alive=False` as `failed` (with `error="Destroy process exited without writing final state"`).
   - `list_destructions(paths)` → walks `destructions/` for landing-page rendering.
   - `delete_destruction(agent_id, paths)` → removes the directory (used by Dismiss + done-cleanup).
   - `read_log_chunk(agent_id, paths, offset)` → seek + read tail.

3. `apps/minds/imbue/minds/desktop_client/agent_creator.py`:
   - Delete `start_destruction`, `_destroy_agent_background`, `_get_host_id_for_agent`, `_destroy_all_agents_on_host`, `_destroy_single_agent`, `release_imbue_cloud_host`, `get_destruction_info`, the `_destroy_statuses` / `_destroy_errors` private attrs, and the `AgentDestructionStatus` / `AgentDestructionInfo` types. They move into `destroy_agent.py` (subprocess) and `destruction.py` (record management).

4. `apps/minds/imbue/minds/desktop_client/app.py`:
   - `_handle_destroy_agent_api` → calls `start_destruction(...)` (the new helper), returns 202 + `{"status": "running", "redirect_url": "/"}`.
   - Add `_handle_destruction_status_api` (GET `/api/destruction/<agent_id>/status`).
   - Add `_handle_destruction_log_api` (GET `/api/destruction/<agent_id>/log?after=...`).
   - Add `_handle_destruction_dismiss_api` (POST `/api/destruction/<agent_id>/dismiss`).
   - Add `_handle_destruction_page` (GET `/destruction/<agent_id>`).
   - `_handle_landing_page` → call `list_destructions(...)` and pass `destructions: dict[str, Destruction]` into the landing template.

5. `apps/minds/imbue/minds/desktop_client/templates/landing.html`:
   - For each agent_id, if `destructions.get(agent_id)` is set, render the marker (running spinner + link, or failed badge + link). Disable the row's main onclick handler.

6. `apps/minds/imbue/minds/desktop_client/templates/destruction.html` (new):
   - Status, pid, started/finished, error summary, log container with `data-agent-id`. Loads `static/destruction.js`.

7. `apps/minds/imbue/minds/desktop_client/static/destruction.js` (new):
   - Polls `/api/destruction/<id>/log?after=<bytes>` every 1 s, appends new content. When status flips to terminal, does one final poll and stops. Wires Retry / Dismiss buttons.

8. `apps/minds/imbue/minds/desktop_client/templates/workspace_settings.html` + inline JS:
   - On confirm, after `fetch('/api/destroy-agent/<id>', POST)` resolves with 2xx, immediately `window.location.href = '/'`. Drop the `pollDestroyStatus()` and `destroy-spinner` element entirely (server-rendered marker on `/` replaces it).

9. Tests:
   - `destruction_test.py`: round-trip `start_destruction` against a fake destroy command (tiny shell script that prints to stdout, exits 0 or 1), assert state.json transitions and log file content.
   - `app_test.py` / `test_desktop_client.py` patches: assert the new endpoints return the right shapes; assert the landing page renders the marker when destructions/<id>/state.json says running.
   - Unit tests for `read_destruction` adoption logic (running + pid dead → failed).

## Open Questions

A. **Auto-prune of done records.** When `status="done"`, do you want the landing renderer to delete the destruction directory automatically (my proposal), or keep a "Dismiss" tombstone visible until the user clicks dismiss (parallel to FAILED)? Auto-delete is silent; tombstone is more discoverable.

B. **Idempotency on duplicate POST.** If the user POSTs `/api/destroy-agent/<id>` twice (e.g. settings page submitted, then they navigate back, then click destroy on the row), should the second POST be (a) a no-op that returns the existing record's status (my proposal), or (b) a hard `409 Conflict`? (a) is friendlier; (b) surfaces the bug if it ever fires.

C. **Drill-down route URL.** I went with `/destruction/<agent_id>` to mirror `/creating/<creation_id>`. Any reason to prefer a different layout (e.g. nest under settings: `/workspace/<id>/destruction`)? Settings-nested would 404 once the agent is destroyed (because the agent is gone), so I'd lean against that.

D. **Log polling cadence.** `/api/destruction/<id>/log?after=<bytes>` polled every 1 s feels right for a 30 s destroy. Live SSE adds ~80 lines of code; worth it, or stick with polling?

E. **"Destroy host-mates" semantics.** Today's `_destroy_all_agents_on_host(host_id)` destroys every agent on the same Docker host when one is destroyed. That's the same behavior the new detached helper will preserve — confirming you want to keep it. If you'd prefer single-agent destroy with the host left up, that's a one-line change in `destroy_agent.py`.

F. **Where the "Failed to destroy" badge links to.** I'm proposing the destruction-detail page (with the log tail and Retry/Dismiss). Alternative: an inline expand-collapse on the landing-page row showing the last ~5 lines of the log. The detail page is simpler and matches the creating-page idiom, so I lean that way unless you want everything on one page.

G. **Subcommand naming.** `minds destroy-agent <id>` matches the `/api/destroy-agent/<id>` API. Could also be `minds destroy <id>` but that visually collides with `mngr destroy`. Sticking with `destroy-agent` unless you want it shorter.

H. **State-file write atomicity.** I'm proposing `Path.write_text(json.dumps(...))` for state.json updates, which is fine for single-writer (the subprocess) + single-reader (the minds backend) on the same host. If you want hardened atomic writes, we'd add a temp-file + rename pattern. Probably overkill, but flagging.
