# Docker-in-Docker on Modal: Experiment Log

## Goal

Run a release test (`test_multiple_snapshots_ordering`) inside a Modal sandbox
with `enable_docker=True`, which requires `MODAL_IMAGE_BUILDER_VERSION=2025.06`.

## Problem

The alpha image builder hangs during the image save/materialize phase for any
non-trivial Dockerfile. All experiments below hit the same wall unless noted.

**Caveat:** Modal appeared to be experiencing infrastructure issues during this
testing window (2026-04-02). Every experiment that "hung" may have been affected
by transient Modal-side problems rather than a fundamental size limit.

## Experiments

| # | What changed | Image size (est.) | Outcome | Hypothesis |
|---|---|---|---|---|
| 1 | Docker CE via apt in Dockerfile | ~2 GB | Worker crashed at ~60 min | Large images OOM the alpha builder |
| 2 | Pre-built base pushed to GHCR | ~700 MB | Auth failure (skopeo unauthorized) | GHCR packages default private; Modal can't pull without credentials |
| 3 | Pre-built base pushed to Docker Hub (Docker CE) | ~700 MB | Worker crashed at ~60 min | Same OOM as #1 — pre-built base doesn't help if total image is large |
| 4 | Slim Dockerfile: python:3.11-slim + git/curl/uv only, **no Docker, no code copy** | ~200 MB | **Saved in 910ms** | Small images save fine on alpha builder |
| 5 | Pre-built base on Docker Hub (static Docker binaries instead of Docker CE) | ~419 MB base + code | Hung 110+ min, no crash | Static binaries smaller but still too large, or Modal was flaky |
| 6 | Self-contained Dockerfile: static Docker + build-essential + code | ~500 MB | Hung 30+ min, killed | build-essential adds ~200 MB; still too large, or Modal was flaky |
| 7 | Same as #6 but dropped build-essential | ~350 MB | Hung 30+ min, killed | build-essential wasn't the bottleneck (uv sync worked without it), or Modal was flaky |
| 8 | Same as #7 + .dockerignore excluding .venv (221 MB) and .git (39 MB) | ~300 MB | Hung 28+ min, killed | Context size reduction didn't help, or Modal was flaky |
| 9 | Same as #7 but removed `MODAL_IMAGE_BUILDER_VERSION=2025.06` (standard builder) | ~300 MB | Hung, killed | Not specific to alpha builder, or Modal was flaky |
| 10 | Slim Dockerfile (no Docker) + Docker installed via `.run_commands()` as separate layer | ~300 MB Dockerfile + 70 MB layer | Hung at Dockerfile save — never reached Docker layer | Even the slim Dockerfile with code+deps hangs, or Modal was flaky |

## Key observations

- Experiment #4 is the only success: a truly minimal image with no code copy.
- Every Dockerfile that includes `COPY . /code/` + `uv sync` hangs, even with
  `.dockerignore` and no Docker binaries at all (#7, #8, #10).
- The common factor in all failures is the code + Python deps layer, not Docker.
- However, Modal may have been degraded during all failing runs, making it
  impossible to distinguish "image too large" from "Modal infrastructure issue."

## What hasn't been tried

- `Image.from_registry()` to pull a pre-built image (bypasses Dockerfile builder entirely)
- Splitting the Dockerfile so code/deps are added via `.add_local_dir()` after a cached base
- Re-running any experiment after Modal has recovered
- Contacting Modal support about alpha builder save performance
