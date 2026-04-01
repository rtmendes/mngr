#!/bin/bash
# Start the Docker daemon inside a Modal sandbox with enable_docker=True.
# Based on Modal's Docker-in-Sandboxes demo:
# https://modal.com/docs/guide/docker-in-sandboxes
set -xe -o pipefail

dev=$(ip route show default | awk '/default/ {print $5}')
if [ -z "$dev" ]; then
    echo "Error: No default device found."
    ip route show
    exit 1
else
    echo "Default device: $dev"
fi
addr=$(ip addr show dev "$dev" | grep -w inet | awk '{print $2}' | cut -d/ -f1)
if [ -z "$addr" ]; then
    echo "Error: No IP address found for device $dev."
    ip addr show dev "$dev"
    exit 1
else
    echo "IP address for $dev: $addr"
fi

echo 1 > /proc/sys/net/ipv4/ip_forward
iptables-legacy -t nat -A POSTROUTING -o "$dev" -j SNAT --to-source "$addr" -p tcp
iptables-legacy -t nat -A POSTROUTING -o "$dev" -j SNAT --to-source "$addr" -p udp

# gVisor doesn't support nftables yet (https://github.com/google/gvisor/issues/10510).
update-alternatives --set iptables /usr/sbin/iptables-legacy
update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy

dockerd --iptables=false --ip6tables=false &

# Wait for Docker daemon to be ready
timeout 30 sh -c 'until docker info >/dev/null 2>&1; do sleep 1; done'
echo "Docker daemon is ready."
