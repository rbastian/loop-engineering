# loop-engineering

This repository holds the scripts and prompts that run [Claude Code](https://claude.com/claude-code) as a team of headless agents. [Beads](https://github.com/gastownhall/beads) is the agents' memory and work queue.

The core idea is to specify interactively and implement headlessly:

- A human and an agent refine a work item (a "bead") together until the spec has no open questions.
- The human assigns the bead to the coder agent. A shell loop starts a fresh headless session for each bead. The coder implements the bead test-first on a feature branch.
- The coder hands the bead to the reviewer agent. The reviewer checks the branch against the spec. By default the coder opens a pull request, and a human approves and merges it.
- Each session starts with a clean context window and gets its bearings from the bead database alone. No markdown plan and no session memory exist to decay.

## Why

Coding agents have no memory between sessions, and their markdown plans rot. Plans spawn sub-plans, compactions erase the outer context, and the agent notices problems and then forgets them. Two writeups shaped this setup:

- Steve Yegge, [Introducing Beads](https://steve-yegge.medium.com/introducing-beads-a-coding-agent-memory-system-637d7d92514a). Replace prose plans with a dependency graph of issues that agents query (`bd ready`). A fresh session gets its bearings in seconds, and discovered work goes into a new bead instead of getting lost.
- Geoffrey Huntley, [everything is a ralph loop](https://ghuntley.com/loop/). Run the agent in a loop, one task per iteration. Put your engineering effort into watching the loop and removing each class of failure for good.

Beads holds the what, and the loop provides the how. The human owns the spec, the merge and the loop's failure modes.

## What's here

| Path | Purpose |
|------|---------|
| `loop/` | The multi-agent loop: `run.sh`, the coder and reviewer prompts, the project overlay template, and the watcher `watch.py`. See [loop/README.md](loop/README.md). |
| `skills/dev-env-setup/` | A Claude Code skill that installs `loop/` into a project and starts the agents. |
| `docs/` | The talk material from the AI Guild demo. It describes the earlier single-agent version. |

## How the loop works

Each agent is the same `run.sh` with its own prompt and its own git worktree. The loop for an agent polls Beads for beads assigned to that agent's name, and starts one headless session per bead. To hand a bead on, a session changes the assignee.

The loop has three roles: CODER, REVIEWER and HUMAN.

- The coder (default name Ralph) is an agent. It claims a bead, writes tests first, implements, runs the gate and hands the bead to the reviewer.
- The reviewer (default name Alice) is an agent. It reads the branch against the bead's design and runs a code review and the gate. Then it passes the bead or returns it once.
- The human specs each bead, approves and merges pull requests, and settles escalations.

Each project names its agents and the human in `ralph/project.md`, so you can rename them. The agent prompts refer to roles, not to fixed names. You can add more agent roles over time. [loop/README.md](loop/README.md) tells you how.

## Ship modes

The ship mode decides what happens after a review passes. Each project sets it in `ralph/project.md`.

`pr` is the default. The coder pushes the branch and opens a pull request. The reviewer posts the review as a comment, and the human approves and merges the pull request. Use this mode for every repository that more than one person works in.

`local` is for a repository with one user. The reviewer merges the branch into `main` in the primary checkout, with no remote and no pull request.

## Prerequisites

- [Claude Code](https://claude.com/claude-code) CLI, authenticated.
- [Beads](https://github.com/gastownhall/beads) (`bd`), installed system-wide.
- `git`, `uv` and `jq`.
- For `pr` mode: the [GitHub CLI](https://cli.github.com/) (`gh`), authenticated, and an `origin` remote.
- GNU `timeout` for the time limit on each session (macOS: `brew install coreutils`). It is optional.
- For the setup skill's last step: herdr.

## Get started

1. Install the setup skill. Run this command from the root of your clone:

   ```bash
   ln -s "$(pwd)/skills/dev-env-setup" ~/.claude/skills/dev-env-setup
   ```

   The skill finds `loop/` relative to its own folder, so the link works from any clone of this repository.

2. In a Claude Code session in the new project, type `/dev-env-setup`. The skill asks for the bead prefix, the ship mode, the human who approves merges and the agent names. Then it sets up git, uv, beads, the `ralph/` folder and both worktrees, and starts the loops.

3. Do the spec ritual on a bead. In an interactive Claude Code session, enter:

   > Read bead `<id>`. Ask me questions about the spec, one round at a time, until you have no questions left. Then update the bead's design field with the final spec.

   This step carries the most weight. Each question that you answer here is a guess that a headless agent does not make later.

4. Assign the bead to the coder:

   ```bash
   bd update <id> --assignee=Ralph
   ```

5. In `pr` mode, watch the `merge` label. Each bead with that label has a reviewed pull request. Approve and merge the pull request, then run `bd close <id>` and remove the label.

To set up a project without the skill, follow the manual steps in [loop/README.md](loop/README.md).

## Design notes

- One bead per session, then exit. Sessions are disposable. The agent always works near the start of its context window, where it makes its best decisions and takes the fewest shortcuts.
- The status of a bead follows `main`. The rule for closing a bead is that its code must be on `main`. Dependent beads become ready only after the close.
- A crashed session leaves enough to resume. Checkpoint commits and breadcrumb notes on the bead (`Branch created: …`, `Checkpoint committed: …`, `PR opened: …`) let the next session continue the work.
- Discovered work goes into Beads. Bugs and unrelated work become new beads. Subtasks in scope become child beads, never prose notes.
- `BEADS_ACTOR` matters. `run.sh` sets it to the agent name. Without it, `bd update --claim` fails because the actor does not match the bead's assignee.

## Safety

Headless sessions run with `--dangerously-skip-permissions`. Run each agent in its own worktree, with credentials scoped as tightly as you can. In `pr` mode, the human approves every merge to `main`. In `local` mode, the reviewer and the gate are the only checks between the agents and `main`. Use `local` mode only on a repository where you accept that.

## History

The first version of this repository ran one agent that shipped through a pull request and auto-merge. Its files (`run.sh` and `PROMPT_TEMPLATE.md` at the root) are in commit `194238a`. The talk material in `docs/` describes that version.

## Credits

The process comes from Steve Yegge's Beads posts and Geoffrey Huntley's ralph-loop writing. Claude Code reviewed and hardened it. The commit history records the bugs found along the way. Those bugs are a good argument to review your automation like production code.
