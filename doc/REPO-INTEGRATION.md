# Repository Integration

## Build-time relationship

This repository builds MoneyWiz Tools.app from three local components:

| Component | Role during build |
| --- | --- |
| Dispatcher scripts | Implement `moneywiz` commands and plans. |
| `moneywiz-api/` source | Supplies the read-only API shell and shared Python code. |
| Swift host source | Performs the verified live Core Data save. |

A complete checkout must include `moneywiz-api/` because the Make build
packages it into the app.

## Runtime relationship

After installation, the app bundle contains the runtime components it needs.
The `moneywiz` and `moneywiz-cli` symlinks resolve into that bundle, so normal
use does not depend on a Development-directory checkout or a pyenv
environment.

## Development boundaries

- Keep source-level changes in this repository and rebuild the bundle through
  Make.
- Treat `moneywiz-api` as the source packaged by this project, not as a
  separate runtime requirement for users.
- Do not add a second standalone writer app. The outer MoneyWiz Tools.app is
  the canonical host for the Swift writer and a future GUI.
- Keep live writer contracts narrow and evidence-backed; generic raw SQL
  helpers remain a different scope.
