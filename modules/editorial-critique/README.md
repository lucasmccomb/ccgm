# Editorial Critique

Deep editorial review that treats writing as craft. Runs 8 parallel analysis passes and produces a scored, prioritized report.

## `/editorial-critique [file] [--fix] [--score-only]`

Analyzes any long-form writing (blog posts, essays, reports, documentation) across 8 editorial lenses simultaneously:

| Pass | What It Checks |
|------|---------------|
| Prose Craft | Verbs, word choice, sentence rhythm, paragraph structure |
| AI-Tell Detection | Filler phrases, AI vocabulary, structural/tone tells |
| Argument Architecture | Thesis coherence, logical integrity, rhetorical effectiveness |
| Conciseness | Wordiness, redundancy, signal-to-noise ratio |
| Data Verification | Factual accuracy, citation quality, math correctness |
| Structure & Pacing | Opening hook, section flow, transitions, closure |
| Power & Impact | Specificity, contrast, show-vs-tell, surprise, restraint |
| Grammar & Mechanics | Subject-verb agreement, punctuation, consistency |

Produces a scorecard (8 dimensions, 80 points max) and a prioritized findings list. Optionally applies fixes automatically with `--fix`.

**Usage:**
```
/editorial-critique path/to/post.md
/editorial-critique path/to/post.md --fix
/editorial-critique path/to/post.md --score-only
```

## Manual Installation

```bash
mkdir -p ~/.claude/skills/editorial-critique
cp skills/editorial-critique/SKILL.md ~/.claude/skills/editorial-critique/SKILL.md
```
