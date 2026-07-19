# Model Vetting: Verify Before Integrating Any New Model

**Iron Law:** NO NEW MODEL ENTERS THE HARNESS OR THE LOCAL DEV SYSTEM WITHOUT PASSING THE VETTING CHECKLIST. "OPEN SOURCE" IS A CLAIM, NOT A VERIFICATION.

This applies to ANY model that is not already part of the trusted, in-use set — open-weights releases, hosted third-party APIs, fine-tunes, and quantized re-uploads — being wired into anything: a Claude Code backend swap (`ANTHROPIC_BASE_URL` repointing, wrapper scripts, translation proxies), a delegated-agent fleet, an application feature, a local inference stack, or a script.

**Announce at start:** "I'm using the model-vetting discipline. Running the checklist before any integration work."

## Why This Rule Exists

Two failure classes motivated it, both observed in the wild:

1. **Announced ≠ released ≠ verified.** A flagship "open source" model (Kimi K3, July 2026) was announced on the 16th with weights promised for the 27th — an 11-day window in which "the open model" existed only as a hosted API. Integration plans built on "it's open, we can always self-host" were resting on an artifact that did not exist yet. Availability, provenance, and terms must be verified against the actual artifact, not the press release.
2. **A model inside an agent harness inherits the harness.** A new backend model dropped into Claude Code gets every tool, credential, file, and permission the harness can reach — shell, git push, secrets in env files, MCP servers, browsers. Deterministic hooks (branch-guard, permission gates) still fire, but they gate specific actions, not judgment: an unvetted model's failure modes (instruction-following gaps, prompt-injection susceptibility, silent exfiltration via tool calls) are exactly the ones action-gates don't cover.

## The Checklist

Work through every section. Record answers (see "Write It Down" below). A section that cannot be answered is a **BLOCKED** finding, not a skippable one.

### 1. Weights Provenance & Availability (open-weights models)

- [ ] **Do the weights actually exist right now?** Find the artifact itself (Hugging Face / ModelScope repo with files present), not an announcement of it.
- [ ] **Is the publisher the vendor's official org?** Verify the org handle from the vendor's own site/docs — not from search results or a README badge. Popular models attract typosquatted and backdoored re-uploads within days of release.
- [ ] **Pin the exact revision.** Record the commit hash of the weights repo and load by revision, never by floating `main`. A repo that was clean at vetting time can be force-updated later.
- [ ] **Integrity check.** If the vendor publishes checksums or signatures, verify them. If not, record the hashes of what you downloaded so drift is detectable.
- [ ] **Quantized / converted variants** (GGUF, AWQ, MLX, …) are separate artifacts with their own provenance. A community quant of an official model is community-published — vet the converter and the uploader, or convert from official weights yourself.

### 2. File-Format & Loading Safety

- [ ] **Safetensors or GGUF only.** Pickle-based formats (`.bin`, `.pt`, `.ckpt`) execute arbitrary code on load. Refuse them unless converted or scanned in an isolated environment first.
- [ ] **No `trust_remote_code=True`** unless the custom modeling code has been read and the revision pinned. That flag is "run this repo's Python on my machine."
- [ ] **Pin the inference stack.** The serving engine (vLLM, SGLang, llama.cpp, MLX) and any converters are supply chain too — pinned versions, official sources.

### 3. License & Terms

- [ ] **License permits your use.** Read the actual license file in the weights repo (not the blog post). Many "open" models ship modified licenses with commercial thresholds, attribution requirements, or usage restrictions.
- [ ] **Hosted API terms** (for any hosted integration, including the vendor's own): data retention period, whether inputs are used for training, jurisdiction the data lands in. Every prompt, file, and repo you send to a hosted endpoint is disclosed to that operator — decide explicitly which codebases are allowed to flow there.

### 4. Serving Path as Supply Chain

- [ ] **Who is actually serving it?** An aggregator (e.g. OpenRouter) may route to one upstream provider — the upstream's terms apply, not just the aggregator's.
- [ ] **Translation proxies count.** Anything between the harness and the model (LiteLLM, protocol bridges, routers) sees full plaintext traffic including any secrets in context. Pin versions, prefer local-only listeners, and treat proxy config as security-sensitive.
- [ ] **Keys in scoped env files** (mode 0600, sourced by the launcher that needs them) — never in shell rc, never committed, never pasted into a session transcript.

### 5. Staged Agentic Access (the harness gate)

Never grant a new model full harness access on day one. Stage it, and advance only on evidence:

| Stage | Access | Gate to advance |
|-------|--------|-----------------|
| 0 — Smoke test | Chat only, no tools, no repo context | Coherent output; auth, model ID, and context window verified |
| 1 — Sandbox | Isolated worktree or scratch repo; read-mostly; NO secrets, NO push, NO browsing/untrusted content | Follows instructions and tool contracts; no rule-violating actions across several sessions |
| 2 — Implementer | Real specs in isolated worktrees; commits allowed; output treated as an untrusted contribution behind independent two-stage review (spec compliance, then code quality) on a trusted model | Tracked results (log observations per task) show consistent spec adherence |
| 3 — Expanded roles | Review, orchestration, broader tool surface | Only after Stage 2 evidence accumulates; expand one capability at a time |

- Prompt-injection posture of a new model is unknown: keep web browsing and untrusted-content tools out of its reach until Stage 3.
- Two-stage review by a trusted model is the structural containment for Stage 2 — the new model implements, the trusted model judges the diff. Do not collapse this into self-review.

### 6. Write It Down

- [ ] Record the verification before first use: source URL, publisher org, revision hash, license, data terms, serving path, date, and current stage. Keep it next to the integration config (e.g. a `VETTING.md` beside the wrapper/proxy config).
- [ ] **Re-verify on change.** A new model version, a changed provider, or an edited proxy config re-opens the checklist (hash-of-config marker pattern: if the integration config changed, the old verification does not apply).

## Rationalizations That Mean You Are About to Skip Vetting

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "It's open source, so it's safe" | Openness enables verification; it is not itself verification. You still have to do it. |
| "The weights are announced" | Announced ≠ released ≠ verified. Check that the artifact exists and is the vendor's. |
| "It's the top model on the leaderboard" | Popularity attracts typosquats and backdoored re-uploads. Verify the org, pin the hash. |
| "The provider is reputable" | The re-upload you downloaded may not be from the provider. |
| "We'll lock it down later" | The first unrestricted session is when credentials leak. Stage access from day one. |
| "It's just a quick benchmark run" | A benchmark run inside the harness has the same tool access as production work. Use Stage 0/1. |
| "The benchmarks say it's as good as our current model" | Capability benchmarks measure neither provenance nor safety under tool access. Different question entirely. |

## Red Flags

Stop and run the checklist if you catch yourself:

- Writing `ANTHROPIC_BASE_URL`/wrapper/proxy config for a model with no vetting record
- Downloading weights from a repo whose org you did not verify against the vendor's site
- Loading a `.bin`/`.pt` file or passing `trust_remote_code=True` to "just try it"
- Pointing a session that can reach secrets or push access at a Stage 0/1 model
- Sending a private codebase to a hosted endpoint whose retention terms you have not read
- Upgrading a model version and reusing last version's verification

## Cross-References

- `subagent-patterns.md` — the two-stage review that contains Stage 2 implementer output
- `verification.md` — evidence-before-claims; a vetting record is evidence, a vendor claim is not
- `config-change-detection.md` — the hash-marker pattern for re-verification on config drift
- `git-worktrees.md` — the isolation mechanism for Stage 1/2 sandboxing
