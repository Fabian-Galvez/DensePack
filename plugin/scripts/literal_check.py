"""Finds figurative phrasing in finished text. Used by the style gate.

WHAT THIS IS: a plain module, not a hook. Nothing runs it directly. The Stop
gate imports it when the user has turned the writing rules on with /stylepack.

WHAT IT DOES: returns every figurative phrase it can find in a piece of text,
as (kind, phrase) pairs. It never rewrites anything. Choosing the literal
replacement needs judgement about what was meant, and a machine that guessed
would damage sentences, so the gate names the phrase and sends the text back to
be rewritten by the model that wrote it.

WHY A SEPARATE CHECK EXISTS AT ALL: a character rule can be applied by a
program. An em dash always becomes a comma. "The docs get wrong" has no
mechanical replacement, so no character check can see it, and a rule that only
reminds cannot catch it either. This is the missing piece between the two.

THE DESIGN CONSTRAINT: a checker that says almost everything is broken is
itself broken. Every pattern here was dry run against real hand written
documentation before it was kept, and every pattern that fired on good prose
was cut rather than kept. It found one real slip in this plugin's own
documentation and nothing else across thirteen files.

THREE SHAPES ARE MATCHED, AND NOTHING ELSE:

  Personification. An inanimate subject doing something only a person can do.
  "The docs think", "the code knows", "the number wants". The subject list is
  the nouns technical writing actually uses, not every noun in English.

  Fixed idioms. Set phrases whose meaning is not their words. "Under the hood",
  "out of the box". A closed list, because an open one guesses.

  Labelling sentences. A sentence that only names what the sentence before it
  already said, "That is the whole point of it.", instead of adding a fact.
  Added 30 August 2026, after a live reviewer's test showed nothing else here
  caught it. A closed list of the nouns such a sentence reaches for, the same
  reason idioms above are a closed list.
"""

import re
from pathlib import Path

# Inanimate subjects that come up constantly in this work. A person or a model
# is NOT here: "the user decided" and "Opus scored" are literal and true.
SUBJECTS = (
    r"docs?|documentation|reference|README|CLAUDE\.md|HANDOFF|file|files|"
    r"code|script|scripts|hook|hooks|plugin|table|tables|number|numbers|"
    r"receipt|receipts|image|images|test|tests|suite|report|command|"
    r"setting|settings|threshold|measurement|page|note|doc|"
    # Added 21 August 2026. Dry run against 25 documents that already pass:
    # these nouns produce ZERO new hits with the existing verb list.
    r"export|folder|folders|copy|copies|packer|meter|strip|column|row|rows|"
    r"link|links|repo|repos|engine|app|handoff|gate|checker|constant|"
    r"constants|limit|limits"
)

# Verbs only a person can do. Deliberately short.
#
# Cut after dry running, each for a reason:
#   says      "the doc says X" is how everyone cites a document. Not a slip.
#   shows     "the table shows" is plain and standard.
#   refuses   the approved exception is "refuse when worse" as the guard's name.
#   holds     "the file holds" is plain and standard.
#   carries   same.
#   decides   "let the measurement decide" is plain. A checker that fires on
#             good writing is itself broken, so the pattern goes, not the
#             sentence.
HUMAN_VERBS = (
    r"thinks?|knows?|believes?|wants?|wanted|forgets?|"
    r"forgot|remembers?|remembered|lies?|lied|admits?|admitted|agrees?|"
    r"agreed|disagrees?|disagreed|complains?|complained|hopes?|feels?|felt|"
    r"understands?|understood|assumes?|assumed|guesses?|guessed|"
    r"pretends?|pretended|insists?|insisted|worries|worried|likes|liked|"
    r"bleeds?|bled|sings?|sang|sung"
    # likes, not likes?. The bare "like" is a preposition and the optional s
    # matched it in "extracted from the file like everything else".
    # Found and cut 21 August 2026.
    # bleeds, sings: added 30 August 2026, a live reviewer's own test case,
    # "the plugin bleeds tokens", "the dashboard sings to the reader", caught
    # neither. Checked against every real .md, .py and .txt file in this
    # repo first: the only hit is "full-bleed" in three vendored SKILL.md
    # files, an adjective before a noun, not the article-subject-verb shape
    # this pattern requires, so it cannot fire there.
)

# Up to two words may sit between the article and the subject, so that
# "the hooks reference gets wrong" and "the plugin README knows" are caught,
# not only the bare "the docs get wrong".
# Verbs of movement. A thing that cannot walk cannot go, ride or travel.
# Added 21 August 2026. Every one below hit nothing in 25 documents that
# already pass.
#
# Cut after that dry run, each because it appears in writing that is correct:
#   goes, reaches, sits, lives, belongs, teaches, drifts
#
# So this group does not catch "where a new file goes" or "the folder the
# export reads from". No word list can: the same verb is right in one
# sentence and wrong in another, and only the subject tells them apart.
MOTION_VERBS = (
    r"climbs?|climbed|floats?|floated|jumps?|jumped|rides?|rode|"
    r"travels?|traveled|traveled|walks?|walked"
)

