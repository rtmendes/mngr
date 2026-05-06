Add a draft spec under `specs/expose-outer-host/` for exposing each
host's outer machine (the VPS / docker daemon host / local machine
hosting a container) on `OnlineHostInterface` so that `mngr exec` can
target it. Modal is excluded because Sandboxes have no accessible outer
host. No code changes yet; spec authoring in progress via `/architect`.
