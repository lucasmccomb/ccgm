"""prose_lint: measure the STE-lite limits from the writing-system rule.

Public API:
    lint(text)  -> list[Finding]   errors and warnings
    stats(text) -> dict            counts the metrics tools read

Errors: sentence length (by kind) and paragraph length.
Warnings: two-action steps.
Noun clusters and unnamed references are guidance in the rule, not checked here:
an audit of real messages put their precision at 16% and 35%.

Before counting, the text loses frontmatter, fenced code, inline code, tables,
headings, URLs, and file:line refs. Each list item is its own paragraph.
"""
import math
import re
from dataclasses import dataclass

# Every threshold lives here.
LIMITS = {
    "instruction_words": 20,
    "description_words": 25,
    "paragraph_sentences": 6,
}

RULES = ("sentence-length", "paragraph-length", "two-actions")


@dataclass
class Finding:
    line: int
    level: str  # "error" | "warning"
    rule: str
    message: str
    text: str

    def as_dict(self):
        return {
            "line": self.line,
            "level": self.level,
            "rule": self.rule,
            "message": self.message,
            "text": self.text,
        }


# --- word lists --------------------------------------------------------------

# Base-form verbs that are rarely nouns: a sentence starting with one is an instruction.
_VERBS = set("""
add run use check read write create delete remove open close keep install update edit fix
verify confirm ensure show print return call pass send start stop restart copy move rename
replace select choose click press type enter avoid do don't let take give find search look
review merge push pull apply revert wait ask tell follow define declare import export deploy
launch kill skip save load begin finish split join pick treat try change increase decrease
restrict explain describe include exclude prefer compare inspect resolve retry convert
extract parse validate provide supply assign configure enable disable grant revoke approve
reject accept handle extend reduce compute measure calculate generate render ignore
make put get turn bring cite quote paste upload download sign pin unpin cancel clear
dispatch delegate append prepend insert trigger fetch track wrap
""".split())

# Words that are also common nouns: an instruction only when a determiner,
# pronoun, preposition, or particle follows ("Store the result", not "Store layer gains").
_AMBIGUOUS_VERBS = set("""
store log record test build link list name state report commit branch tag limit document
stage count match query mark switch drop cut break end set stack file note plan sort
rewrite checkout rebase patch scope target group price score label point focus
""".split())

_VERB_FOLLOWERS = set("""
the a an this that these those it them each every all any your my our its their both
to with on in into from up out off at by for of as over under back if when
""".split())

_ABBREVIATIONS = {
    "e.g", "i.e", "vs", "cf", "approx", "mr", "mrs", "ms", "dr", "st", "no", "fig", "ca", "al",
    "etc", "inc", "ltd", "jr", "sr",
}

# --- cleaning ----------------------------------------------------------------

_FENCE = re.compile(r"^\s*(```+|~~~+)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")
_HEADING = re.compile(r"^\s{0,3}#{1,6}(?:\s|$)")
_RULE_LINE = re.compile(r"^\s*(?:[-*_=]\s*){3,}$")
_URL = re.compile(r"(?:https?://|www\.)\S+")
_FILE_REF = re.compile(r"[\w./~-]*\w\.\w+:\d+(?::\d+)?")
_INLINE_CODE = re.compile(r"`[^`]*`")
# Inline code becomes this marker: it keeps a sentence boundary visible to the
# splitter but is not a word.
_CODE = "\ue000"
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>|<!--.*?-->")


def _clean_inline(s):
    s = _INLINE_CODE.sub(_CODE, s)
    s = _IMAGE.sub("", s)
    s = _LINK.sub(r"\1", s)
    s = _URL.sub("", s)
    s = _FILE_REF.sub("", s)
    s = _HTML_TAG.sub("", s)
    s = s.replace("*", "").replace("__", "")
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _blocks(text):
    """Yield (first_line_number, cleaned_text) for each paragraph or list item."""
    lines = text.splitlines()
    i = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                i = j + 1
                break
    fence = None
    cur = None  # [start_line, [parts]]
    out = []

    def flush():
        nonlocal cur
        if cur:
            cleaned = _clean_inline(" ".join(cur[1]))
            if re.search(r"\w", cleaned):
                out.append((cur[0], cleaned))
        cur = None

    for n in range(i, len(lines)):
        raw = lines[n]
        m = _FENCE.match(raw)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if m:
            flush()
            fence = m.group(1)
            continue
        stripped = raw.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("|") or _HEADING.match(raw) or _RULE_LINE.match(raw):
            flush()
            continue
        stripped = re.sub(r"^(?:>\s?)+", "", stripped).strip()
        item = _LIST_ITEM.match(stripped)
        if item:
            flush()
            cur = [n + 1, [stripped[item.end():]]]
        elif cur:
            cur[1].append(stripped)
        else:
            cur = [n + 1, [stripped]]
    flush()
    return out


# --- sentences ---------------------------------------------------------------

_SPLIT = re.compile(r"""([.!?]+["')\]]*)\s+(?=["'(\[]?[A-Za-z0-9\ue000])""")


