---
name: new-forever-claude-clone
argument-hint: <owner>/<repo-name>
description: Create a new PRIVATE GitHub repo that is a full-history copy of imbue-ai/forever-claude-template's current main branch, clone it to ~/project/<repo-name>, and push. Use when the user asks to "spin up a new forever-claude clone", "fork the forever-claude template as a private repo", "make me a new private copy of forever-claude-template", or similar.
---

# Create a new private copy of forever-claude-template

This skill stands up a brand-new private GitHub repository that contains the full git history of `imbue-ai/forever-claude-template`'s current `main` branch. It clones the result to `~/project/<repo-name>` so the user can start using it immediately.

## Input parsing

The Skill tool passes the entire args string as `$1`. Parse it into `OWNER` and `REPO`:

- **Canonical form** (preferred): `<owner>/<repo-name>`, e.g. `joshalbrecht/story-recommender`.
  Split on the single `/`.
- **Space-separated form**: `<repo-name> <owner>` or `<owner> <repo-name>` may show up if the caller used the old argument-hint format. Disambiguate by looking for a `/` (canonical) first; if absent and two tokens are present, ask the user to confirm which is which -- do not guess.
- **Bare repo name** (no owner): ask the user for the owner. Common choices are their personal account (e.g. `joshalbrecht`) or an org (`imbue-ai`). Never guess.

After parsing, you should have:
- `OWNER` -- a GitHub username or org.
- `REPO` -- the new repo name. This is also the local directory name under `~/project/`.

Use these throughout the rest of the skill in place of the literal placeholders `<owner>` / `<repo-name>` in the commands below.

## Preconditions to check (fail loudly if any are wrong)

1. `gh` CLI is installed and authenticated (`gh auth status`). For a personal repo the default scopes are enough; for an org repo the token needs `admin:org` or the org must allow member repo creation.
2. `~/project/forever-claude-template` exists, has `origin` pointing at `git@github.com:imbue-ai/forever-claude-template.git`, is on `main`, has a clean working tree, and `git fetch origin main` leaves no "ahead"/"behind" delta versus `origin/main`. We are copying the history that is actually on `origin/main`, not whatever stale state a local checkout happens to have.
3. `~/project/<REPO>` does NOT already exist. Do not overwrite an existing directory.
4. The target GitHub repo `<OWNER>/<REPO>` does NOT already exist (`gh repo view <OWNER>/<REPO>` returns non-zero). If it already exists, stop and ask -- we never push into a pre-existing repo the user didn't intend.

## Steps

### 1. Clone forever-claude-template into the new path

Use a fresh `git clone` (not `cp -r` of the existing checkout) so git state is clean and we pick up `origin/main` exactly:

```bash
cd ~/project
git clone git@github.com:imbue-ai/forever-claude-template.git <REPO>
cd <REPO>
git checkout main
```

This gives us the full commit history reachable from `main`.

### 2. Rewire the remote

Drop the template's `origin` so we don't accidentally push template-copy commits back upstream:

```bash
git remote remove origin
```

### 3. Create the private repo and push in one shot

```bash
gh repo create "<OWNER>/<REPO>" --private --source=. --remote=origin --push
```

`--source=.` tells `gh` to use the current directory as the source repo; `--push` pushes the current branch (`main`) to the new remote after creation. This preserves the full history of `main`.

If the user wanted more than just `main` copied (e.g. all branches/tags), `--push` only pushes the current branch. In that case, replace the push with `git push --all origin && git push --tags origin` after `gh repo create` (omit `--push` from the `gh` invocation). Default behavior for this skill is `main` only; escalate to all-refs only if the user explicitly asks.

### 4. Verify

```bash
git remote -v                                                   # origin should be the new private repo
git log --oneline -3                                            # same recent commits as forever-claude-template main
gh repo view "<OWNER>/<REPO>" --json name,visibility,url        # visibility should be PRIVATE
git rev-list --count HEAD                                       # commit count -- quick sanity
```

### 5. Print the GH_TOKEN creation URL (pre-filled)

The user will want a `GH_TOKEN` scoped to the new private repo. Tokens cannot be created programmatically, but GitHub's creation pages accept query parameters that pre-fill most of the form. Hand the user a URL with as much pre-filled as possible.

**Classic PAT URL (fully pre-fills scopes -- recommended if the user just wants a working token fast):**

```
https://github.com/settings/tokens/new?description=<REPO>%20token&scopes=repo,workflow
```

GitHub's classic-token page honors `scopes=` (comma-separated) and `description=` URL parameters -- the scope checkboxes will already be checked when the page loads. `repo` alone is enough for a private-repo token; add `workflow` only if the user plans to modify `.github/workflows/` via the token. URL-encode spaces in the description (`%20`).

**Fine-grained PAT URL (least-privilege, recommended for long-lived automation; but some fields must still be picked manually):**

```
https://github.com/settings/personal-access-tokens/new?name=<REPO>&description=<REPO>%20token&target_name=<OWNER>&expires_in_days=90
```

GitHub's fine-grained page honors `name`, `description`, `target_name` (the resource owner), and `expires_in_days`. It does NOT accept URL parameters for permissions or repository selection, so the user still has to:
- Under "Repository access": pick "Only select repositories" and add `<OWNER>/<REPO>`.
- Under "Repository permissions": set **Contents: Read and write** and **Metadata: Read-only** (and **Pull requests**, **Workflows**, **Actions** if they plan to automate those).

Default-recommend the fine-grained URL. Tell the user "the classic URL is faster but broader" and let them pick.

### 6. Report

Report back:
- Clone URL: `git@github.com:<OWNER>/<REPO>.git`.
- Web URL: `https://github.com/<OWNER>/<REPO>`.
- Local path: `~/project/<REPO>`.
- Commit count (from `git rev-list --count HEAD`) -- sanity check that history came across.
- Both token-creation URLs from step 5, with the pre-fill values actually substituted in (don't leave literal `<REPO>` / `<OWNER>` in the URL you show the user).

## Things not to do

- Do not use `gh repo fork` -- GitHub "forks" keep a parent pointer and can't easily be made fully private/independent. We want an independent repo.
- Do not `cp -r` the existing checkout. It would copy untracked files, editor swapfiles, `.venv`, `node_modules`, etc. A fresh `git clone` is the right tool.
- Do not push force or touch `imbue-ai/forever-claude-template` in any way. This skill only reads from it.
- Do not create the repo under an owner the user did not explicitly name.
- Do not rename `main` to something else, and do not squash/rewrite history. The request is a full-history copy.
- Do not try to mint a PAT via any API. Just print the URL.
