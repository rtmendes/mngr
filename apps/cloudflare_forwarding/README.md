# cloudflare_forwarding

A lightweight service deployed as a Modal Function that wraps the Cloudflare tunnel API behind authenticated HTTP endpoints.

## What it does

Allows authenticated users to:
- Create Cloudflare tunnels (one per host running `cloudflared`)
- Add/remove forwarding rules (ingress + DNS) on those tunnels
- List their tunnels and configured services
- Delete tunnels (cascading cleanup of DNS and ingress)

After creating a tunnel, users receive a token to run `cloudflared tunnel run --token <TOKEN>` on their host.

## Deployment

Requires the following Modal Secrets (env vars):

- `CLOUDFLARE_API_TOKEN`: Cloudflare API token with Tunnel Write and DNS Write permissions
- `CLOUDFLARE_ACCOUNT_ID`: Cloudflare account ID
- `CLOUDFLARE_ZONE_ID`: Cloudflare zone ID for DNS records
- `CLOUDFLARE_DOMAIN`: Base domain for service subdomains (e.g. `example.com`)
- `USER_CREDENTIALS`: JSON object mapping usernames to secrets (e.g. `{"alice": "secret1"}`)

Deploy with:

```bash
modal deploy apps/cloudflare_forwarding/imbue/cloudflare_forwarding/app.py
```

## API

All endpoints require HTTP Basic Auth.

### Tunnels

- `POST /tunnels` -- Create a tunnel. Body: `{"agent_id": "..."}`. Returns tunnel info with token.
- `GET /tunnels` -- List your tunnels with their configured services.
- `DELETE /tunnels/{tunnel_name}` -- Delete a tunnel and all its DNS records/ingress rules.

### Services

- `POST /tunnels/{tunnel_name}/services` -- Add a service. Body: `{"service_name": "...", "service_url": "http://localhost:8080"}`.
- `DELETE /tunnels/{tunnel_name}/services/{service_name}` -- Remove a service and its DNS record.
