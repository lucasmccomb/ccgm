---
name: ideate
description: >
  Structured ideation framework that interviews the user to refine a loose idea into a concrete, actionable concept.
  Uses Socratic questioning, progressive refinement, and confidence tracking to reach 95% clarity before confirming.
  Can delegate to /deepresearch for validation and /xplan for planning once the idea is locked.
  Triggers: ideate, brainstorm, flesh out idea, refine idea, explore idea, think through, help me figure out
disable-model-invocation: true
---

# /ideate - Idea Refinement Through Structured Interview

Takes a loose, half-formed idea and interviews you until the concept is sharp enough to act on. Tracks confidence across multiple dimensions, loops until 95% clarity, then confirms the final concept with you.

## Usage

```
/ideate "I want to build an app that helps people track habits"
/ideate "some kind of AI tool for real estate"
/ideate                                          # Asks what you're thinking about
/ideate --resume                                 # Resume a saved ideation session
```

## Instructions

### Phase 0: Setup & Initial Capture

#### 0.1 Parse Input

Extract from `$ARGUMENTS`:
- **Seed idea**: Whatever the user typed (can be vague, that's the point)
- **`--resume`**: Resume a prior session from `~/.claude/ideation/`

If no arguments provided, ask:

> "What's rattling around in your head? Give me whatever you've got - a sentence, a word, a half-baked concept. The vaguer the better, that's what this is for."

#### 0.2 Create Session Directory

```
slug = kebab-case(seed idea, max 40 chars)
timestamp = YYYYMMDD-HHMM
session_dir = ~/.claude/ideation/{timestamp}-{slug}/
mkdir -p {session_dir}
```

#### 0.3 Initialize Session State

Create `{session_dir}/session.md` with:

```markdown
# Ideation Session: {seed idea}
Started: {timestamp}
Status: in-progress

## Seed
{raw user input}

## Interview Log
{will be appended as the interview progresses}

## Confidence Tracker
| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem | 0/10 | |
| Audience | 0/10 | |
| Solution | 0/10 | |
| Scope | 0/10 | |
| Differentiation | 0/10 | |
| Feasibility | 0/10 | |
| Motivation | 0/10 | |
| **Overall** | **0%** | |
```

#### 0.4 Resume Handling

If `--resume` was passed:
1. Find the most recent session in `~/.claude/ideation/` with `Status: in-progress`
2. Read the full `session.md`
3. Reconstruct the confidence state and pick up where you left off
4. Tell the user what you remember and what's still unclear

---

### Phase 1: The Interview

This is the core loop. You are a skilled product thinker and strategist having a conversation, not a survey bot reading from a list. The goal is to reach 95% confidence across all dimensions.

#### Interview Principles

1. **One to two questions at a time.** Never dump a list of questions. Each question should feel like the natural next thing to ask given what you just learned.

2. **Listen more than you talk.** When the user answers, reflect back what you heard in your own words before asking the next question. This catches misunderstandings early.

3. **Follow the energy.** If the user lights up about a specific aspect, go deeper there even if it's out of order. Rigid structure kills good ideation.

4. **Challenge gently.** If something sounds like it won't work, don't just nod. Push back with "What if..." or "Have you considered..." or "The tricky part there is..."

5. **Offer concrete examples.** When a concept is abstract, ground it: "So like, if I'm a user and I open the app, I'd see... what exactly?"

6. **Name what's unclear.** Be transparent: "I think I understand the who and the what, but I'm fuzzy on why this needs to exist when X already does Y."

7. **Use AskUserQuestion for structured choices.** When you identify 2-4 distinct directions, present them as options rather than open-ended questions. This helps the user crystallize their thinking.

8. **Synthesize periodically.** Every 3-4 exchanges, give a brief synthesis: "Here's what I'm hearing so far..." This keeps the conversation grounded and gives the user a chance to correct course.

#### Confidence Dimensions

Track these internally. Update after each exchange. You do NOT need to show the scores to the user unless they ask.

| Dimension | What You Need to Know | 95% Means... |
|-----------|----------------------|---------------|
| **Problem** | What pain/need/desire does this address? | You can articulate the problem in one sentence that the user agrees with |
| **Audience** | Who specifically has this problem? | You can describe the target user persona with enough detail to find them |
| **Solution** | What does the thing actually do? | You can describe the core experience/workflow in concrete terms |
| **Scope** | What's in v1, what's not? | Clear MVP boundary - you know what to build first and what to defer |
| **Differentiation** | Why this over existing alternatives? | You can explain the unique angle in a way that's not hand-wavy |
| **Feasibility** | Can this actually be built/done? | You have a rough sense of technical approach, timeline, and constraints |
| **Motivation** | Why does the user care about this? | You understand the personal/business driver behind the idea |

#### Interview Flow (Adaptive, Not Rigid)

The interview adapts based on what the seed idea reveals. Start with whatever dimension is most unclear from the seed.

**Opening move**: Parse the seed idea. What do you already know? What's the biggest gap? Start there.

For example:
- "I want to build a habit tracker app" - You know the solution category but not the problem, audience, or differentiation. Start with: "What's broken about existing habit trackers for you?"
- "Something for real estate" - You know the domain but almost nothing else. Start with: "Are you thinking about something for buyers, sellers, agents, investors... who's the person you want to help?"
- "AI" - You know nothing. Start with: "What problem are you running into that made you think AI might help?"

**Mid-interview techniques**:

- **The "magic wand" question**: "If this existed exactly as you imagine it, what would change for the user? What's different about their life/work?"
- **The "day in the life" question**: "Walk me through how someone would actually use this. They wake up, they... what?"
- **The "competitor autopsy" question**: "What have you tried that's close but not right? What specifically fell short?"
- **The "friend test" question**: "If you had to explain this to a friend in one sentence over drinks, what would you say?"
- **The "kill test" question**: "What would make you abandon this idea? What would have to be true for this to not be worth doing?"

**When confidence stalls on a dimension**:

If a dimension stays below 6/10 after 2-3 questions, try a different angle:
- Offer a concrete hypothesis for the user to react to (easier than generating from scratch)
- Give 2-3 options that represent different directions
- Ask about a related dimension - sometimes the answer to "who" clarifies "what"

#### Tool Integration During Interview

The user may ask you to pull in other tools during ideation. Common requests:

- **"Research this"** or **"What exists already?"** - Use the Skill tool to invoke `/deepresearch` with a focused query derived from the current ideation state. After research returns, incorporate findings into the interview.

- **"Search for X"** - Use WebSearch directly for quick lookups during the conversation.

- **"Check if X exists"** - Use WebSearch to verify.

- **"Look at competitor Y"** - Use WebFetch or browser tools to analyze a specific product.

After any tool usage, synthesize what you learned and update your confidence scores. Continue the interview.

#### Logging

After each exchange (your question + user's answer), append to `{session_dir}/session.md`:

```markdown
### Q{N}: {your question summary}
**Asked**: {the actual question}
**Answer**: {user's response, paraphrased}
**Insight**: {what this revealed}
**Confidence update**: {which dimensions changed and why}
```

---

### Phase 2: Confidence Check Loop

After each exchange, evaluate overall confidence:

```
overall = average of all 7 dimension scores / 10 * 100
```

**If overall < 70%**: Continue interviewing. Focus on the lowest-scoring dimensions.

**If overall 70-89%**: Tell the user where you are:
> "I'm getting a solid picture. I'm at about {X}% clarity. The parts I'm still fuzzy on are {list dimensions below 8}. A few more questions..."

**If overall 90-94%**: You're close. Ask one or two final clarifying questions on the weakest remaining dimension.

**If overall >= 95%**: Move to Phase 3.

**Stuck detection**: If you've asked 15+ questions and confidence hasn't crossed 70%, pause and tell the user:
> "We've been going back and forth for a while and I'm still at {X}% clarity. Here's what's still unclear: {list}. Would you like to: (1) Keep going on these specific gaps, (2) Accept the ambiguity and lock what we have, or (3) Run /deepresearch to see if external research helps clarify?"

---

### Phase 3: Synthesis & Confirmation

When confidence hits 95%, synthesize everything into a **Concept Brief**.

#### 3.1 Draft the Concept Brief

Write to `{session_dir}/concept.md`:

```markdown
# Concept Brief: {concept name}

## One-Liner
{One sentence that captures the whole idea - the "friend at a bar" version}

## Problem
{The specific pain/need/desire this addresses, grounded in real scenarios}

## Target Audience
{Who this is for, described concretely enough to find them}

## Solution
{What it does, described as a user experience, not a feature list}

### Core Experience
{The primary workflow or interaction, step by step}

### Key Capabilities (v1)
{Bulleted list of what's in scope for v1}

### Explicitly Deferred
{What's NOT in v1 but might come later}

## Differentiation
{Why this over alternatives, stated as a concrete advantage not a vague claim}

## Feasibility Notes
{Technical approach, known constraints, rough complexity estimate}

## Open Questions
{Anything that came up but wasn't fully resolved}

## Motivation
{Why the user wants to build this - the personal/business driver}
```

#### 3.2 Present to User

Display the full concept brief inline (not just the file path). Then ask:

> **"Is this the idea?"**

Present with AskUserQuestion:

| Option | Description |
|--------|-------------|
| **Yes, this is it** | Lock it in. The concept is ready for next steps. |
| **Close, but needs tweaks** | I'll tell you what to adjust, then re-confirm. |
| **Not quite right** | Let's go back to the interview - something fundamental is off. |
| **Split it** | I'm actually describing multiple ideas. Help me separate and pick one. |

#### 3.3 Handle Response

**"Yes, this is it"**: Move to Phase 4.

**"Close, but needs tweaks"**: Ask what needs to change. Apply edits to `concept.md`. Re-present the updated brief and ask again. Loop until confirmed.

**"Not quite right"**: Ask what feels off. Return to Phase 1 with updated context. The interview continues, but now you have a concrete draft to react against (which is often easier than generating from scratch).

**"Split it"**: Help the user identify the distinct ideas. Present them as options. The user picks one (or saves the others for later). Continue with the chosen idea.

---

### Phase 3.5: Menu-Gen Test

Before proceeding to next steps, apply the Menu-Gen Test. See `modules/code-quality/rules/menu-gen-test.md`.

Forcing question: **Could this concept be accomplished with a single prompt + multimodal call instead of an app/script/feature? If yes, why are we building anything?**

Ask the user to answer in one sentence or short paragraph. If the dissolvability score is 4-5, add an "Existence Justification" field to `concept.md` and require the user to name the specific reason before the concept advances to `/xplan`. If score is 0-3, note it and proceed without interruption.

### Phase 4: Next Steps

Once the concept is confirmed, update `session.md` status to `confirmed` and ask:

> "The idea is locked. What do you want to do with it?"

| Option | Description |
|--------|-------------|
| **Deep research** | Run `/deepresearch` to validate the concept against the market, existing solutions, and technical landscape |
| **Plan it** | Run `/xplan` to create a full execution plan with phases, tasks, and architecture |
| **Just save it** | Keep the concept brief for later. I'll tell you where it's saved. |
| **Start building** | Jump straight into implementation (for small/simple ideas) |

**"Deep research"**: Invoke `/deepresearch` via the Skill tool with a query derived from the concept brief. Pass `--output {session_dir}` so research lands next to the concept.

**"Plan it"**: Invoke `/xplan` via the Skill tool with the one-liner and a pointer to the concept brief.

**"Just save it"**: Report the path to `{session_dir}/concept.md` and suggest the user can return later with `/ideate --resume` or feed the concept to `/xplan` manually.

**"Start building"**: Transition to implementation mode. Use the concept brief as your spec.

---

## Anti-Patterns (Do NOT Do These)

- **Don't be a survey bot.** Never present all 7 dimensions as a checklist. The interview should feel like a conversation with a smart friend, not a form.
- **Don't ask questions you can infer.** If the user said "I want to build a Chrome extension for developers," don't ask "What platform?" or "Who is the audience?" You already know.
- **Don't accept vague answers without pushing.** "It should be easy to use" is not a useful answer. Push: "Easy how? What's the interaction that should feel effortless?"
- **Don't front-load all questions.** Spread them out. Let insights from early answers shape later questions.
- **Don't skip the confirmation loop.** Even if you're confident, the user must explicitly approve the concept brief.
- **Don't over-engineer the brief.** The concept brief is 1-2 pages, not a PRD. Save the details for /xplan.
- **Don't lose context across tool calls.** If /deepresearch runs mid-interview, read the results and weave insights back into the conversation naturally.
