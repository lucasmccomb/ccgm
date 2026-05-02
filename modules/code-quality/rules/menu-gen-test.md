# Menu-Gen Test: Apps That Shouldn't Exist

Before committing to build anything — a new app, a script, a feature, a workflow — ask one question first:

> **Could this be a single prompt + multimodal call instead of an app/script/feature? If yes, why are we building anything?**

If you cannot answer "why," stop. The build might be unnecessary.

## The Karpathy Confession

Andrej Karpathy built Menu Gen: an OCR webapp on Vercel that takes a photo of a restaurant menu, calls an image generator for each item, and re-renders the menu with pictures.

Then he saw the Software 3.0 version: hand the photo to Gemini, say "use Nano Banana to overlay the items," and receive the annotated image directly — one multimodal call, no app.

> *"All of my menu gen is spurious. It's working in the old paradigm — that app shouldn't exist."*
> — Andrej Karpathy, Sequoia Capital, 2026-04-29

The app was not wrong or poorly built. It was answering the right question in the wrong paradigm. The new question is: does the build need to exist at all?

## The Forcing Question

At intake — before research, before planning, before any implementation — answer this in one paragraph:

> Could this be accomplished with a single prompt and a multimodal/agentic call? If yes, what is the specific reason an app, script, or persistent system is still needed?

Valid reasons an app still needs to exist:
- Runtime injection into another system (e.g., a Chrome extension that modifies page DOM)
- Persistent server state shared across users or sessions (e.g., a multi-tenant SaaS with a database)
- Recurring background automation that cannot be triggered manually each time
- Distribution to non-technical users who cannot operate a prompt

Not valid reasons:
- "The prompt would be long" — long prompts are fine
- "We need a UI" — many things that feel like they need UI are just a prompt with output rendering
- "The logic is complex" — complex logic can live in an agent, not an app

## Dissolvability Score

If the answer is not obvious, score it:

| Score | Meaning |
|-------|---------|
| **0** | Clearly needs to exist. Has runtime injection, persistent multi-user state, or distribution requirements. |
| **2-3** | Mostly needs to exist, but some parts could be dissolved into prompts. Consider which parts. |
| **5** | Could be a single multimodal or agentic call right now. Strong case for not building. |
| **4** | Borderline. The app adds enough structure or UX that it is worth building — but name the specific reason explicitly. |

A score of 4 or 5 is not a hard stop. It is a flag. Name the reason you are building anyway. If you cannot name it, the build is not justified.

## Examples

**Should not exist (score: 5)**

Menu Gen — OCR + image gen webapp. One Gemini + Nano Banana call does the same thing.

A script that fetches a URL, runs it through a prompt, and emails the summary on a schedule — if it runs manually each time and the user already has access to a model, this is a prompt, not a script.

**Needs to exist (score: 0)**

A Chrome extension that injects a dark-mode CSS overlay into every page the user visits. It runs inside the browser at runtime, on arbitrary pages the user navigates to. No prompt can do this.

A multi-tenant habit-tracking SaaS with user accounts, persistent streaks, and push notifications. It requires a database, a server, and distribution to users who interact via a native UI.

## When to Apply

Apply this check at every project intake: `/xplan`, `/research`, `/ideate`, or any other scoping exercise before research and planning begins.

Do not apply it to:
- Work already in progress (this is an intake check, not a retroactive audit)
- Incremental features on an existing system where the system's existence is already justified
- Purely exploratory research with no build decision yet

## Relationship to Build Decisions

This check does not reject ideas. It forces explicit justification before committing resources. The answer "this needs to exist because users cannot operate a raw prompt" is a complete and sufficient answer. The problem is building without asking the question at all.
