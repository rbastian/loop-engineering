# Project

This section gives the facts about this project. The prompt above refers to it as "the Project section". The prompt also uses names that this section defines, for example "the gate", `$PRIMARY` and `$CODER`.

## What the project is

loop-engineering holds the scripts and prompts that run two headless coding agents, a coder and a reviewer, as a team that works through a beads queue. Developers install it into their own projects with the dev-env-setup skill. This repository also runs the loop on itself, so the files in `.loop/` are an installed copy of the files in `loop/`.

Do not change `.loop/`. It is the installed copy that runs this loop, and the human updates it from `loop/` after a merge. Make every harness change in `loop/` or `skills/`. Do not change `.beads/`, `.claude/`, `.codex/` or `.agents/`, and do not change the beads section of `CLAUDE.md` or `AGENTS.md`. `bd setup` writes those

## Roles

```bash
CODER=Ralph
REVIEWER=Alice
HUMAN=Rob Bastian
REVIEWER_ENGINE=claude
BEAD_PREFIX=lpe
```

`$CODER` is the agent that implements beads. `$REVIEWER` is the agent that reviews them. Each name is the bead assignee that the agent's loop polls for. `$HUMAN` is the bd assignee for the human's queues: merge approval, acceptance and escalation. `REVIEWER_ENGINE` is the CLI that the reviewer's loop runs on: `claude` or `codex`. The coder always runs on `claude`. `BEAD_PREFIX` is the prefix of every bead ID in this project, and the watchers match bead IDs with it.

## Ship mode

```bash
SHIP_MODE=pr
GITHUB_ACCOUNT=rbastian
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
PRIMARY=/Users/robert.bastian/github.com/rbastian/loop-engineering
CODER_WORKTREE=/Users/robert.bastian/github.com/rbastian/loop-engineering-ralph
REVIEWER_WORKTREE=/Users/robert.bastian/github.com/rbastian/loop-engineering-alice
```

`PRIMARY` is the primary checkout, which belongs to `$HUMAN`. `CODER_WORKTREE` is the worktree of `$CODER`. `REVIEWER_WORKTREE` is the worktree of `$REVIEWER`.

There are no exceptions to the rule that agents do not write in the primary checkout.

## Tech stack

- Bash for `loop/run.sh` and the setup scripts in `skills/dev-env-setup/scripts/`. They must run on macOS bash 3.2 and BSD tools.
- Python 3.13 for `loop/watch.py`, run through `uv`. It uses Rich.
- Markdown for the prompts (`loop/CODER.md`, `loop/REVIEWER.md`, `loop/project.template.md`), the skill (`skills/dev-env-setup/SKILL.md`) and the READMEs
- pytest and ruff. The tests are in `loop/tests/` and cover `watch.py`. No tests cover `run.sh` or the setup scripts yet
- The scripts call `bd`, `git`, `gh`, `jq`, `claude`, `codex`, `herdr` and `timeout`/`gtimeout`

## Key directories

- `loop/`: the harness source: `run.sh`, `watch.py`, the role prompts and the project template.
- `loop/tests/`: the pytest suite for `watch.py`.
- `skills/dev-env-setup/`: the setup skill and its scripts.
- `.loop/`: the installed copy that runs this loop. Out of scope.

## Format commands and gate

Format commands:

```bash
uv run ruff format . && uv run ruff check --fix .
```

The gate:

```bash
uv run ruff format --check . && uv run ruff check . && uv run pytest -q \
  && printf '%s\n' loop/run.sh skills/dev-env-setup/scripts/*.sh | xargs -n1 bash -n
```

## External services

GitHub, through `gh` as the account `rbastian` and `git` over the `origin` remote. The human logs in. The code under test calls no service. If a bead needs a service and it is unavailable, follow "When Things Go Wrong".

## Review method (for the reviewer)

Always run the default method for your engine on every branch: the `/code-review` skill at high effort on `claude`, or `codex exec review` on `codex`. The checks below add to that method. They never replace it. In the `Review summary:` note, give the number of findings that the default method returned.

If the branch changes `loop/run.sh` or a script in `skills/dev-env-setup/scripts/`, no test covers it, so read the diff line by line for bash 3.2 and BSD portability, quoting and `set -euo pipefail` traps. Run the changed path by hand in a scratch git repository when you can do so without the network. If the branch changes a prompt, check that `loop/README.md` and the top-level `README.md` still agree with it.
