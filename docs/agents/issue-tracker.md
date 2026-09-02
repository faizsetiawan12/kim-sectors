# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues at `faizsetiawan12/kim-sectors`. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`.
- **Read an issue**: `gh issue view <number> --comments`.
- **List issues**: `gh issue list --state open`.
- **Comment on an issue**: `gh issue comment <number> --body "..."`.
- **Apply or remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`.
- **Close**: `gh issue close <number> --comment "..."`.

Infer the repository from the GitHub remote; `gh` does this automatically when run inside this clone.

## Pull requests as a triage surface

**No.** Pull requests are not treated as a request surface for triage.

When a skill says “publish to the issue tracker”, create a GitHub issue. When it says “fetch the relevant ticket”, run `gh issue view <number> --comments`.
