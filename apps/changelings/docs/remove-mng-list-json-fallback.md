# Plan: Add SSH info to discovery events, remove mng list --json fallback

## Context

The changelings forwarding server's `MngStreamManager` currently uses `mng list --stream` for agent discovery but falls back to `mng list --json` to get SSH info (needed for tunneling to remote agents). This is because `DiscoveredHost` - the model used in discovery events - lacks SSH fields. The goal is to add SSH info to the discovery event system so the forwarding server can get everything from the stream alone.

## Changes

### 1. Add SSH info to `DiscoveredHost` (mng library)

**File: `libs/mng/imbue/mng/primitives.py`** (~line 310)

Move `SSHInfo` from `interfaces/data_types.py` to `primitives.py` (it's a pure data model with no dependencies beyond `FrozenModel`, `Field`, and `Path`). Then add an optional `ssh` field to `DiscoveredHost`:
```python
# In primitives.py:
class SSHInfo(FrozenModel):
    """SSH connection information for a remote host."""
    user: str
    host: str
    port: int
    key_path: Path
    command: str  # Full SSH command (e.g. "ssh -i /path/key -p 2222 root@host")

class DiscoveredHost(FrozenModel):
    host_id: HostId
    host_name: HostName
    provider_name: ProviderInstanceName
    ssh: SSHInfo | None = Field(default=None, description="SSH info, present for remote hosts")
```

Update the 4 files that import SSHInfo to import from primitives instead:
- `libs/mng/imbue/mng/api/list.py`
- `libs/mng/imbue/mng/api/test_list.py`
- `libs/mng/imbue/mng/providers/modal/instance.py`
- `libs/mng/imbue/mng/interfaces/data_types_test.py`

In `interfaces/data_types.py`, remove the SSHInfo class and import it from primitives. The `HostDetails.ssh` field type annotation still works since SSHInfo is now in primitives.

### 2. Populate SSH info in conversion functions

**File: `libs/mng/imbue/mng/api/discovery_events.py`**

**A. `discovered_host_from_agent_details`** (~line 120): Pass through `agent_details.host.ssh` directly (same type now):
```python
def discovered_host_from_agent_details(agent_details: AgentDetails) -> DiscoveredHost:
    return DiscoveredHost(
        host_id=agent_details.host.id,
        host_name=HostName(agent_details.host.name),
        provider_name=agent_details.host.provider_name,
        ssh=agent_details.host.ssh,
    )
```

This is the path used by `_write_unfiltered_full_snapshot` -> `extract_agents_and_hosts_from_full_listing` -> `discovered_host_from_agent_details`.

**B. `discovered_host_from_online_host`** (~line 130): Extract SSH info via `host._get_ssh_connection_info()`:
```python
def discovered_host_from_online_host(host, provider_name) -> DiscoveredHost:
    certified = host.get_certified_data()
    ssh = _build_discovered_host_ssh(host)
    return DiscoveredHost(
        host_id=host.id, host_name=HostName(certified.host_name),
        provider_name=provider_name, ssh=ssh,
    )
```

Add helper `_build_ssh_info_from_host(host) -> SSHInfo | None` that calls `host._get_ssh_connection_info()` and builds the model. Same pattern as `libs/mng/imbue/mng/api/list.py:362`.

This path is used by `emit_discovery_events_for_host` which is called from create, destroy, start, stop, rename, cleanup, provision - i.e., whenever a host state change occurs.

### 3. Update `make_test_discovered_host`

**File: `libs/mng/imbue/mng/utils/testing.py`** (~line 1004)

No change needed - the new `ssh` field defaults to None, so existing test helpers work as-is.

### 4. Parse SSH info from discovery events in changelings

**File: `apps/changelings/imbue/changelings/forwarding_server/backend_resolver.py`**

**A. Update `_handle_discovery_line`** in `MngStreamManager`: When processing a `DISCOVERY_FULL` event, extract SSH info from the hosts array and update the resolver. No need to call `mng list --json` anymore.

**B. Remove `_fetch_and_update_agents`** method entirely - this is the `mng list --json` fallback.

**C. Update `start()`**: No longer call `_fetch_and_update_agents()` on start. The first `DISCOVERY_FULL` event from the stream will populate everything.

**D. Update `_handle_discovery_line`**: Instead of checking for "truly new" agents and calling `_fetch_and_update_agents`, just parse SSH info directly from the `DISCOVERY_FULL` event's hosts:
```python
def _handle_discovery_line(self, line: str) -> None:
    event = parse_discovery_event_line(line)
    if not isinstance(event, FullDiscoverySnapshotEvent):
        return

    agent_ids = tuple(agent.agent_id for agent in event.agents)

    # Extract SSH info from hosts in the discovery event
    ssh_info_by_agent: dict[str, RemoteSSHInfo] = {}
    ssh_by_host_id: dict[str, SSHInfo] = {}
    for host in event.hosts:
        if host.ssh is not None:
            ssh_by_host_id[str(host.host_id)] = host.ssh
    for agent in event.agents:
        host_ssh = ssh_by_host_id.get(str(agent.host_id))
        if host_ssh is not None:
            ssh_info_by_agent[str(agent.agent_id)] = RemoteSSHInfo(
                user=host_ssh.user, host=host_ssh.host,
                port=host_ssh.port, key_path=host_ssh.key_path,
            )

    self.resolver.update_agents(ParsedAgentsResult(
        agent_ids=agent_ids,
        ssh_info_by_agent_id=ssh_info_by_agent,
    ))
    self._sync_events_streams({str(aid) for aid in agent_ids})
```

**E. Remove imports** of `ConcurrencyExceptionGroup`, `ConcurrencyGroup` from backend_resolver.py (no longer needed for `_fetch_and_update_agents`). Also remove `_SUBPROCESS_TIMEOUT_SECONDS`. Also remove `parse_agents_from_json` usage from MngStreamManager (it was used by `_fetch_and_update_agents` to parse `mng list --json` output).

**F. Remove `get_all_ssh_info`** from `MngCliBackendResolver` - it was only needed for the old pattern where `_handle_discovery_line` had to preserve SSH info across updates. Now SSH info comes from the event itself.

### 5. Update conftest.py

**File: `apps/changelings/imbue/changelings/forwarding_server/conftest.py`**

`make_resolver_with_data` still works - it uses `parse_agents_from_json` to populate the resolver for tests, which is fine since the test helper parses `mng list --json` format. The streaming path is separate.

### 6. Update tests

**File: `apps/changelings/imbue/changelings/forwarding_server/backend_resolver_test.py`**

- Remove test for `get_all_ssh_info` if present
- Existing MngStreamManager tests still pass (they test callbacks directly)

**File: `libs/mng/imbue/mng/api/discovery_events_test.py`**

- Add test that `discovered_host_from_agent_details` includes SSH info when present
- Add test that `discovered_host_from_online_host` includes SSH info for remote hosts
- Verify `FullDiscoverySnapshotEvent` serialization/deserialization preserves SSH info

## Verification

1. Run `cd libs/mng && uv run pytest` - all mng tests pass
2. Run `cd apps/changelings && uv run pytest` - all changelings tests pass
3. Verify no references to `mng list --json` remain in backend_resolver.py (only in conftest for test helpers)
