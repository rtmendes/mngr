# mngr_imbue_cloud

Provider backend plugin and CLI for Imbue Cloud (the imbue-team-hosted leasing
service that talks to `remote_service_connector`).

The plugin owns four concern areas, all reachable only through `mngr` commands:

- **auth** — SuperTokens session: signup, signin, oauth, refresh, signout, status
- **hosts** — lease/release/list pre-provisioned pool hosts
- **keys** — LiteLLM virtual key management (`mngr imbue_cloud keys litellm ...`)
- **tunnels** — Cloudflare tunnel + service + auth-policy management
- **admin pool** — operator-only pool provisioning (Vultr + Neon)

## Configuration

Each signed-in account is its own provider instance entry in
`~/.mngr/config.toml`:

```toml
[providers.imbue_cloud_alice]
backend = "imbue_cloud"
account = "alice@imbue.com"
# connector_url is optional; defaults to the prod URL.
```

The default connector URL can be overridden via the
`MNGR__PROVIDERS__IMBUE_CLOUD__CONNECTOR_URL` environment variable.

## Sign in

```bash
mngr imbue_cloud auth signin --account alice@imbue.com
# or browser-based OAuth:
mngr imbue_cloud auth oauth google --account alice@imbue.com
```

Token state lives at `<default_host_dir>/providers/imbue_cloud/sessions/<user_id>.json`.

## Claim a host

```bash
mngr imbue_cloud claim my-agent --account alice@imbue.com \
    --repo-url https://github.com/imbue-ai/forever-claude-template \
    --repo-branch v1.2.3
```

This leases a matching pool host from the connector, runs the rename + label +
env-injection sequence in 2 SSH round trips, and starts the agent.

## Destroy vs delete

- `mngr destroy <agent>` stops the docker container on the leased VPS only;
  the lease and on-disk data are preserved. `mngr start <agent>` brings it
  back on the same VPS.
- `mngr delete <agent>` (or `mngr imbue_cloud hosts release <lease-id>`)
  releases the VPS back to the pool and drops all data.

## Pool admin

```bash
mngr imbue_cloud admin pool create --count 1 \
    --version v1.2.3 \
    --workspace-dir ./forever-claude-template \
    --management-public-key-file ./id_ed25519.pub \
    --database-url "$NEON_DB_DIRECT"
```
