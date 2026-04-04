---
name: editorial-critique
description: Deep editorial critique of any long-form writing. Runs 8 parallel analysis passes covering prose craft, AI-tell detection, argument architecture, sentence-level quality, grammar, data accuracy, structure, and conciseness. Use when reviewing blog posts, essays, reports, or any prose that needs to be sharp.
disable-model-invocation: true
---

# Editorial Critique

A comprehensive editorial review that treats writing as craft. Runs 8 parallel analysis passes and produces a scored, prioritized report.

## Usage

```
/editorial-critique                              # Reviews the most recently modified .md file in content/posts/
/editorial-critique path/to/file.md              # Reviews a specific file
/editorial-critique path/to/file.md --fix        # Reviews AND applies fixes automatically
/editorial-critique path/to/file.md --score-only # Just show the scorecard, skip detailed findings
```

## Instructions

### Step 1: Identify the File

If `$ARGUMENTS` contains a file path, use it. Otherwise find the most recently modified `.md` file in `content/posts/`.

Read the full file content. Strip frontmatter (everything between the opening and closing `---`) before sending to agents - they should critique the prose, not the metadata.

### Step 2: Run Parallel Editorial Passes

Launch **8 Task agents in parallel** (single message, all `subagent_type: "Explore"`). Do **NOT** use `run_in_background: true` - the agents must run in the foreground so the system waits for all 8 to complete before returning results. Launching all 8 in a single message ensures they execute concurrently while still blocking until all finish.

Each agent receives the full text and analyzes it from one lens.

Include the full text in each agent's prompt (not a file path - the agent needs to analyze text, not explore code).

Every agent prompt must end with:

```
IMPORTANT:
- Do NOT use em dashes in your suggestions. Use hyphens, commas, colons, semicolons, or restructure.
- Quote the EXACT original text when referencing issues so edits can be applied programmatically.
- Return findings as the specified JSON array. If no issues found for a category, return an empty array.
```

---

**Agent 1: Prose Craft & Sentence Quality**

This is the line-editing pass. It evaluates writing at the sentence and word level.

```
You are a line editor who cares deeply about prose craft. Review this text for sentence-level writing quality.

For each issue found, report:
- The exact text with the problem
- What's wrong and why it weakens the prose
- A rewritten version that's stronger
- Type of issue (see categories below)

EVALUATE:

Verbs:
- Flag weak verbs: "is", "was", "has", "make", "get", "do", "thing" when a vivid, specific verb exists
- Flag nominalizations (verb-turned-noun): "make a decision" -> "decide", "provide assistance" -> "help"
- Flag passive voice where active would be stronger and the agent is known

Word choice:
- Flag abstract language where concrete specifics would land harder
- Flag Latinate words where Anglo-Saxon equivalents are clearer ("utilize" -> "use", "facilitate" -> "help", "implement" -> "do")
- Flag adverbs that duplicate the verb's meaning ("completely destroyed", "quickly rushed")
- Flag cliches and dead metaphors ("at the end of the day", "moving the needle", "tip of the iceberg")

Sentence rhythm:
- Flag sequences of 3+ sentences with similar length (monotonous rhythm)
- Flag sequences of 3+ sentences with the same structure (Subject-Verb-Object, Subject-Verb-Object)
- Flag sentences longer than 40 words that could be split
- Flag sections with no short sentences (short sentences create emphasis; their absence flattens impact)
- Flag sentences that end weakly (the power position is the end of the sentence; bury "however" and qualifiers mid-sentence)

Paragraph craft:
- Flag paragraphs that bury their strongest point in the middle (lead with it or close with it)
- Flag paragraphs longer than 6 sentences (consider splitting for pacing)
- Flag single-sentence paragraphs used more than twice (they lose impact through overuse)

DO NOT flag:
- Intentional sentence fragments used for rhetorical effect
- Informal/conversational tone when it serves the piece
- Starting sentences with conjunctions ("And", "But", "So")

Return findings as a JSON array:
[{"text": "...", "issue": "...", "rewrite": "...", "type": "weak-verb|nominalization|passive|abstract|latinate|adverb|cliche|rhythm|sentence-length|structure-repetition|weak-ending|buried-point|paragraph-length"}]
```

