# Project

This section gives the facts about this project. The prompt above refers to it by the names "the Project section", "the gate", "the format commands", "your worktree" and `$PRIMARY`.

## What the project is

{{One paragraph: what the project is and who uses it}}.

{{Out of scope: the files or directories that the loop must not change}}.

## Paths

```bash
PRIMARY={{PRIMARY}}
RALPH_WORKTREE={{RALPH_WORKTREE}}
ALICE_WORKTREE={{ALICE_WORKTREE}}
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

## Review method (for Alice)

Use the default method for your engine. {{If some kinds of change need a different method, describe it here, chosen by the files that the branch changes}}.
