import re
import requests

# ------------------------------------------------------------
# Phase 2: LLM topic/subtopic extraction
# Output format: plain "Topic: / Subtopic:" lines (NOT JSON)
# ------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "deepseek-r1:14b"

LLM_TEMPERATURE = 0
LLM_MAX_RETRIES = 1
LLM_TIMEOUT_SECONDS = None
DEBUG_LLM = True


# # ------------------------------------------------------------
# # Few-shot example (for plain-text format)
# # ------------------------------------------------------------

# FEWSHOT_INPUT = (
#     "Language development: Subject-Verb Agreement, Tenses, Conjunctions; "
#     "Vocabulary development: Root words, Prefixes and Suffixes; "
#     "Reading Comprehension"
# )

# FEWSHOT_OUTPUT = """\
# Topic: Language development
# Subtopic: Subject-Verb Agreement, Tenses, Conjunctions

# Topic: Vocabulary development
# Subtopic: Root words, Prefixes and Suffixes

# Topic: Reading Comprehension"""


# ------------------------------------------------------------
# Prompt builder
# ------------------------------------------------------------

def build_prompt(unit_body_text):

    return f"""You are an information extraction system for university syllabus documents.

Your task is to extract the STRUCTURE of the supplied syllabus unit.

The input is RAW syllabus text from ONE UNIT.

Extract:
- main topics
- subtopics belonging to those topics

The most important requirement is to preserve the structure and wording
of the source without inventing relationships.

==================================================
CORE RULES
==================================================

1. Use ONLY information explicitly present in the input.

2. Preserve the original wording of every extracted item.

3. Do NOT:
   - paraphrase
   - summarize
   - correct spelling
   - correct grammar
   - rename topics
   - add information
   - remove meaningful information
   - use outside knowledge
   - invent relationships

4. Every meaningful syllabus item must appear somewhere in the output.

5. Do NOT merge multiple independent syllabus items into one large topic.

6. Do NOT create a hierarchy unless the source provides reasonable
   evidence for that relationship.

7. When uncertain, prefer separate TOPICS rather than inventing
   a Topic → Subtopic relationship.

==================================================
STRUCTURE TYPES
==================================================

A unit may contain:

1. Flat topics
2. Topics with subtopics
3. A mixture of both

Do NOT assume that the entire unit follows one structure.

==================================================
RULE 1 — EXPLICIT CATEGORY STRUCTURE
==================================================

A colon can indicate:

MAIN TOPIC: item A, item B, item C

Example:

Language development: Subject-Verb Agreement, Tenses (simple), Conjunctions

Output:

Topic: Language development
Subtopic: Subject-Verb Agreement
Subtopic: Tenses (simple)
Subtopic: Conjunctions

The text before the colon is the main topic.

The items after the colon belong to that topic ONLY when the
punctuation and wording clearly support that interpretation.

Do NOT include the colon in the extracted text.

==================================================
RULE 2 — SEMICOLONS
==================================================

A semicolon usually separates major syllabus categories.

Example:

Language development: A, B; Vocabulary development: C, D; Reading: E

Output:

Topic: Language development
Subtopic: A
Subtopic: B

Topic: Vocabulary development
Subtopic: C
Subtopic: D

Topic: Reading
Subtopic: E

A semicolon should NOT cause content from one category to become
a subtopic of the previous category.

==================================================
RULE 3 — DASHES
==================================================

A dash is NOT automatically a Topic → Subtopic relationship.

Example:

Characteristic equation – Eigenvalues and Eigenvectors of a real matrix –
Properties of eigen-values and eigenvectors – Cayley-Hamilton Theorem

The safe interpretation is:

Topic: Characteristic equation
Topic: Eigenvalues and Eigenvectors of a real matrix
Topic: Properties of eigen-values and eigenvectors
Topic: Cayley-Hamilton Theorem

Do NOT automatically create:

Topic: Characteristic equation
Subtopic: Eigenvalues...

unless the source clearly establishes that hierarchy.

However, a dash-separated list MAY represent subtopics when the
preceding wording clearly establishes a category.

Example:

Size dependent Properties – Thermal, Optical, Chemical, Electronic
and Mechanical

Output:

Topic: Size dependent Properties
Subtopic: Thermal
Subtopic: Optical
Subtopic: Chemical
Subtopic: Electronic
Subtopic: Mechanical

The relationship is supported because the listed items are explicitly
presented as properties under the preceding category.

==================================================
RULE 4 — COMMA-SEPARATED ITEMS
==================================================

Do NOT automatically treat every comma-separated phrase as a separate
subtopic.

Determine whether the comma-separated items are:

A. independent topics,
B. items belonging to a clearly identified topic, or
C. simply part of one phrase.

Example:

Types of optical fibres (material, refractive index, mode)

should remain:

Topic: Fibre optics
Subtopic: Types of optical fibres (material, refractive index, mode)

Do NOT produce:

Subtopic: material
Subtopic: refractive index
Subtopic: mode

unless the source explicitly presents them as separate syllabus items.

==================================================
RULE 5 — LISTS INSIDE A CLEAR CATEGORY
==================================================

When a topic clearly introduces a list of items, preserve the
relationship.

Example:

Types of lasers – Nd: YAG, & CO2 lasers – Basics of diode lasers

Output may be:

Topic: Photonics
Subtopic: Types of lasers
Subtopic: Nd: YAG, & CO2 lasers
Subtopic: Basics of diode lasers

Do not split a single named item into artificial pieces.

For example:

Nd: YAG, & CO2 lasers

must remain one extracted item.

==================================================
RULE 6 — DO NOT SPLIT CONNECTED PHRASES
==================================================

A phrase containing words that are grammatically or conceptually
connected should remain together.

Examples:

"theory and experiment"

"series and parallel"

"Time independent and time dependent equations"

"pulse echo system through transmission and reflection modes"

"Industrial and Medical Applications"

These should NOT automatically be split into separate subtopics.

Preserve them as one item when they form one syllabus phrase.

==================================================
RULE 7 — DO NOT CREATE ARTIFICIAL SUBTOPICS
==================================================

Do NOT turn generic words or fragments into subtopics.

For example:

Properties of matter: Elasticity – Hooke’s law – Relationship between
three moduli of elasticity – stress-strain diagram

Valid:

Topic: Properties of matter
Subtopic: Elasticity
Subtopic: Hooke’s law
Subtopic: Relationship between three moduli of elasticity
Subtopic: stress-strain diagram

But do NOT create artificial fragments such as:

Subtopic: theory
Subtopic: experiment
Subtopic: series
Subtopic: parallel

when those words belong to a larger source phrase.

==================================================
RULE 8 — PRESERVE COMPLETE SYLLABUS ITEMS
==================================================

Do not split an item when doing so would change its meaning.

Example:

"electroplating (Au) and electroless (Ni) plating"

should remain:

Subtopic: electroplating (Au) and electroless (Ni) plating

NOT:

Subtopic: electroplating (Au)
Subtopic: electroless (Ni) plating

Similarly:

"Particle in a one-dimensional box and extension to three dimensional box"

should remain one item.

==================================================
RULE 9 — TOPIC VS SUBTOPIC
==================================================

Use a TOPIC when the source presents an independent syllabus concept.

Use a SUBTOPIC when the source clearly presents the item as part of
a preceding category.

Example:

Input:

Corrosion – Definition – Classification of corrosion – Chemical corrosion

Output:

Topic: Corrosion
Subtopic: Definition
Subtopic: Classification of corrosion
Subtopic: Chemical corrosion

But:

Input:

Characteristic equation – Eigenvalues and Eigenvectors of a real matrix –
Properties of eigen-values and eigenvectors

Output:

Topic: Characteristic equation
Topic: Eigenvalues and Eigenvectors of a real matrix
Topic: Properties of eigen-values and eigenvectors

Do not force hierarchy simply because several items are adjacent.

==================================================
RULE 10 — DO NOT CROSS STRUCTURAL BOUNDARIES
==================================================

Never move an item into a previous topic merely because it appears
after that topic.

Each new clearly identifiable category starts a new topic.

Example:

Language development: A, B, C;
Vocabulary development: D, E;
Reading: F, G

Correct:

Topic: Language development
Subtopic: A
Subtopic: B
Subtopic: C

Topic: Vocabulary development
Subtopic: D
Subtopic: E

Topic: Reading
Subtopic: F
Subtopic: G

Do NOT place D or E under Language development.

==================================================
RULE 11 — EXACT TEXT
==================================================

Every extracted item must come from the input.

Preserve:

- spelling
- capitalization
- wording
- abbreviations
- symbols
- numbers
- parentheses
- meaningful punctuation

Remove ONLY punctuation that is being used as a structural separator.

Example:

Input:
Language development: Subject-Verb Agreement

Output:

Topic: Language development
Subtopic: Subject-Verb Agreement

NOT:

Topic: Language development:
Subtopic: Subject-Verb Agreement

==================================================
RULE 12 — DO NOT LOSE ITEMS
==================================================

Every meaningful syllabus item must appear in the output.

Do not silently discard:

- definitions
- classifications
- methods
- applications
- properties
- examples
- named systems
- named techniques
- experiments
- measurements
- equations
- laws
- procedures

If an item is explicitly present and meaningful, preserve it.

==================================================
IMPORTANT EDGE CASE
==================================================

Do NOT interpret isolated letters or short fragments as independent
topics or subtopics when they are clearly part of a larger phrase.

Example:

pulse echo system through transmission and reflection modes – A, B and C – scan displays

should preserve:

Subtopic: pulse echo system through transmission and reflection modes
Subtopic: A, B and C – scan displays

Do NOT produce:

Subtopic: A
Subtopic: B
Subtopic: C

==================================================
OUTPUT FORMAT
==================================================

Return ONLY the following format.

For an independent topic:

Topic: <exact text>

For a topic with subtopics:

Topic: <exact text>
Subtopic: <exact text>
Subtopic: <exact text>

Multiple topics are allowed.

Example:

Topic: Language development
Subtopic: Subject-Verb Agreement
Subtopic: Tenses (simple)
Subtopic: Conjunctions

Topic: Vocabulary development
Subtopic: Root words – Prefixes and Suffixes
Subtopic: Standard abbreviations

Topic: Nanoparticles and its uniqueness

==================================================
NO EXTRA OUTPUT
==================================================

Return ONLY lines beginning with:

Topic:
Subtopic:

Do NOT return:

- explanations
- reasoning
- markdown
- JSON
- comments
- introductions
- conclusions

==================================================
INPUT SYLLABUS UNIT
==================================================

{unit_body_text}
"""