---

**Agent 2: AI-Tell Detection & Authenticity**

This pass catches patterns that make writing sound machine-generated rather than human-authored.

```
You are an expert at identifying AI-generated writing patterns. Review this text and flag every instance of AI writing tells.

For each issue found, report:
- The exact text containing the AI tell
- Which pattern it matches (see categories below)
- A human-sounding alternative
- Severity: glaring (immediately obvious AI), subtle (trained eye would catch it), minor (borderline)

DETECT THESE PATTERNS:

Filler and transition phrases (cut entirely or replace):
- "It's worth noting that", "It should be mentioned", "It's important to understand"
- "At its core", "In today's world", "When it comes to", "At the end of the day"
- "Let's explore", "Let's dive in", "Let's take a look at", "Let's break this down"
- "This is where things get interesting", "Here's the thing", "The reality is"
- "In other words", "Put simply", "To put it another way"
- "Ultimately", "Furthermore", "Moreover", "Additionally", "Consequently"
- "That said", "With that in mind", "Having said that"

AI vocabulary (overused words that signal AI authorship):
- delve, tapestry, landscape, crucial, pivotal, foster, garner, underscore
- leverage, robust, streamline, seamless, harness, nuanced, holistic
- paradigm, synergy, ecosystem, empower, stakeholder, alignment
- intricate, multifaceted, testament, vibrant, enduring, invaluable

Structural tells:
- "Not X, it's Y" reversal constructions ("It's not just about X, it's about Y")
- Symmetry padding (balancing sentences for parallelism's sake: "It's not just A, it's B")
- Rule-of-three lists unless the content genuinely requires three items
- Generic positive conclusions that could end any essay ("The future is bright")
- Rhetorical questions used as transitions ("So what does this mean?", "But why does this matter?")
- Sentences that announce what they're about to do ("In this section, we'll examine...")

Tone tells:
- Excessive hedging ("somewhat", "arguably", "it seems like", "to some extent", "in many ways")
- Sycophantic/validating language ("Great question", "That's a really important point")
- False balance ("While there are pros and cons to every approach...")
- Inflated significance ("This represents a fundamental shift in how we think about...")
- Promotional superlatives ("groundbreaking", "game-changing", "revolutionary")

Formatting tells:
- Overuse of bold for emphasis (bold should be rare; if everything is emphasized, nothing is)
- Emoji in professional/analytical writing
- Every section ending with a tidy summary sentence

Return findings as a JSON array:
[{"text": "...", "pattern": "...", "fix": "...", "severity": "glaring|subtle|minor"}]
```

---

**Agent 3: Argument Architecture**

This pass evaluates the piece's logical skeleton, thesis coherence, and rhetorical effectiveness.

```
You are a rhetoric professor evaluating argument architecture. Review this text for logical structure, thesis coherence, and persuasive effectiveness.

For each issue found, report:
- The section or paragraph with the issue
- What the problem is
- How to fix it
- Severity: flawed (logical gap or fallacy), weak (could be stronger), structural (architecture issue)

EVALUATE:

Thesis and throughline:
- Can you state the thesis in one sentence? If not, the piece lacks a clear spine.
- Does every section serve the thesis? Flag sections that drift.
- Does the piece build toward its conclusion, or does it plateau in the middle?

Logical integrity:
- Claims not supported by evidence presented in the text
- Logical leaps or missing connective reasoning between paragraphs
- Cherry-picked comparisons that wouldn't survive scrutiny
- Straw man characterizations of opposing positions
- False equivalences or false dichotomies
- Numbers used in misleading ways (wrong denominators, mixing timeframes, apples-to-oranges)
- Conclusions that don't follow from the evidence
- Correlation presented as causation

Argument strength:
- Missing counterarguments that, if addressed, would strengthen the piece
- Weakest argument in the piece (the one a critic would attack first) - is it acknowledged or exposed?
- Places where the argument loses momentum or goes off-track
- Assertions presented as self-evident that actually need support

Rhetorical effectiveness:
- Does the opening earn the reader's attention with substance (not a gimmick)?
- Does the conclusion land with force, or does it trail off?
- Are the strongest points positioned for maximum impact (beginning or end of sections, not buried)?
- Does the piece earn its length, or could entire sections be cut without losing the argument?

Narrative arc:
- Does the piece follow a coherent arc? (problem -> evidence -> implications -> resolution)
- Are transitions between sections earned? (Each section should answer: why this, why now, why here?)
- Does each section close its loop before opening a new one?

Return findings as a JSON array:
[{"section": "...", "issue": "...", "fix": "...", "severity": "flawed|weak|structural"}]
```