LEAD = r"\b(?:the|this|that|these|those|its|their)\s+(?:\w+\s+){0,2}"

PERSONIFY = re.compile(
    LEAD + r"(?:%s)\s+(?:%s)\b" % (SUBJECTS, HUMAN_VERBS), re.I)

MOTION = re.compile(
    LEAD + r"(?:%s)\s+(?:%s)\b" % (SUBJECTS, MOTION_VERBS), re.I)

# "the docs get wrong", "the code gets it right". Separate because "get" needs
# its object to be the tell.
GET_WRONG = re.compile(
    LEAD + r"(?:%s)\s+gets?\s+(?:it\s+)?(?:wrong|right)\b" % SUBJECTS, re.I)

# Fixed idioms. A closed list. Each one was either written by the assistant in
# a real reply or is a stock phrase that would read as web copy here.
IDIOMS = [
    "under the hood", "out of the box", "at a glance", "in the wild",
    "low hanging fruit", "moving parts", "the heavy lifting", "heavy lifting",
    "hit the ground running", "boils down to", "comes down to",
    "the elephant in the room", "a double edged sword", "double-edged sword",
    "best of both worlds", "game changer", "game-changer", "a no brainer",
    "no-brainer", "silver bullet", "the secret sauce", "secret sauce",
    "bread and butter", "the lion's share", "lion's share",
    "paints a picture", "tells the story", "speaks for itself",
    "the whole nine yards", "back to the drawing board", "on the same page",
    "moves the needle", "ahead of the curve", "behind the curve",
    "a trap the", "falls apart", "falls over", "fell over",
    "eats tokens", "eating tokens", "burns tokens", "chews through",
    "spends it back", "spend it back", "pays for itself", "pay dirt",
    "under the covers", "peel back", "dig into", "dive into", "deep dive",
    "unpack this", "unpack that", "circle back", "touch base",
    "at the end of the day", "when all is said and done",
    # Added 21 August 2026. Zero hits on writing that already passes.
    "in step with", "back in step", "out of step", "keep in step",
    "rides along", "ride along", "rides with", "riding along",
]
IDIOM_RE = re.compile(
    r"(?<![A-Za-z])(%s)(?![A-Za-z])"
    % "|".join(re.escape(p) for p in sorted(IDIOMS, key=len, reverse=True)),
    re.I)


def _strip(text):
    """Code, inline code and quoted spans removed. Shared by every check
    below, so a fenced example or a quoted slip is never itself flagged."""
    stripped = re.sub(r"```.*?```", " ", text, flags=re.S)
    stripped = re.sub(r"`[^`\n]*`", " ", stripped)
    # A phrase inside quotation marks is being NAMED, not used. Documentation
    # that records a slip has to be able to write the slip down. The cost is
    # that a figurative sentence quoted from somewhere else goes uncaught,
    # which is correct: quoting another writer is not a style slip.
    stripped = re.sub(r'"[^"\n]{0,120}"', " ", stripped)
    return stripped


def _sentences(text):
    """Plain prose sentences from the text, one per entry.

    A heading line, a table row and a fenced line are not sentences and are
    left out here; the gerund check below reads headings on its own. A line
    is split into sentences on a period, question mark or exclamation mark
    followed by a capital letter or the end of the line.
    """
    out = []
    for line in _strip(text).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("|") or \
                line.startswith("```"):
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        for piece in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", line):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out


# Sentences.md fullrules.txt sets two limits: an instruction stays under
# twenty words, a statement under twenty five. A script cannot parse mood,
# so this is a heuristic: a sentence is an instruction only when its first
# word is one of the imperative verbs this project's own instruction texts
# actually open sentences with (lead.txt, worker.txt, facts.txt, shared.txt,
# fullrules.txt). Anything else is scored as a statement, the looser limit,
# so the check never blocks a true statement for using the tighter number.
IMPERATIVE_LEAD = re.compile(
    r"^(?:write|read|keep|delegate|pick|send|put|do|never|reply|answer|"
    r"quote|add|conclude|recommend|cut|print|embed|set|check|run|count|"
    r"take|report|name|verify|measure|fix|ask|start|state|open|use|say|"
    r"land|stay|draw|find)\b", re.I)


def find_length(text):
    """Sentences over their word limit, as (kind, phrase) pairs."""
    hits = []
    for sentence in _sentences(text):
        words = sentence.split()
        limit = 20 if IMPERATIVE_LEAD.match(sentence) else 25
        if len(words) > limit:
            snippet = " ".join(words[:6])
            hits.append(("length", "%d words over %d: %s ..." %
                         (len(words), limit, snippet)))
    return hits