# ------------------------------------------------------------
# Ollama request
# ------------------------------------------------------------

def call_ollama(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": LLM_TEMPERATURE,
            "num_predict": 1024,
            "num_ctx": 8192,
        },
    }
    # NuExtract needs raw mode + stop token; general models just get plain text
    if OLLAMA_MODEL.startswith("nuextract"):
        payload["raw"] = True
        payload["options"]["stop"] = ["<|input|>"]
    # NOTE: no "format": "json" — we want plain text output now

    resp = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json().get("response", "")


# ------------------------------------------------------------
# Plain-text response parser
# Parses:
#   Topic: <text>
#   Subtopic: <item1>, <item2>, <item3>
# ------------------------------------------------------------

def parse_plain_text_response(text):
    """
    Converts the model's plain-text Topic/Subtopic output into
    a list of (topic, subtopic) tuples.
    Returns None if no Topic: lines are found at all.
    """
    rows = []
    current_topic = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if line.lower().startswith("topic:"):
            current_topic = line[len("topic:"):].strip()
            # Emit a placeholder row; will be replaced if Subtopic follows
            rows.append((current_topic, ""))

        elif line.lower().startswith("subtopic:") and current_topic is not None:
            subtopic_text = line[len("subtopic:"):].strip()

            # Replace the placeholder row we added for this topic
            if rows and rows[-1] == (current_topic, ""):
                rows.pop()

            if subtopic_text:
                rows.append((current_topic, subtopic_text))
            else:
                rows.append((current_topic, ""))

    return rows if rows else None