def _split_sentences(block):
    sentences, start = [], 0
    for m in _SPLIT.finditer(block):
        before = block[start:m.start()].split()
        last = before[-1].lower().strip("\"'([") if before else ""
        if m.group(1) == "." and (last in _ABBREVIATIONS or re.fullmatch(r"[a-z]", last)):
            continue
        if block[m.end():].lstrip("\"'([")[:1].islower():
            # A lowercase start splits only after a plain full stop, "!" or "?"
            # that follows a word of 3+ letters that is not an abbreviation.
            ends_word = re.search(r"[A-Za-z]{3,}$", before[-1].strip("\"'([")) if before else None
            if m.group(1).rstrip("\"')]") not in (".", "!", "?") or not ends_word or last in _ABBREVIATIONS:
                continue
        sentences.append(block[start:m.end()].strip())
        start = m.end()
    tail = block[start:].strip()
    if tail:
        sentences.append(tail)
    return [s for s in sentences if re.search(r"\w", s)]


_ID = re.compile(r"#\d+|[A-Z]{1,3}-?\d+")


def _is_id_list(sentence):
    """True when more than half the words are IDs (E3, XP-3, #12): not prose."""
    words = _words(sentence)
    ids = sum(1 for w in words if _ID.fullmatch(_strip_punct(w)))
    return ids * 2 > len(words)


def _words(sentence):
    return [w for w in sentence.split() if re.search(r"\w", w)]


def _strip_punct(w):
    return w.strip("\"'()[]{}.,;:!?—–-")


def _is_instruction(sentence):
    words = _words(sentence)
    if not words:
        return False
    first = _strip_punct(words[0]).lower()
    if first in _VERBS:
        return True
    if first in _AMBIGUOUS_VERBS:
        if len(words) == 1:
            return True
        return _strip_punct(words[1]).lower() in _VERB_FOLLOWERS
    return False


# --- analysis ----------------------------------------------------------------

def _analyze(text):
    """Return (paragraphs, findings). Paragraph = (line, [sentences])."""
    findings = []
    paragraphs = []
    for line, block in _blocks(text):
        sentences = [s for s in _split_sentences(block) if not _is_id_list(s)]
        if not sentences:
            continue
        paragraphs.append((line, sentences))
        if len(sentences) > LIMITS["paragraph_sentences"]:
            findings.append(Finding(
                line, "error", "paragraph-length",
                f"{len(sentences)} sentences; limit is {LIMITS['paragraph_sentences']}",
                block[:80],
            ))
        for s in sentences:
            instr = _is_instruction(s)
            n = len(_words(s))
            limit = LIMITS["instruction_words" if instr else "description_words"]
            if n > limit:
                kind = "instruction" if instr else "description"
                findings.append(Finding(
                    line, "error", "sentence-length",
                    f"{n} words in a {kind}; limit is {limit}", s,
                ))
            if instr:
                findings.extend(_two_actions(line, s))
    return paragraphs, findings


_VERB_ALTERNATION = "|".join(sorted(re.escape(v) for v in _VERBS if "'" not in v))
_TWO_ACTIONS = re.compile(
    rf"\b(?:and|then)\s+(?:then\s+)?(?:{_VERB_ALTERNATION})\b|,\s*then\b|;", re.I
)


def _two_actions(line, sentence):
    if _TWO_ACTIONS.search(sentence):
        return [Finding(line, "warning", "two-actions",
                        "step holds more than one action; split it", sentence)]
    return []

# --- public API --------------------------------------------------------------

def lint(text):
    """Return the findings for `text`, in document order."""
    return _analyze(text)[1]


def _counts(paragraphs):
    return [len(_words(s)) for _, group in paragraphs for s in group]


def sentence_word_counts(text):
    """Word count of each counted sentence, in document order (same set as stats())."""
    return _counts(_analyze(text)[0])


def stats(text):
    paragraphs, findings = _analyze(text)
    sentences = [s for _, group in paragraphs for s in group]
    counts = _counts(paragraphs)
    instr = sum(1 for s in sentences if _is_instruction(s))
    by_rule = dict.fromkeys(RULES, 0)
    for f in findings:
        by_rule[f.rule] += 1
    over = by_rule["sentence-length"]
    ranked = sorted(counts)
    return {
        "words": sum(counts),
        "sentences": len(sentences),
        "paragraphs": len(paragraphs),
        "instruction_sentences": instr,
        "descriptive_sentences": len(sentences) - instr,
        "max_sentence_words": max(counts, default=0),
        "mean_sentence_words": round(sum(counts) / len(counts), 1) if counts else 0,
        "max_paragraph_sentences": max((len(g) for _, g in paragraphs), default=0),
        "errors": sum(1 for f in findings if f.level == "error"),
        "warnings": sum(1 for f in findings if f.level == "warning"),
        "p90_sentence_words": ranked[math.ceil(0.9 * len(ranked)) - 1] if ranked else 0,
        "sentences_over_limit": over,
        "pct_over_limit": round(over / len(counts) * 100, 1) if counts else 0,
        "by_rule": by_rule,
    }