# "am/is/are/was/were/be/been/being" plus a past participle. The regular
# case is any word ending "ed"; the irregular list below covers the common
# participles that do not. A be-verb before a listed participle is almost
# always passive in this project's prose; the known miss is a predicate
# adjective built from the same word, for example "the file was open",
# which this list excludes by not including "open".
#   done      "the work is done" is how completion reads in plain English
#             and dry running this check flagged it on a normal reply that
#             carried no passive construction anyone would rewrite.
IRREGULAR_PARTICIPLES = (
    r"built|written|sent|kept|read|held|drawn|known|shown|given|taken|"
    r"found|felt|left|sold|lost|won|worn|torn|born|paid|said|had|"
    r"made|seen|gone|chosen|spoken|broken|driven|eaten|fallen|forgotten|"
    r"frozen|grown|hidden|ridden|risen|shaken|stolen|thrown|woken|"
    r"bought|brought|caught|taught|thought|bound|wound|hung|stuck|"
    r"struck|swung|dug|hurt|cost|cut|hit|let|shut|split|spread|burst|"
    r"bet|meant|understood"
)
PASSIVE_RE = re.compile(
    r"\b(?:am|is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?"
    r"(?:\w+ed|%s)\b" % IRREGULAR_PARTICIPLES, re.I)


def find_passive(text):
    """Passive verb phrases, as (kind, phrase) pairs."""
    hits = []
    for sentence in _sentences(text):
        for match in PASSIVE_RE.finditer(sentence):
            hits.append(("passive", match.group(0)))
    return hits


# fullrules.txt: "Never a gerund" for a heading, and its own example of the
# prose form, "never the drawing of the image". Two shapes are matched: the
# heading that opens on an -ing word, and "the X-ing of" anywhere in prose.
# A third shape, an -ing word opening a sentence and taking a verb right
# after it ("Building the vault creates six folders"), is the gerund used
# as the sentence's own subject.
GERUND_OF_RE = re.compile(r"\bthe\s+(\w+ing)\s+of\b", re.I)
GERUND_SUBJECT_RE = re.compile(
    r"^(\w+ing)\s+(?:\w+\s+){0,4}(?:is|are|was|were|makes?|means?|"
    r"creates?|helps?|lets?|allows?|requires?|needs?|takes?|costs?|"
    r"saves?|cuts?)\b", re.I)
GERUND_HEADING_RE = re.compile(r"^#{1,6}\s+(\w+ing)\b", re.I)
# -ing words already lexicalized as a plain noun or adjective in this
# project's prose, not a gerund standing in for an actor. Zero hits on the
# shipped instruction texts.
GERUND_EXCLUDE = {
    "nothing", "something", "everything", "anything", "morning",
    "evening", "during", "following", "according", "interesting",
    "existing", "outstanding", "meaning", "setting",
}


def find_gerund(text):
    """Gerunds standing in for a noun, as (kind, phrase) pairs."""
    hits = []
    stripped = _strip(text)
    for match in GERUND_OF_RE.finditer(stripped):
        if match.group(1).lower() not in GERUND_EXCLUDE:
            hits.append(("gerund", match.group(0)))
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        heading = GERUND_HEADING_RE.match(line)
        if heading:
            if heading.group(1).lower() not in GERUND_EXCLUDE:
                hits.append(("gerund", heading.group(0)))
            continue
        line = re.sub(r"^[-*|]\s*", "", line)
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line):
            match = GERUND_SUBJECT_RE.match(sentence.strip())
            if match and match.group(1).lower() not in GERUND_EXCLUDE:
                hits.append(("gerund", match.group(0)))
    return hits


def _load_jargon():
    """The banned word to plain word map, read from jargon.txt beside this
    file. One "jargon=plain" pair per line. A missing or unreadable file
    turns the jargon check off rather than crashing the gate."""
    path = Path(__file__).resolve().parent / "jargon.txt"
    pairs = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            word, plain = line.split("=", 1)
            word = word.strip().lower()
            if word:
                pairs[word] = plain.strip()
    except OSError:
        pass
    return pairs


JARGON = _load_jargon()
JARGON_RE = re.compile(
    r"\b(%s)\b" % "|".join(re.escape(w) for w in
                            sorted(JARGON, key=len, reverse=True))
) if JARGON else None
if JARGON_RE is not None:
    JARGON_RE = re.compile(JARGON_RE.pattern, re.I)


def find_jargon(text):
    """Banned jargon words, as (kind, phrase) pairs naming the plain word."""
    if JARGON_RE is None:
        return []
    hits = []
    for match in JARGON_RE.finditer(_strip(text)):
        plain = JARGON.get(match.group(0).lower(), "")
        phrase = "%s (use %s)" % (match.group(0), plain) if plain else \
            match.group(0)
        hits.append(("jargon", phrase))
    return hits


