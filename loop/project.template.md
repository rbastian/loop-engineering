# Project

This section gives the facts about this project. The prompt above refers to it as "the Project section". The prompt also uses names that this section defines, for example "the gate", `$PRIMARY` and `$CODER`.

## What the project is

{{One paragraph: what the project is and who uses it}}.

{{Out of scope: the files or directories that the loop must not change}}.

## Roles

```bash
CODER={{CODER}}
REVIEWER={{REVIEWER}}
HUMAN={{HUMAN}}
```

`$CODER` is the agent that implements beads. `$REVIEWER` is the agent that reviews them. Each name is the bead assignee that the agent's loop polls for. `$HUMAN` is the bd assignee for the human's queues: merge approval, acceptance and escalation.

## Ship mode

```bash
SHIP_MODE={{SHIP_MODE}}
```

`pr` is the default. `$CODER` pushes each branch to `origin` and opens a pull request against `main`. `$REVIEWER` reviews the branch and comments on the pull request. `$HUMAN` approves and merges it. `$BASE` is `origin/main`.

`local` is only for a repository with one user and no shared remote. `$REVIEWER` merges the branch into `main` in the primary checkout, and no pull request exists. `$BASE` is `main`.

## Paths

```bash
PRIMARY={{PRIMARY}}
CODER_WORKTREE={{CODER_WORKTREE}}
REVIEWER_WORKTREE={{REVIEWER_WORKTREE}}
```

There are no exceptions to the rule that agents do not write in the primary checkout.

## Tech stack

- {{Language and version, run through `uv`}}.
- {{Test and lint tools: pytest and ruff}}.
- {{Other tools or services the code uses}}.

## Key directories

- `src/`: {{the package}}.
- `tests/`: the pytest suite.
- `ralph/`: the loop scripts and prompts.

## Format commands and gate

Format commands:

```bash
uv run ruff format . && uv run ruff check --fix .
```

The gate:

```bash
uv run ruff format --check . && uv run ruff check . && uv run pytest -q
```

## External services

{{Name each external service, the variables or login it uses, and where they come from. If the project uses none, write "None"}}. If a bead needs a service and it is unavailable, follow "When Things Go Wrong".

## Review method (for the reviewer)

Use the default method for your engine. {{If some kinds of change need a different method, describe it here, chosen by the files that the branch changes}}.
