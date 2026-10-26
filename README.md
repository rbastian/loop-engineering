# loop-engineering

This repository holds the scripts and prompts that run coding agents as a headless team. The agents run on [Claude Code](https://claude.com/claude-code), and the reviewer can also run on [Codex](https://github.com/openai/codex). [Beads](https://github.com/gastownhall/beads) stores the task state and work queue between sessions.

The runner is reusable across projects. The supplied setup skill creates a Python project with uv, Ruff and pytest. It requires the primary checkout on `main`. A worktree is a separate checkout that shares the repository's Git history. The primary checkout belongs to the human.

The gate is the project's required validation command. Each project defines it in `ralph/project.md`. The default runs Ruff formatting checks, Ruff lint checks and pytest.

The core idea is to specify interactively and implement headlessly:

- A human breaks a specification into beads with an interactive agent. A bead is one work item in a graph of dependencies.
- The human and the agent refine each bead until its spec has no open questions.
- The human assigns the bead to the coder agent. A shell loop starts fresh headless sessions, each limited to one bead. The coder implements the bead test-first on a feature branch.
- The coder hands the bead to the reviewer agent. The reviewer checks the branch against the spec. By default the coder opens a pull request, and the human approves and merges it.
- Each session reads the bead, the role prompt, the project configuration and the repository. Beads records task progress and handoffs between sessions.

## Prerequisites

You need these tools for every project:

- [Claude Code](https://claude.com/claude-code) CLI (`claude`), authenticated. It runs the coder and, by default, the reviewer. It also runs the setup skill.
- [Beads](https://github.com/gastownhall/beads) (`bd`), installed system-wide.
- `git`, with a name and email configured for commits.
- [uv](https://docs.astral.sh/uv/). The setup skill makes a uv project with ruff and pytest, and `watch.py` runs through uv.
- `jq`. `run.sh` and the setup scripts read JSON with it.

Make sure that `/simplify` is available in the coder's Claude Code session. A Claude Code reviewer also needs `/code-review`. The watcher requires Python 3.13 or later and Rich. Running it directly with `uv run ralph/watch.py` reads its script metadata and supplies these dependencies.

You need these tools for some features:

- [GitHub CLI](https://cli.github.com/) (`gh`), authenticated, and an `origin` remote on GitHub. You need both for `pr` mode. Make sure that the active `gh` account can open pull requests on the repository.
- [Codex](https://github.com/openai/codex) CLI (`codex`), authenticated. You need it only for a reviewer on Codex. Before the first headless Codex session, open `codex` once in the primary checkout, trust the project and approve its hooks.
- [herdr](https://herdr.dev/), a terminal multiplexer for coding agents. The setup skill's last step (`layout.sh`) uses it. It starts both loops in a tab of their own, with both watchers and a Beads pane beside your session. Without herdr, start the loops and watchers by hand, as [loop/README.md](loop/README.md) shows.
- GNU `timeout`, for the time limit on each session. On macOS, run `brew install coreutils`. Without it, sessions have no time limit.

## Get started

1. Install the setup skill. Run this command from the root of your clone:

   ```bash
   mkdir -p ~/.claude/skills
   ln -s "$(pwd)/skills/dev-env-setup" ~/.claude/skills/dev-env-setup
   ```

   The skill finds `loop/` relative to its own folder, so the link works from any clone of this repository.

2. Review the setup changes before you start. Bootstrap adds Python development dependencies and runs formatting and lint fixes. The worktree script stages and commits all current changes. In `pr` mode, it also pushes `main` to `origin`. Make sure that the target project contains only changes you intend to commit.

   In a Claude Code session in the new project, inside herdr, type `/dev-env-setup`. The skill asks for the bead prefix, the ship mode, the human who approves merges, the agent names and the reviewer's engine. Then it sets up git, uv, beads, the `ralph/` folder and both worktrees, and starts the loops.

3. Break your specification into beads, as [From specification to beads](#from-specification-to-beads) explains.

4. Do the spec ritual on the first ready bead. In an interactive session, enter:

   > Read bead `<id>`. Ask me questions about the spec, one round at a time, until you have no questions left. Then update the bead's design field with the final spec.

   This step carries the most weight. Each question that you answer here is a guess that a headless agent does not make later.

5. Assign the bead to the coder:

   ```bash
   bd update <id> --assignee=Ralph
   ```

   Use the coder name from `ralph/project.md` if you changed the default.

6. In `pr` mode, watch the `merge` label. Each bead with that label has a reviewed pull request. Approve and merge the pull request, then run `bd close <id>` and remove the label.

To set up a project without the skill, follow the manual steps in [loop/README.md](loop/README.md#install-in-a-project).

## Why

### The problem

A large specification can outlast one agent session. Plans and decisions in the conversation become harder to recover as the context fills. Compaction replaces conversation history with a summary and can lose details.

### The dependency graph

The human and an interactive agent break the specification into beads before implementation. Each bead describes one step small enough for a coding session. Dependencies identify the steps that need another step's code on `main` first.

The human reviews the graph before implementation makes changes expensive. `bd ready` shows work whose dependencies are closed. Closing a bead only after its code reaches `main` keeps dependent work in order.

### Fresh sessions and recovery

Each headless session works on one bead and then exits. A bead can need several sessions for implementation, review, fixes or recovery. Small beads and fresh sessions reduce reliance on compaction. The runner does not enforce a context budget or prevent compaction.

Bead notes record the branch, checkpoint commits and handoffs. Later sessions use those notes and the saved Git state to resume work. Recovery depends on what the previous session saved and recorded.

### A record for later work

A bead is not only a task. As the work goes on, the bead collects the record of that work:

- The design, with requirements, acceptance criteria and constraints that the change must preserve. The prompts call these constraints the trap list.
- The branch, each checkpoint commit and the pull request.
- Each review round, with the blocking findings, the disputed findings and the non-blocking findings.

Feature commits and normal checkpoint commits include the bead ID. Feature commits use the form `feat: <description> [<bead-id>]`. Months later, an agent that fixes a bug or adds a feature can go from `git log` or `git blame` to the bead that made the code. From the bead it learns why the code has its shape and what the reviewer already checked. A commit history alone cannot tell it that.

### Sources

Two writeups shaped this setup:

- Steve Yegge, [Introducing Beads](https://steve-yegge.medium.com/introducing-beads-a-coding-agent-memory-system-637d7d92514a). Replace prose plans with a dependency graph of issues that agents query (`bd ready`). A fresh session gets its bearings in seconds, and discovered work goes into a new bead instead of getting lost.
- Geoffrey Huntley, [everything is a ralph loop](https://ghuntley.com/loop/). Run the agent in a loop, one task per iteration. Put your engineering effort into watching the loop and removing each class of failure for good.

Beads holds the what, and the loop provides the how. The human owns the specification, the merge and the loop's failure modes.

## What's here

| Path | Purpose |
|------|---------|
| `loop/` | The multi-agent loop: `run.sh`, the coder and reviewer prompts, the project overlay template, and the watcher `watch.py`. See [loop/README.md](loop/README.md). |
| `skills/dev-env-setup/` | A Claude Code skill that installs `loop/` into a project and starts the agents in herdr. |

## Roles and agents

The loop has three roles: CODER, REVIEWER and HUMAN. Outside the loop, an interactive agent helps the human specify work.

| Role | Runs on | Responsible for |
|------|---------|-----------------|
| Interactive agent | Claude Code or Codex, in a normal interactive session | Breaking a specification into beads with the human, and the spec ritual on each bead. |
| CODER (default name Ralph) | Claude Code, headless | Claiming a bead, writing tests first, implementing, running the gate, opening the pull request in `pr` mode, and handing the bead to the reviewer. |
| REVIEWER (default name Alice) | Claude Code or Codex, headless | Reviewing the branch against the bead's design, running a code review and the gate. It passes the bead on, returns it to the coder with findings, or escalates it to the human. In `local` mode it also merges. |
| HUMAN | You | Writing the specification, answering the agent's questions, assigning beads, approving and merging pull requests, and settling escalations. |

The coder needs Claude Code, because its prompt uses the `/simplify` skill. The reviewer uses the `/code-review` skill on Claude Code and `codex exec review` on Codex. A reviewer on Codex reads the diff with a different model family from the coder's.

Each project names its agents and the human in `ralph/project.md`, so you can rename them. The agent prompts refer to roles, not to fixed names. You can add more agent roles over time. [loop/README.md](loop/README.md) tells you how.

## How the loop works

Each headless agent is the same `run.sh` with its own prompt and its own git worktree. The loop for an agent polls Beads for beads assigned to that agent's name, and starts sessions that each work on one bead. To hand a bead on, a session changes the assignee. `RALPH_ENGINE` selects the agent CLI for each loop: `claude` (the default) or `codex`.

## The review cycle

A bead can go back and forth between the coder and the reviewer. The bead notes carry every message between them. Each note is a line in an append-only log, and the last status note tells the next session what to do.

1. The coder finishes the bead and hands it to the reviewer with the note `Handed to <reviewer> for review`.
2. The reviewer starts review round 1. It reads the bead's design, the diff and the coder's notes, runs a code review, and runs the gate.
3. If the review finds no blocking problem, the bead passes. Then the ship mode decides what happens next.
4. If the review finds a blocking problem, the reviewer returns the bead to the coder. It writes one `Review round 1 failed:` note per problem, then the note `Returned to <coder> after review round 1`. Then it assigns the bead back to the coder. In `pr` mode it also posts the findings as a comment on the pull request.
5. The coder's next session finds the bead in its queue. The coder fixes only the listed problems, runs the gate again and hands the bead back for round 2.
6. If round 2 passes, the bead passes. If round 2 fails, the reviewer does not return the bead again. It escalates the bead to the human with the note `Escalated to <human> after review round 2` and the label `escalated`.

These findings are blocking:

- A bug.
- A departure from the bead's design or acceptance criteria.
- A test that was deleted, skipped or weakened.
- New behavior with no test.
- A failing gate.
- In `pr` mode, a pull request whose head is not the commit that the reviewer reviewed.

All other findings are non-blocking. The reviewer writes all non-blocking findings in one `Non-blocking review findings:` note for the human, and they never stop the bead.

If the coder thinks that a finding is wrong, the coder does not change that code. It writes a `Disputed finding:` note with the reason. The reviewer judges the dispute in round 2. If the reviewer still holds the finding blocking, the bead goes to the human.

A merge conflict also sends the bead back to the coder, with the note `Rebase needed:`. The coder rebases the branch, runs the gate and hands the bead back. A rebase does not count as a review round.

The limit of one return keeps the two agents from passing a bead back and forth without end. A second disagreement needs a human decision.

## Ship modes

The ship mode decides what happens after a review passes. Each project sets it in `ralph/project.md`.

`pr` is the default. The coder pushes the branch and opens a pull request. The reviewer posts the review as a comment, and the human approves and merges the pull request. Use this mode for every repository that more than one person works in.

`local` is for a repository with one user. The reviewer merges the branch into `main` in the primary checkout, without requiring a remote or opening a pull request. After merging, the reviewer closes the bead and assigns it to the human with the label `accept`.

## From specification to beads

This repository does not write specifications. A specification comes from the human: a document, or the human's own description of what to build. The loop starts after the human and the interactive agent turn the specification into beads.

The breakdown makes a graph. The epic stands for the whole specification. Each child bead is one implementation step that one coder session can finish. A dependency between two beads means that one step needs the other step's code on `main` first. `bd ready` shows only the beads whose dependencies are closed, so the coder takes the steps in a correct order.

To break a specification into beads, open an interactive Claude Code or Codex session in the project and enter a prompt like this one:

> Read the specification in `<file>` (or: here is what I want to build: ...). Break it into beads. Create one epic for the whole specification. Under it, create one child bead per implementation step, small enough for one coding session. Give each child a description, a design and acceptance criteria. Add a dependency wherever one step needs another step's code first. Before you create anything, ask me about each gap in the specification. Do not assign any bead. When you finish, show me the graph.

These `bd` commands do the work. The agent knows them, but you can also run them yourself:

```bash
bd create --type=epic --title="<specification name>" --description="<summary>"
bd create --parent=<epic-id> --title="<step>" --description="..." --design="..." --acceptance="..."
bd dep add <step-id> <step-it-depends-on>
bd graph <epic-id>
bd ready
```

Read the graph before you go on. Each bead must contain enough context to implement independently.

## Human queues and operations

The human handles the `merge`, `accept` and `escalated` queues. See [Rules of engagement](loop/README.md#rules-of-engagement) for the queue workflow and merge preconditions.

See [Operations](loop/README.md#operations) for stopping and restarting loops, finding logs and updating an installed harness. Bootstrap preserves existing harness files and does not upgrade them. A rerun still runs `uv add --dev`, `ruff format .` and `ruff check --fix .`, which can change project files. In `local` mode, modified tracked files prevent the reviewer from merging until the human resolves those changes.

## Design notes

- One bead per session, then exit. A later session can resume the same bead.
- The status of a bead follows `main`. The rule for closing a bead is that its code must be on `main`. Dependent beads become ready only after the close.
- Crash recovery uses checkpoint commits, saved files and breadcrumb notes on the bead (`Branch created: …`, `Checkpoint committed: …`, `PR opened: …`). Record progress so the next session can resume it.
- Implementation discoveries become beads: bugs, unrelated work and required subtasks. Review findings stay in the current bead's notes for review and human triage.
- `BEADS_ACTOR` matters. `run.sh` sets it to the agent name. Without it, `bd update --claim` fails because the actor does not match the bead's assignee.

## Safety

Headless sessions skip all permission prompts. Claude Code runs with `--dangerously-skip-permissions`, and Codex runs with `--dangerously-bypass-approvals-and-sandbox`. Run each agent in its own worktree, with credentials scoped as tightly as you can. In `pr` mode, the human approves every merge to `main`. In `local` mode, the reviewer and the gate are the only checks between the agents and `main`. Use `local` mode only on a repository where you accept that.

## Contributing

The watcher tests are in `loop/tests/`. Run them with the command in [Tests](loop/README.md#tests). For documentation changes, make sure that commands and descriptions match the scripts and prompts.

## History

The first version of this repository ran one agent that shipped through a pull request and auto-merge. Its files (`run.sh` and `PROMPT_TEMPLATE.md` at the root) and the talk material from the AI Guild demo are in commit `194238a`.

## Credits

The process comes from Steve Yegge's Beads posts and Geoffrey Huntley's ralph-loop writing. Claude Code reviewed and hardened it. The commit history records the bugs found along the way. Those bugs are a good argument to review your automation like production code.
