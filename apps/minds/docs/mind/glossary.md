# Glossary

There are several key concepts to understand when working with minds:

- **mind**: a single mngr agent created from a template repository (or local directory) via `mngr create`. All configuration -- agent types, templates, environment variables -- lives in the template's `.mngr/settings.toml`. Each mind is identified by its `AgentId` and is labeled with `mind=<name>` for discovery via `mngr list`.
- **forwarding server**: a local process (started via `mind forward`) that handles authentication and proxies web traffic from the user's browser to the appropriate mind's web server. Since a user may have *multiple minds* running simultaneously, the forwarding server multiplexes access to all of them through a single local endpoint, handling discovery, routing, and authentication centrally. The forwarding server can also create new minds from git repositories or local paths, and optionally sets up Cloudflare tunnels for global access.