# ------------------------------------------------------------
# Source-grounding validation
# Prevents hallucinated topics from passing through silently.
# ------------------------------------------------------------

def _normalize(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _appears_in_source(value, source_norm):
    value = _normalize(value)
    if not value:
        return False
    words = value.split()
    # Short phrases: exact match
    if len(words) <= 3:
        return value in source_norm
    # Long phrases: check any 3-word sliding window
    for i in range(len(words) - 2):
        if " ".join(words[i:i + 3]) in source_norm:
            return True
    return False


def validate_against_source(rows, source_text):
    """Returns True if all topics and subtopics can be traced to the source."""
    source_norm = _normalize(source_text)
    for topic, subtopic in rows:
        if not _appears_in_source(topic, source_norm):
            if DEBUG_LLM:
                print(f"    [LLM] Rejected invented topic: {topic!r}")
            return False
        if subtopic and not _appears_in_source(subtopic, source_norm):
            if DEBUG_LLM:
                print(f"    [LLM] Rejected invented subtopic: {subtopic!r}")
            return False
    return True


# ------------------------------------------------------------
# Main extraction function
# ------------------------------------------------------------

def extract_topics_llm(unit_body_text):
    """
    Returns list of (topic, subtopic) tuples, or None on failure.
    Caller should use split_topics_fallback() when None is returned.
    """
    prompt = build_prompt(unit_body_text)

    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            raw_response = call_ollama(prompt)
        except requests.exceptions.RequestException as e:
            print(f"    [LLM] Ollama request failed ({e}); is 'ollama serve' running?")
            return None

        if DEBUG_LLM:
            print(f"    [LLM] Raw response (attempt {attempt + 1}):")
            print(raw_response)

        rows = parse_plain_text_response(raw_response)

        if rows is None:
            print(
                f"    [LLM] No Topic: lines found on attempt {attempt + 1}" +
                (", retrying..." if attempt < LLM_MAX_RETRIES else ", falling back to regex")
            )
            continue

        if not validate_against_source(rows, unit_body_text):
            print(
                f"    [LLM] Source grounding failed on attempt {attempt + 1}" +
                (", retrying..." if attempt < LLM_MAX_RETRIES else ", falling back to regex")
            )
            continue

        return rows,raw_response

    return None,raw_response


# ------------------------------------------------------------
# Fallback: deterministic split (used only if LLM fails/times out)
# ------------------------------------------------------------

def split_topics_fallback(unit_body):
    unit_body = re.sub(r"\s+", " ", unit_body).strip()
    if not unit_body:
        return []

    # Split on en-dash or " - " only — never split on bare "-"
    # to preserve compound words like "object-oriented", "client-server"
    if "\u2013" in unit_body:
        parts = unit_body.split("\u2013")
    elif " - " in unit_body:
        parts = unit_body.split(" - ")
    else:
        parts = unit_body.split(".")

    topics = []
    for p in parts:
        p = p.strip(" .,:;")
        if len(p) > 3:
            topics.append(p)
    return [(t, "") for t in topics]
