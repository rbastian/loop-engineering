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
CODER_ENGINE={{CODER_ENGINE}}
CODER_MODEL={{CODER_MODEL}}
REVIEWER_ENGINE={{REVIEWER_ENGINE}}
REVIEWER_MODEL={{REVIEWER_MODEL}}
BEAD_PREFIX={{BEAD_PREFIX}}
```

`$CODER` is the agent that implements beads. `$REVIEWER` is the agent that reviews them. Each name is the bead assignee that the agent's loop polls for. `$HUMAN` is the bd assignee for the human's queues: merge approval, acceptance and escalation. `BEAD_PREFIX` is the prefix of every bead ID in this project, and the watchers match bead IDs with it.

`CODER_ENGINE` and `REVIEWER_ENGINE` name the CLI that each agent's loop runs on. The coder runs on `claude` or `fw`, because its prompt uses the `/simplify` skill of Claude Code. The reviewer runs on `claude`, `codex` or `fw`. `fw` is a launcher that runs Claude Code on a Fireworks model. `CODER_MODEL` and `REVIEWER_MODEL` hold the model for the engine of that agent. An empty model gives the default of the engine: `claude-opus-5-5` for the coder on `claude`, `claude-sonnet-5-5` for the reviewer on `claude`, and the plan's default model on `codex`. `fw` has no default, so an agent on `fw` must have a model, for example `deepseek-flash-latest[1m]`.

## Ship mode

```bash
SHIP_MODE={{SHIP_MODE}}
GITHUB_ACCOUNT={{GITHUB_ACCOUNT}}
```

`SHIP_MODE` is `pr` or `local`. `pr` is the default. `$CODER` pushes each branch to `origin` and opens a pull request against `main`. `$REVIEWER` reviews the branch and comments on the pull request. `$HUMAN` approves and merges it. `$BASE` is `origin/main`.

`local` is only for a repository with one user and no shared remote. `$REVIEWER` merges the branch into `main` in the primary checkout, and no pull request exists. `$BASE` is `main`.

`GITHUB_ACCOUNT` is the GitHub account that `$CODER` and `$REVIEWER` use in `pr` mode, for every `gh` command and every push. It is usually `$HUMAN`'s own account. The agents do not use separate bot accounts. `run.sh` pins this account at start: it exports the account's token as `GH_TOKEN`, and it checks that an SSH push uses the same account. In `local` mode the field is empty.

### Remote actions in `pr` mode

This list is the only place that says what each role can do on the GitHub remote. An action that is not on the list is not allowed.

- `$CODER` can push its own `feat/` branches to `origin`. After a rebase, it pushes with `git push --force-with-lease`, never with a plain `--force`. It can open a pull request against `main` with `gh pr create`, and it can read pull requests with `gh pr view`.
- `$REVIEWER` can read pull requests with `gh pr view`, and it can post comments with `gh pr comment`. It does not push, approve, merge, close, edit or label a pull request on GitHub, and it does not delete branches. A GitHub account cannot approve its own pull request, so the review result is a comment, not `gh pr review --approve`.
- `$HUMAN` approves and merges pull requests, deletes remote branches, and changes anything else on the remote, for example the settings, the releases and the tags.
- No agent pushes to `main`, creates or deletes tags or releases, changes the repository settings, or closes a pull request that another author opened.

## Paths

```bash
PRIMARY={{PRIMARY}}
CODER_WORKTREE={{CODER_WORKTREE}}
REVIEWER_WORKTREE={{REVIEWER_WORKTREE}}
```

`PRIMARY` is the primary checkout, which belongs to `$HUMAN`. `CODER_WORKTREE` is the worktree of `$CODER`. `REVIEWER_WORKTREE` is the worktree of `$REVIEWER`.

There are no exceptions to the rule that agents do not write in the primary checkout.

## Tech stack

- {{Language and version, run through `uv`}}.
- {{Test and lint tools: pytest and ruff}}.
- {{Other tools or services the code uses}}.

## Key directories

- `src/`: {{the package}}.
- `tests/`: the pytest suite.
- `.loop/`: the loop scripts and prompts.

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

The reviewer always runs the default method for its engine. List here only the checks that add to it, chosen by the files that the branch changes.

{{List the extra review checks for each kind of change, or write "None"}}.
