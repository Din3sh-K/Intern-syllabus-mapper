import re
import requests

# ------------------------------------------------------------
# Phase 2: LLM topic/subtopic extraction
# Output format: plain "Topic: / Subtopic:" lines (NOT JSON)
# ------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi3:mini"

LLM_TEMPERATURE = 0
LLM_MAX_RETRIES = 1
LLM_TIMEOUT_SECONDS = None
DEBUG_LLM = True


# ------------------------------------------------------------
# Few-shot example (for plain-text format)
# ------------------------------------------------------------

FEWSHOT_INPUT = (
    "Language development: Subject-Verb Agreement, Tenses, Conjunctions; "
    "Vocabulary development: Root words, Prefixes and Suffixes; "
    "Reading Comprehension"
)

FEWSHOT_OUTPUT = """\
Topic: Language development
Subtopic: Subject-Verb Agreement, Tenses, Conjunctions

Topic: Vocabulary development
Subtopic: Root words, Prefixes and Suffixes

Topic: Reading Comprehension"""


# ------------------------------------------------------------
# Prompt builder
# ------------------------------------------------------------

def build_prompt(unit_body_text):

    return f"""You are an information extraction system for university syllabus documents.

Your task is to extract the STRUCTURE of the supplied syllabus text.

The input is raw syllabus text from ONE UNIT.

Your job is to identify:
- main topics
- subtopics belonging to those topics

You MUST use only information explicitly present in the input.

==================================================
IMPORTANT: THERE MAY BE DIFFERENT STRUCTURES
==================================================

The syllabus may contain:

1. FLAT TOPICS
2. TOPICS WITH SUBTOPICS
3. A MIXTURE OF BOTH

Do NOT assume that an entire unit must follow only one structure.

--------------------------------------------------
CASE 1: TOPIC WITH EXPLICIT CATEGORY HEADING
--------------------------------------------------

When the syllabus contains:

Topic name: item A, item B, item C

the text before the colon is normally the MAIN TOPIC.

Example:

Language development: Subject-Verb Agreement, Tenses (simple), Conjunctions

Output:

Topic: Language development
Subtopic: Subject-Verb Agreement
Subtopic: Tenses (simple)
Subtopic: Conjunctions

Another example:

Vocabulary development: Root words – Prefixes and Suffixes, Standard abbreviations

Output:

Topic: Vocabulary development
Subtopic: Root words – Prefixes and Suffixes
Subtopic: Standard abbreviations

IMPORTANT:

The text before the colon is NOT part of the subtopic.

WRONG:

Topic: Language development: Subject-Verb Agreement

CORRECT:

Topic: Language development
Subtopic: Subject-Verb Agreement

--------------------------------------------------
CASE 2: TOPIC WITHOUT SUBTOPICS
--------------------------------------------------

A topic may exist independently.

Example:

Nanoparticles and its uniqueness.
Classification of nanoparticles.

Output:

Topic: Nanoparticles and its uniqueness
Topic: Classification of nanoparticles

Do NOT create subtopics unless the source clearly indicates a relationship.

--------------------------------------------------
CASE 3: DASHES DO NOT AUTOMATICALLY MEAN HIERARCHY
--------------------------------------------------

A dash may simply separate independent syllabus items.

Example:

Characteristic equation – Eigenvalues and Eigenvectors of a real matrix –
Properties of eigen-values and eigenvectors –
Cayley-Hamilton Theorem – statement and applications

This may represent:

Topic: Characteristic equation
Topic: Eigenvalues and Eigenvectors of a real matrix
Topic: Properties of eigen-values and eigenvectors
Topic: Cayley-Hamilton Theorem
Topic: statement and applications

Do NOT automatically interpret:

A – B

as:

Topic A
    Subtopic B

A dash alone is NOT sufficient evidence of a parent-child relationship.

--------------------------------------------------
CASE 4: COMMAS DO NOT AUTOMATICALLY MEAN SUBTOPICS
--------------------------------------------------

Example:

Thermal, Optical, Chemical, Electronic and Mechanical

Do NOT automatically create:

Topic: Thermal
Topic: Optical
Topic: Chemical
...

Instead, determine whether these are properties belonging to a previously
identified topic.

For example:

Size dependent Properties – Thermal, Optical, Chemical, Electronic and Mechanical

should preserve the relationship:

Topic: Size dependent Properties
Subtopic: Thermal
Subtopic: Optical
Subtopic: Chemical
Subtopic: Electronic
Subtopic: Mechanical

when the wording clearly indicates that these are properties of
"Size dependent Properties".

--------------------------------------------------
CASE 5: MIXED STRUCTURE
--------------------------------------------------

A unit can contain both hierarchical and flat topics.

Example:

Language development: Subject-Verb Agreement, Tenses, Conjunctions;
Vocabulary development: Root words, Prefixes and Suffixes;
Nanoparticles and its uniqueness;
Classification of nanoparticles.

Output:

Topic: Language development
Subtopic: Subject-Verb Agreement
Subtopic: Tenses
Subtopic: Conjunctions

Topic: Vocabulary development
Subtopic: Root words
Subtopic: Prefixes and Suffixes

Topic: Nanoparticles and its uniqueness

Topic: Classification of nanoparticles

--------------------------------------------------
HIERARCHY DECISION RULE
--------------------------------------------------

Use the following priority:

1. Explicit colon structure is strong evidence of a topic followed by
   its items.

2. Explicit wording such as:
   "types of..."
   "properties of..."
   "techniques..."
   "methods..."
   "applications..."
   may indicate that following items belong to the preceding topic,
   but only when the relationship is clearly supported by the source.

3. A dash alone is NOT evidence of hierarchy.

4. A comma alone is NOT evidence of hierarchy.

5. Semicolon usually separates major categories/topics.

6. Do NOT invent relationships using outside knowledge.

7. If uncertain, prefer a FLAT TOPIC rather than inventing a hierarchy.

--------------------------------------------------
EXACT TEXT RULE
--------------------------------------------------

Every extracted item MUST come from the supplied input.

DO NOT:

- paraphrase
- summarize
- correct spelling
- correct grammar
- change capitalization
- rename anything
- invent information
- add information
- remove meaningful words
- use outside knowledge
- merge unrelated items

Preserve the wording from the source as closely as possible.

However, remove only structural punctuation that belongs to the
separator itself.

For example:

Input:

Language development: Subject-Verb Agreement

Output:

Topic: Language development
Subtopic: Subject-Verb Agreement

NOT:

Topic: Language development:
Subtopic: Subject-Verb Agreement

--------------------------------------------------
IMPORTANT: DO NOT LOSE ITEMS
--------------------------------------------------

Every meaningful syllabus item in the source must appear in the output.

Do not silently discard an item.

Do not combine multiple independent syllabus items into one item.

For example:

Writing: Describing an object, the process of an event/experiment
and others, Paragraph Writing

must NOT become:

Topic: Writing: Describing an object, the process...

Instead:

Topic: Writing
Subtopic: Describing an object
Subtopic: the process of an event/experiment and others
Subtopic: Paragraph Writing

--------------------------------------------------
OUTPUT FORMAT
--------------------------------------------------

Return ONLY these lines.

For a topic without subtopics:

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

Topic: Vocabulary development
Subtopic: Root words – Prefixes and Suffixes
Subtopic: Standard abbreviations

Topic: Nanoparticles and its uniqueness

--------------------------------------------------
NO EXTRA OUTPUT
--------------------------------------------------

Return ONLY:

Topic:
Subtopic:

Do not return:

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
            "num_ctx": 4096,
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
            subtopics_raw = line[len("subtopic:"):].strip()
            subtopics = [s.strip() for s in subtopics_raw.split(",") if s.strip()]

            # Replace the placeholder row we added for this topic
            if rows and rows[-1] == (current_topic, ""):
                rows.pop()

            if subtopics:
                for st in subtopics:
                    rows.append((current_topic, st))
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
