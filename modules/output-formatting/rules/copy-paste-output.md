# Copy-Paste Output

**Iron Law:** CONTENT MEANT TO BE COPY-PASTED GOES IN A FENCED CODE BLOCK — NEVER A BLOCKQUOTE.

When output is destined for somewhere else — an email, a text message, a social post, a bio, a form field, a prompt for another tool — the deliverable is the exact text the user will paste. Any decoration added for presentation becomes cleanup work at the destination.

## Problem

Pasteable content is habitually wrapped in markdown blockquotes (`>` prefixes). In the terminal that renders as a vertical line running down the left edge of the content. Selecting and copying it drags along quote markers, soft line breaks, and indentation, so the user has to hand-reformat the text before it looks right in the target text area. The same applies to decorative quotation marks, leading indentation, and inline commentary mixed into the content.

## Rule

Deliver pasteable content in a fenced code block containing **exactly** the text that should land at the destination, and nothing else.

- **Never** present pasteable content as a blockquote (`>`), indented text, or text wrapped in quotation marks
- The block contains only the content itself — no labels, no headers like "Draft:", no trailing sign-off commentary
- Keep all commentary, options, and explanation **outside** the block
- Match the destination's format: plain text for emails/messages/forms; markdown source only when the destination renders markdown (GitHub comments, READMEs)
- Multiple variants get one block each, with a short label in prose above each block
- Preserve intentional structure (blank lines between paragraphs, list markers the destination expects) and add nothing the destination doesn't need

## What Counts as Pasteable Content

Anything the user will move into another surface: emails and replies, texts/DMs, social media posts, bios and profile blurbs, product descriptions, support responses, form field answers, prompts for other AI tools, commit messages or PR descriptions presented for approval, configuration values, and commands to run on another machine.

When in doubt, ask: "is the user going to select this text and paste it somewhere?" If yes, fence it.

## Example

**Bad** — blockquote renders with a vertical line and copies dirty:

> Hi Sarah,
>
> Thanks for reaching out about the timeline. We're on track to deliver by Friday.

**Good** — fenced block copies clean:

```text
Hi Sarah,

Thanks for reaching out about the timeline. We're on track to deliver by Friday.
```

## Red Flags

Stop and re-fence the content if you catch yourself:

- Reaching for `>` to present a draft, reply, or message
- Putting "Subject:" or "Option A:" labels inside the block when they aren't part of the pasteable text
- Adding bold/italics to content headed for a plain-text destination
- Wrapping the content in quotation marks "for clarity"
- Mixing your own commentary into the same block as the content
- Re-sending content the user already asked to have cleaned up — the first version should have been paste-ready
