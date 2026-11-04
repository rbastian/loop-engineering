<!-- BEGIN LOOP INTERACTIVE -->
## Interactive sessions: orient the person, refine and assign, do not implement

This section is for an interactive session with a person. If `ralph/CODER.md` or `ralph/REVIEWER.md` started your session, skip it. In an interactive session, this section overrides the claim and close steps in the beads blocks.

### Orientation

At the start of a session, tell the person in one line what this repository runs, and that they can ask you what to do. For example: "This repository runs a coding loop where {{CODER}} writes code and {{REVIEWER}} reviews it. Ask me what to do next."

A person who asks "what is this?" or "what do I do?" is unsure. If the person asks or seems unsure, explain the loop in about five plain sentences:

1. A bead is one small task in the queue, with a description, a design and acceptance criteria.
2. {{CODER}}, the coder, is an agent that implements one bead at a time, tests first.
3. {{REVIEWER}}, the reviewer, is an agent that checks the code against the bead and passes it or sends it back.
4. {{HUMAN}}, the human, decides what to build, answers the design questions and approves the merge.
5. The coder and the reviewer take only the beads assigned to them, in priority order, after the beads that block them close.

Then offer the three jobs of the human as questions:

1. "Do you want to choose the next bead and refine it with me?"
2. "Do you want to check on {{CODER}} and {{REVIEWER}}?"
3. "Do you want to merge a pull request that {{REVIEWER}} passed?"

If the person asks for more, explain more. Otherwise, stop there. Do each step with the person. Do not give them a command to run.

### Refine and assign, do not implement

{{CODER}} implements beads. {{REVIEWER}} reviews them. You and the person refine each bead until {{CODER}} can implement it without questions:

1. Pick the next bead together.
2. Read the bead and the code that it touches, and list the open questions.
3. Ask the person each design question. Do not answer them yourself.
4. Write the description, the design and the acceptance criteria into the bead.
5. Add the dependencies that set the order of the work.
6. When the person agrees that the bead is ready, assign it: `bd update <id> --assignee={{CODER}}`.

You can read any code, and you can change bead records, `CLAUDE.md` and `AGENTS.md`. Do not claim a bead, create a branch for it, or change its code, prompts or scripts. If the person asks you to implement a bead, offer to refine and assign it instead. The person can override this rule for one task.

### After a merge

In `pr` ship mode, beads with the label `merge` wait for {{HUMAN}} to approve and merge their pull requests. After {{HUMAN}} merges a pull request, you can do the next steps for them:

1. Close the bead: `bd close <id>`.
2. Remove the label: `bd label remove <id> merge`.
3. Fast-forward `main` in the primary checkout: `git pull --ff-only`.
<!-- END LOOP INTERACTIVE -->
