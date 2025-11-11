# Repository Integration Options for `moneywiz-api`

This project consumes `moneywiz-api` by cloning MarcoMC's fork into a sibling `moneywiz-api/` directory (run `./moneywiz.sh --setup` to bootstrap it). The directory remains ignored in this repo so contributors can point it at their own fork or upstream. If you need alternative wiring (submodule, subtree, package install), the options below document trade-offs.

## Option A: Git Submodule (source-linked, pinned by commit)

- Pros: Keeps `moneywiz-api` as a separate repo, with its own history; your project pins the exact commit.
- Cons: Requires submodule workflows (init/update) and two-step commits (submodule + parent pointer).

Commands (documentation only — not executed here):

```bash
# Add as a submodule at the `moneywiz-api/` path
git submodule add <API_repo_url> moneywiz-api

# Clone with submodules (on a new machine)
git clone --recurse-submodules <this_repo_url>
# Or initialize submodules after clone
git submodule update --init --recursive

# Update to a newer commit/branch in the submodule
cd moneywiz-api
git fetch origin
git checkout <branch-or-commit>
cd ..
# Record the new submodule pointer in the parent repo
git add moneywiz-api
git commit -m "Bump moneywiz-api submodule"
```

Tips:

- After `git submodule update`, the submodule may be in a detached HEAD; `git checkout <branch>` before editing.
- Always commit the submodule pointer change in the parent repo after updating inside the submodule.

## Option B: Git Subtree (vendor code into this repo)

- Pros: One repository for everything; simpler for consumers (no submodules).
- Cons: Heavier parent history; manual subtree updates.

Commands (example):

```bash
git subtree add --prefix moneywiz-api <API_repo_url> main --squash
# Later updates
git subtree pull --prefix moneywiz-api <API_repo_url> main --squash
```

## Option C: Install from a Package (preferred for runtime)

If `moneywiz-api` is published (e.g., to PyPI), depend on a released version:

```bash
# requirements.txt
moneywiz-api==<version>

# or with uv
uv pip install moneywiz-api==<version>
```

- Pros: Clean dependency management; no repository coupling.
- Cons: Editing the API requires working in its own repo.

## Recommendation

- Default workflow: run `./moneywiz.sh --setup` to clone `https://github.com/marcomc/moneywiz-api.git` into `moneywiz-api/` and (optionally) add `upstream` → `https://github.com/ileodo/moneywiz-api`. Pull latest changes inside that folder as needed.
- Use Option C (package install) for CI or when you only need the published API.
- Use Option A (submodule) when you must pin both repos together and share that pointer with teammates.
