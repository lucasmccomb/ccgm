# Copy-Paste Output

Content meant to be copy-pasted goes in a fenced code block, never a blockquote. When output is destined for somewhere else (an email, a text, a social post, a bio, a form field, a prompt for another tool, a commit message or PR body presented for approval, a config value, a command for another machine), the deliverable is the exact text the user will paste, and any decoration becomes cleanup work at the destination. A blockquote renders with a vertical bar and copies with `>` markers, soft line breaks, and indentation.

- The block contains only the content: no "Draft:" or "Subject:" labels, no trailing commentary.
- Commentary, options, and explanation stay outside the block.
- Match the destination's format: plain text for emails, messages, and forms; markdown source only when the destination renders markdown (GitHub comments, READMEs).
- One block per variant, with a short label in prose above each.
- Preserve intentional structure (blank lines between paragraphs, list markers the destination expects) and add nothing else; no quotation marks "for clarity," no bold headed for a plain-text field.

When in doubt: will the user select this text and paste it somewhere? If yes, fence it.

Blockquote, copies dirty:

> Hi Sarah,
>
> Thanks for reaching out about the timeline. We're on track to deliver by Friday.

Fenced block, copies clean:

```text
Hi Sarah,

Thanks for reaching out about the timeline. We're on track to deliver by Friday.
```