---

**Agent 4: Conciseness & Density**

```
You are a ruthless editor whose job is to cut. Every word must earn its place. Review this text for wordiness, redundancy, and low-density passages.

For each issue found, report:
- The exact text that could be tightened
- The tighter version
- Words saved
- Type of issue

CHECK FOR:

Wordiness:
- Sentences that could lose 30%+ of words without losing meaning
- Prepositional phrase chains ("the impact of the implementation of the policy on the lives of people" -> "how the policy affects people")
- "There is/are" constructions ("There are many people who believe" -> "Many people believe")
- "In order to" -> "to"
- "Due to the fact that" -> "because"
- "In the event that" -> "if"
- "A large number of" -> "many"
- "At this point in time" -> "now"

Redundancy:
- Paragraphs that repeat a point already made elsewhere
- Sentences that say the same thing twice in different words within the same paragraph
- Sections where the same comparison or example appears multiple times
- Adjective stacking that adds nothing ("important and significant", "new and innovative")

Low-density passages:
- Paragraphs where removing the first and last sentence loses nothing (they're just throat-clearing and summarizing)
- Passages that explain what the reader can already infer from context
- Setup sentences before data or quotes that just announce them ("The following table shows..." - just show the table)
- "As mentioned earlier" callbacks (if you need to reference earlier content, the structure may need fixing)

Signal-to-noise:
- Score each paragraph 1-10 for information density (1 = mostly filler, 10 = every word carries weight)
- Flag any paragraph scoring below 5
- For the piece overall, estimate the percentage that could be cut without losing meaning

Return findings as a JSON array:
[{"text": "...", "tighter": "...", "words_saved": N, "type": "wordy|redundant|low-density|setup-sentence"}]
```

---

**Agent 5: Data & Claims Verification**

```
You are a fact-checker at a major publication. Review this text for data accuracy, citation quality, and mathematical correctness.

For each data point or claim, verify:
- Is the number plausible given the source cited?
- Is the source authoritative and current?
- Are comparisons mathematically correct? (Check the arithmetic yourself)
- Are timeframes consistent? (Not mixing FY2023 and FY2024 data without noting it)
- Are characterizations of sources fair? (Does the source actually say what the text claims?)

FLAG:
- Numbers that don't add up (percentages that exceed 100%, per-person calculations that are off)
- Broken or potentially dead links
- Claims that overstate what the cited source actually says
- Missing citations for strong factual claims
- Outdated data presented as current
- Apples-to-oranges comparisons (e.g., comparing annual to monthly figures, nominal to inflation-adjusted)
- Round numbers that feel invented ("about 50%" without a source)
- Statistics without context (a number means nothing without a baseline or comparison)

For each finding, note whether it's:
- error: mathematically wrong or factually false
- caution: plausible but needs verification or better sourcing
- suggestion: would benefit from additional context or citation

Return findings as a JSON array:
[{"claim": "...", "issue": "...", "severity": "error|caution|suggestion"}]
```

---

**Agent 6: Structure, Pacing & Flow**

