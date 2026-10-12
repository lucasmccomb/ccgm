---
description: Explain a topic in the lowest medium that carries it - prose, diagram, page, or video - then verify the artifact and summarize in 5 lines or fewer
allowed-tools: Read, Glob, Grep, Write, Bash, Skill
argument-hint: "<topic> [as prose|diagram|page|video]"
---

# /explain - Explain Something in the Right Medium

Explain `$ARGUMENTS`. Read what you need, pick the medium, produce it, check it, and finish with a short summary.

## Step 1: Parse

Split `$ARGUMENTS` at the last ` as ` followed by `prose`, `diagram`, `page`, or `video`. Everything before it is the topic. With no `as`, you pick the medium in Step 3. With no topic, ask what to explain.

## Step 2: Read

Read the code or docs the topic needs. Stop when you can explain it from what you read. Do not survey the repo.

## Step 3: Pick the Medium

Honour `as` when given. Otherwise pick the lowest rung that carries the content:

| Content | Medium |
|---|---|
| A fact, result, decision, or short explanation | prose |
| A flow, sequence, dependency, state machine, architecture, or before/after | diagram |
| More than 5 items on more than 3 attributes, a long report, data to chart, anything that needs filters | page |
| A new concept the operator wants to build intuition for | video, only with `as video` |

Load the `output-medium` skill before you draw a diagram or write a page. It holds the conventions for each medium.

## Step 4: Produce and Check

- **prose**: write plain sentences. No file.
- **diagram**: ASCII in a fenced block for the terminal, 100 columns or fewer, with a one-line caption. Check the width. Use Mermaid only when the destination is GitHub, and check it with `npx -y @mermaid-js/mermaid-cli` when `npx` exists.
- **page**: with the Artifact tool, follow its publish guidance. Without it, write the content as markdown and run `"${CCGM_BIN:-$HOME/.claude/bin}/ccgm-md-page" FILE.md`. If that file is missing, print a one-line note and give the markdown path. Never open the page.
- **video**: use the `explainer-video` module when it is installed. When it is missing, say so in one line and offer a page instead. Do not build a page unasked.

## Step 5: Finish

End with a summary of 5 lines or fewer in plain prose: the answer first, then the path or link to the diagram file or page. The prose answer comes before any artifact.
