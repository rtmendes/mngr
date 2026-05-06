Add a Concise spec under `specs/expose-outer-host/concise.md` for
exposing each host's outer machine (the VPS / docker daemon host /
local machine hosting a container) on `OnlineHostInterface` and
`ProviderInstanceInterface` as an optional context-manager-based
accessor that yields `OnlineHostInterface | None`. Surfaces via a new
`mngr exec --outer` flag that dedups by outer host so the command runs
once per unique outer; `--missing-outer abort|warn|ignore` (default
`warn`) controls behavior when targeted agents have no accessible
outer. The existing one-off SSH paths
(`mngr_imbue_cloud/vps_admin.py`, `mngr_vps_docker/docker_over_ssh.py`)
will be deleted and migrated to the new abstraction. Modal, `local`,
`ssh`, and docker-over-tcp return `None` (no accessible outer). No
code changes yet — spec only.