```
You are a developmental editor evaluating the architecture of this piece. Review for overall structure, pacing, and reader experience.

ANALYZE:

Opening:
- Does it hook with substance (a surprising fact, a provocation, a concrete image)?
- Or does it hook with a gimmick (rhetorical question, "Imagine this...", vague promise)?
- How many words before the reader gets something valuable? (Under 50 is good, over 150 is a problem)

Section architecture:
- Does each section logically follow from the previous one?
- Is there a clear throughline that builds across sections?
- Are transitions between sections smooth or jarring?
- Could the sections be reordered without losing anything? (If yes, the structure is arbitrary, not logical)

Pacing:
- Are there sections that feel too long relative to their importance?
- Are there sections that feel rushed and need more development?
- Does the piece build momentum toward the conclusion, or does it plateau?
- Are there places where the reader would lose interest? (long data dumps, repetitive arguments, tangential asides)

Closure:
- Does the conclusion earn its claims based on what came before?
- Does it introduce new ideas (it shouldn't)?
- Does it trail off or end with force?
- Is there a clear "so what" - why should the reader care after finishing?

Headings:
- Are they descriptive and parallel in structure?
- Do they create a readable outline on their own? (Skim just the headings - do they tell the story?)
- Are any too clever/vague to be useful?

Tone consistency:
- Does the register stay consistent, or does it shift jarringly between sections?
- Is the reading level appropriate and consistent throughout?

Return findings as a JSON array:
[{"section": "...", "issue": "...", "suggestion": "...", "severity": "structural|pacing|minor"}]
```

---

**Agent 7: Power & Impact**

```
You are a writing coach focused on making prose land harder. The difference between adequate writing and powerful writing is specificity, surprise, and restraint. Review this text for missed opportunities to increase impact.

For each opportunity found, report:
- The current text
- Why it's weaker than it could be
- A stronger alternative
- Type of improvement

CHECK FOR:

Concrete vs abstract:
- Places where a specific example, number, name, or image would be more powerful than a general statement
- "Many people are affected" -> "2.3 million families lost coverage"
- "This costs a lot of money" -> "This costs $47 per household per year"

Contrast and juxtaposition:
- Places where putting two facts side by side would create impact through contrast
- Places where a single devastating comparison would be more effective than three adequate ones

Show vs tell:
- Moments where the text tells the reader what to think ("This is alarming") instead of showing evidence and letting the reader reach that conclusion
- Moments where a brief narrative or example would be more memorable than an abstract claim

Positioning for impact:
- The most powerful line in the piece - is it positioned for maximum impact? (End of a section, end of a paragraph, standalone)
- Strong points buried in long paragraphs
- Conclusions that undercut themselves with qualifiers

Restraint:
- Places where the text oversells a point (if the evidence is strong, let it speak)
- Multiple exclamation points, excessive emphasis, or hyperbolic language
- Stacking three examples when one strong one would suffice

Surprise and tension:
- Does the piece ever surprise the reader? If not, where could it?
- Are there moments of tension (expectation vs reality, common belief vs evidence)?
- Does the piece challenge assumptions or just confirm what the reader already believes?

Return findings as a JSON array:
[{"text": "...", "issue": "...", "stronger": "...", "type": "concrete|contrast|show-dont-tell|positioning|restraint|surprise"}]
```

---

**Agent 8: Grammar & Mechanics**

```
You are a copy editor. Review this text for grammar, punctuation, spelling, and mechanical errors.

For each issue found, report:
- The exact text containing the error (quote it)
- What's wrong
- The corrected text
- Severity: error (objectively wrong) or suggestion (stylistic preference)

CHECK FOR:
- Subject-verb agreement
- Tense consistency within and across paragraphs
- Comma splices and run-on sentences
- Misused words (affect/effect, its/it's, their/there/they're, than/then, who/whom, lay/lie)
- Dangling or misplaced modifiers
- Parallel structure violations in lists and comparisons
- Missing or misplaced punctuation
- Inconsistent capitalization, number formatting, or abbreviation style
- Inconsistent use of serial/Oxford comma (pick one and stick with it)
- Incorrect possessives

DO NOT FLAG:
- Intentional informal/conversational tone
- Sentence fragments used for rhetorical effect
- Starting sentences with "And", "But", or "So" (acceptable in most modern prose)
- Ending sentences with prepositions (acceptable in non-academic writing)

IMPORTANT: Do NOT use em dashes. Flag any em dashes found and suggest alternatives (hyphens, commas, colons, semicolons, or restructured sentences).

Return findings as a JSON array:
[{"text": "...", "issue": "...", "fix": "...", "severity": "error|suggestion"}]
```

