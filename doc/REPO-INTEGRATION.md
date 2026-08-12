# Repository Integration

## Build-time relationship

This repository builds MoneyWiz Tools.app from three product components and a
locked dependency graph:

| Component | Role during build |
| --- | --- |
| Dispatcher scripts | Implement `moneywiz` commands and plans. |
| `pyproject.toml` and `uv.lock` | Pin the read-model API and its dependencies. |
| Swift host source | Performs the verified live Core Data save. |

A complete checkout must include the committed lockfile. The Make build
installs the pinned dependency graph rather than copying a nested API checkout.

## Runtime relationship

After installation, the app bundle contains the runtime components it needs.
The `moneywiz` symlink resolves into that bundle, so normal use does not
depend on a Development-directory checkout or a pyenv environment.

## Development boundaries

- Keep source-level changes in this repository and rebuild the bundle through
  Make.
- Keep generic, upstreamable read-model changes in the separate
  `marcomc/moneywiz-api` fork. It is a pinned source dependency, not an
  end-user product or bundled nested checkout.
- Do not add a second standalone writer app. The outer MoneyWiz Tools.app is
  the canonical host for the Swift writer and a future GUI.
- Keep live writer contracts narrow and evidence-backed; generic raw SQL is
  not a product write path.
