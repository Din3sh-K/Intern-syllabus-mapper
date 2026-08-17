import re
import json
import requests


# ============================================================
# Phase 2: Semantic syllabus topic/subtopic extraction
#
# The LLM is responsible for understanding hierarchy.
#
# We DO NOT assume:
#   ":" = topic
#   "," = subtopic
#   ";" = topic separator
#
# Different syllabus formats are allowed.
# ============================================================


OLLAMA_URL = "http://localhost:11434/api/generate"

# Use a general instruction-following model.
# Change this to whatever model you actually have.
OLLAMA_MODEL = "nuextract"

LLM_TEMPERATURE = 0

# Give the model enough time, but don't allow infinite hanging.
LLM_TIMEOUT_SECONDS = 180

LLM_MAX_RETRIES = 1

DEBUG_LLM = True


# ------------------------------------------------------------
# Expected output schema
# ------------------------------------------------------------

SCHEMA = {
    "topics": [
        {
            "topic": "",
            "subtopics": []
        }
    ]
}


# ------------------------------------------------------------
# Prompt
# ------------------------------------------------------------

def build_prompt(unit_body_text):

    schema = json.dumps(
        SCHEMA,
        indent=2
    )

    return f"""
You are a syllabus information extraction engine.

Your task is to extract the hierarchical structure of a university
syllabus unit.

The syllabus formatting may vary between subjects.

DO NOT assume that:
- a colon always means a topic
- a comma always means a subtopic
- a semicolon always means a new topic
- a dash always means a subtopic
- capitalization alone determines hierarchy

Instead, infer the topic/subtopic hierarchy from the meaning,
wording, numbering, headings, indentation, punctuation and
overall structure of the supplied syllabus text.

IMPORTANT RULES:

1. Extract only information that is present in the input.
2. Do not invent topics.
3. Do not explain the topics.
4. Do not summarize the syllabus.
5. Preserve the original wording as closely as possible.
6. A topic is a major concept or heading within the unit.
7. A subtopic is a clearly related concept belonging under that topic.
8. If a topic has no meaningful subtopics, use an empty list.
9. Do not create unnecessary hierarchy.
10. Return ONLY valid JSON.
11. Do not use markdown.
12. Do not include explanations before or after the JSON.

Expected JSON structure:

{schema}

SYLLABUS UNIT:

{unit_body_text}

Return the JSON now.
""".strip()


# ------------------------------------------------------------
# Ollama request
# ------------------------------------------------------------

def call_ollama(prompt):

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": LLM_TEMPERATURE
        }
    }

    print(
        f"    [LLM] Sending request to Ollama ({OLLAMA_MODEL})...",
        flush=True
    )

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=LLM_TIMEOUT_SECONDS
    )

    response.raise_for_status()

    print(
        "    [LLM] Response received!",
        flush=True
    )

    return response.json().get("response", "")


# ------------------------------------------------------------
# JSON extraction
# ------------------------------------------------------------

def extract_first_json(text):

    decoder = json.JSONDecoder()

    brace_index = text.find("{")

    if brace_index == -1:

        raise json.JSONDecodeError(
            "No JSON object found",
            text,
            0
        )

    obj, _ = decoder.raw_decode(
        text,
        brace_index
    )

    return obj


# ------------------------------------------------------------
# Schema validation
# ------------------------------------------------------------

def validate_topics(parsed):

    if not isinstance(parsed, dict):
        return False

    if "topics" not in parsed:
        return False

    if not isinstance(parsed["topics"], list):
        return False

    for item in parsed["topics"]:

        if not isinstance(item, dict):
            return False

        topic = item.get("topic")

        subtopics = item.get("subtopics")

        if not isinstance(topic, str):
            return False

        if not topic.strip():
            return False

        if not isinstance(subtopics, list):
            return False

        if not all(
            isinstance(x, str)
            for x in subtopics
        ):
            return False

    return True


# ------------------------------------------------------------
# Source grounding validation
# ------------------------------------------------------------

def normalize_for_matching(text):

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    text = re.sub(
        r"[^\w\s]",
        " ",
        text
    )

    return text.strip()


def appears_in_source(value, source):

    value = normalize_for_matching(value)
    source = normalize_for_matching(source)

    if not value:
        return False

    return value in source


def validate_against_source(parsed, source):

    for item in parsed["topics"]:

        topic = item["topic"]

        # Topic should originate from the syllabus.
        if not appears_in_source(topic, source):

            if DEBUG_LLM:
                print(
                    f"    [LLM] Rejected invented topic: {topic!r}"
                )

            return False

        for subtopic in item["subtopics"]:

            if not appears_in_source(
                subtopic,
                source
            ):

                if DEBUG_LLM:
                    print(
                        f"    [LLM] Rejected invented subtopic: "
                        f"{subtopic!r}"
                    )

                return False

    return True


# ------------------------------------------------------------
# Convert JSON -> rows
# ------------------------------------------------------------

def convert_to_rows(parsed):

    rows = []

    for item in parsed["topics"]:

        topic = item["topic"].strip()

        subtopics = [
            x.strip()
            for x in item["subtopics"]
            if x.strip()
        ]

        if subtopics:

            for subtopic in subtopics:

                rows.append(
                    (
                        topic,
                        subtopic
                    )
                )

        else:

            rows.append(
                (
                    topic,
                    ""
                )
            )

    return rows


# ------------------------------------------------------------
# Main extraction function
# ------------------------------------------------------------

def extract_topics_llm(unit_body_text):

    prompt = build_prompt(
        unit_body_text
    )

    for attempt in range(
        LLM_MAX_RETRIES + 1
    ):

        try:

            raw_response = call_ollama(
                prompt
            )

        except requests.exceptions.RequestException as e:

            print(
                f"    [LLM] Ollama request failed: {e}"
            )

            return None

        if DEBUG_LLM:

            print(
                "    [LLM] Raw response:"
            )

            print(
                raw_response[:1000]
            )

        # ----------------------------------------------------
        # Parse JSON
        # ----------------------------------------------------

        try:

            parsed = extract_first_json(
                raw_response
            )

        except json.JSONDecodeError:

            print(
                f"    [LLM] Invalid JSON "
                f"on attempt {attempt + 1}"
            )

            continue

        # ----------------------------------------------------
        # Schema validation
        # ----------------------------------------------------

        if not validate_topics(parsed):

            print(
                f"    [LLM] Schema validation failed "
                f"on attempt {attempt + 1}"
            )

            continue

        # ----------------------------------------------------
        # Source validation
        # ----------------------------------------------------

        if not validate_against_source(
            parsed,
            unit_body_text
        ):

            print(
                f"    [LLM] Source validation failed "
                f"on attempt {attempt + 1}"
            )

            continue

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------

        return convert_to_rows(
            parsed
        )

    print(
        "    [LLM] Extraction failed."
    )

    return None


# ------------------------------------------------------------
# Emergency fallback
#
# This is intentionally conservative.
# It does NOT attempt to understand every syllabus format.
#
# It simply prevents the entire pipeline from crashing if the
# LLM is unavailable.
# ------------------------------------------------------------

def split_topics_fallback(unit_body):

    text = re.sub(
        r"\s+",
        " ",
        unit_body
    ).strip()

    if not text:
        return []

    return [
        (
            text,
            ""
        )
    ]