---

### Step 3: Score the Piece

After all agents complete, compute a scorecard across 8 dimensions (1-10 each, 80 max):

| Dimension | What It Measures | Agent Source |
|-----------|-----------------|--------------|
| **Craft** | Sentence quality, word choice, rhythm | Agent 1 |
| **Authenticity** | Human voice, absence of AI tells | Agent 2 |
| **Argument** | Logical integrity, thesis coherence, persuasion | Agent 3 |
| **Density** | Economy of language, signal-to-noise ratio | Agent 4 |
| **Accuracy** | Factual correctness, citation quality, math | Agent 5 |
| **Architecture** | Structure, pacing, transitions, opening/closing | Agent 6 |
| **Impact** | Power, specificity, surprise, contrast | Agent 7 |
| **Mechanics** | Grammar, punctuation, consistency | Agent 8 |

**Scoring guidelines:**
- 9-10: Publishable as-is in this dimension. No meaningful improvements possible.
- 7-8: Strong. A few fixable issues, but the foundation is solid.
- 5-6: Adequate. Noticeable issues that weaken the piece.
- 3-4: Weak. Significant problems that undermine effectiveness.
- 1-2: Needs fundamental rework in this dimension.

Score based on the ratio of issues found to the length and ambition of the piece. A single factual error in a data-heavy piece is different from a single factual error in an opinion piece.

### Step 4: Compile Results

Compile all findings into a single **numbered, prioritized list** ordered from highest to lowest priority.

**If `--score-only` was passed**, display only the scorecard and stop.

**Deduplication**: If multiple agents flag the same text, merge into a single finding and note which lenses caught it.

**Prioritization rules** (apply in order):

1. **Severity tier** is the primary sort: Errors > Improvements > Polish
   - **Errors** - Factual errors, broken math, grammar mistakes, logical flaws, glaring AI tells
   - **Improvements** - Structural issues, weak arguments, wordiness, weak prose, subtle AI tells
   - **Polish** - Minor suggestions, stylistic preferences, impact opportunities

2. **Within each tier**, rank by impact:
   - Issues affecting the thesis or core argument rank above isolated sentence issues
   - Issues that appear multiple times (systemic patterns) rank above one-off occurrences
   - Issues visible to every reader rank above issues only an editor would catch
   - Structural/architectural issues rank above line-level issues

Each item in the list includes:
- A number (sequential across all tiers)
- The severity tier tag: `[Error]`, `[Improvement]`, or `[Polish]`
- A concise description of the issue
- The original text quoted (for line-level issues)
- The suggested fix or rewrite
- Which editorial lens(es) caught it

### Step 5: Present to User

Display the scorecard first:

```
EDITORIAL CRITIQUE SCORECARD (XX/80)

Craft:        X/10  ████████░░
Authenticity:  X/10  ██████░░░░
Argument:      X/10  █████████░
Density:       X/10  ███████░░░
Accuracy:      X/10  █████████░
Architecture:  X/10  ████████░░
Impact:        X/10  ██████░░░░
Mechanics:     X/10  █████████░
```

Then display the full numbered list from Step 4.

After the list, use `AskUserQuestion` to ask how the user wants to proceed:

1. **Implement all** - Apply every fix from the list
2. **Pick and choose** - Let me select which items to implement by number
3. **None** - Keep the report as reference, make no changes

If `--fix` was passed, skip the question and apply all Error-level fixes automatically, then ask about the remaining items using the same prompt above.

If the user chooses **"Pick and choose"**, ask them to provide the item numbers they want implemented (e.g., "1, 3, 5-8, 12"). Then apply only those.

### Step 6: Apply Fixes (if requested)

Use the Edit tool to apply approved changes to the file. Work through edits in document order (top to bottom) to avoid offset issues.

After all edits, verify the file still builds if applicable (e.g., `npm run build` for blog posts).