# A labelling sentence: one that only names what the sentence before it
# already said, instead of adding a fact of its own. "DensePack packs
# images. That is the whole point of it." The second sentence tells the
# reader nothing the first did not; cut it and no fact is lost, which is
# the same test WRITING-RULES.md applies to every sentence.
#
# A closed list of the nouns a sentence like that reaches for, the same
# design as IDIOMS above: an open list would flag a real fact that happens
# to share a word, "that is the key that opens the door" names a literal
# key, not a label.
LABEL_NOUNS = r"point|idea|reason|goal|purpose|takeaway|gist|upshot|moral|lesson"
LABEL_RE = re.compile(
    r"^(?:this|that|it)\s+(?:is|was)\s+"
    r"(?:exactly\s+|really\s+|just\s+|simply\s+)?"
    r"(?:the\s+)?(?:whole\s+|entire\s+|main\s+|real\s+)?"
    r"(?:%s)\b" % LABEL_NOUNS, re.I)


def find_label(text):
    """Sentences that only label the sentence before them, as (kind, phrase)
    pairs."""
    hits = []
    for sentence in _sentences(text):
        if LABEL_RE.match(sentence):
            hits.append(("label", sentence))
    return hits


# Which surface each fault kind is worth blocking on. A chat reply has
# already reached the reader by the time the Stop gate can run, so blocking
# it costs a second whole reply for one sentence; that is only worth it when
# the reader loses a fact or is actively misled, which is what figurative
# language and jargon do. A file being written or edited has not reached
# anyone yet, so a block there costs a retry before the first version is ever
# seen, and nothing here is weakened for it: every kind stays live.
#   "both"  fires for a chat reply and for a written file.
#   "write" fires for a written file only; on a chat reply it is a style
#           preference, not a lost fact, so the gate leaves it be.
SCOPES = {
    "personification": "both",
    "idiom": "both",
    "jargon": "both",
    "label": "both",
    "length": "write",
    "passive": "write",
    "gerund": "write",
}


def find(text, scope="write"):
    """Every style fault in the text that applies to `scope`, as (kind,
    phrase) pairs.

    Code blocks are skipped whole. A variable named `wants` or a quoted doc
    string is not prose and is not a style slip. Seven kinds are checked:
    personification, idiom, label, length, passive, gerund, jargon. `scope`
    is "chat" for a reply already sent to the reader, where SCOPES above
    narrows the result to the faults worth a second whole reply; "write"
    (the default) is a file the reader or GitHub will read, where every kind is
    checked and none is weakened; "both" checks every kind regardless of
    SCOPES, the same as "write" today, named separately so a caller can ask
    for the unfiltered list on purpose.
    """
    stripped = _strip(text)

    hits = []
    for match in PERSONIFY.finditer(stripped):
        hits.append(("personification", match.group(0)))
    for match in GET_WRONG.finditer(stripped):
        hits.append(("personification", match.group(0)))
    for match in MOTION.finditer(stripped):
        hits.append(("personification", match.group(0)))
    for match in IDIOM_RE.finditer(stripped):
        hits.append(("idiom", match.group(0)))
    hits.extend(find_length(text))
    hits.extend(find_passive(text))
    hits.extend(find_gerund(text))
    hits.extend(find_jargon(text))
    hits.extend(find_label(text))

    if scope != "both":
        hits = [(kind, phrase) for kind, phrase in hits
                if SCOPES.get(kind, "both") in ("both", scope)]

    seen = set()
    out = []
    for kind, phrase in hits:
        key = (kind, phrase.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((kind, phrase))
    return out


KIND_ADVICE = {
    "personification": "give it the real subject and a verb it can do",
    "idiom": "write what it means, not the set phrase",
    "label": "cut it, or replace it with the fact it stands in for",
    "length": "split it into shorter sentences",
    "passive": "name the actor and use active voice",
    "gerund": "name the actor and use a verb, not the -ing noun",
    "jargon": "use the plain word",
}
KIND_ORDER = (
    "personification", "idiom", "label", "length", "passive", "gerund",
    "jargon")


def note(hits):
    """The lines shown under a reply that breaks a style rule, one line per
    kind of fault found."""
    if not hits:
        return ""
    lines = []
    for kind in KIND_ORDER:
        group = [phrase for k, phrase in hits if k == kind]
        if not group:
            continue
        shown = ", ".join('"%s"' % phrase for phrase in group[:4])
        more = "" if len(group) <= 4 else " and %d more" % (len(group) - 4)
        advice = KIND_ADVICE[kind]
        lines.append("%s: %s%s. %s%s." %
                      (kind, shown, more, advice[0].upper(), advice[1:]))
    return "\n\nSTYLE CHECK, not literal:\n" + "\n".join(lines)
