# Syllabus Topic Extraction – Development History

## 1. Project Overview

The objective of this project is to process university syllabus PDFs and convert their unstructured syllabus content into a structured representation of subjects, units, topics, and subtopics.

The expected final output is a structured dataset containing records such as:

- Subject code
- Subject name
- Unit number
- Unit title
- Topic
- Subtopic

This structured syllabus information is intended to be used in the later stages of the project for syllabus-to-textbook mapping, where each syllabus topic can be mapped to relevant textbook pages.

The extraction pipeline was developed iteratively after evaluating multiple approaches. The development progressed from rule-based extraction to a specialized extraction model and finally to instruction-following LLMs.

---

## 2. Development Approach

The extraction system was developed through the following stages:

```text
University Syllabus PDF
        |
        v
1. Rule-based topic extraction
        |
        | Problems with real syllabus structure
        v
2. NuExtract-based extraction
        |
        | Structured JSON and semantic hierarchy limitations
        v
3. General-purpose LLM evaluation
        |
        | Multiple models evaluated
        v
4. Current LLM-based unit-wise extraction
        |
        v
Structured Topic / Subtopic Dataset
```

The important change during development was the realization that syllabus extraction is not only a text parsing problem. The system must also understand the relationship between syllabus concepts.

---

## 3. Initial Approach – Rule-Based Extraction

### 3.1 Approach

The initial implementation used a rule-based extraction approach through `dataextract.py`.

The objective at this stage was to identify syllabus topics directly from the extracted PDF text using deterministic text-processing and pattern-based rules.

The initial assumption was that the syllabus could be sufficiently structured using formatting patterns and textual separators.

The approach primarily focused on extracting topics from the syllabus rather than determining topic/subtopic hierarchy.

### 3.2 Initial Observation

After examining the extraction output from actual university syllabus documents, an important limitation became apparent.

The syllabus does not follow a single consistent textual structure.

For example, a syllabus may contain:

```text
Language development: Subject-Verb Agreement, Tenses, Conjunctions
```

while another section may contain:

```text
Characteristic equation – Eigenvalues and Eigenvectors of a real matrix –
Properties of eigenvalues and eigenvectors
```

Another section may contain:

```text
Size dependent Properties – Thermal, Optical, Chemical, Electronic and Mechanical
```

These structures cannot reliably be interpreted using a fixed set of delimiters.

More importantly, the output revealed that syllabus content contains **hierarchical relationships** that are not always represented by explicit formatting.

For example:

```text
Size dependent Properties
    ├── Thermal
    ├── Optical
    ├── Chemical
    ├── Electronic
    └── Mechanical
```

The relationship between these concepts needs to be understood rather than simply split using punctuation.

### 3.3 Key Limitation

The main limitation of the initial approach was therefore not simply that the regex rules were incomplete.

The deeper problem was that the extraction task required understanding **semantic hierarchy**.

A rule-based parser can identify separators such as commas, semicolons, colons, dashes, and periods — but these separators do not consistently represent the same structural relationship across different syllabus documents.

For example, `A – B` does not necessarily mean `Topic: A / Subtopic: B`. Similarly, `A, B, C` does not necessarily mean that A, B, and C are subtopics.

### 3.4 Conclusion

The rule-based approach was therefore not considered sufficient for the complete use case.

The key realization was:

> The system needs to understand the semantic hierarchy of syllabus content rather than only identify textual separators.

This led to the exploration of language-model-based extraction.

---

## 4. Second Approach – NuExtract

### 4.1 Motivation

After the limitations of purely rule-based extraction became apparent, a specialized information-extraction model, NuExtract, was evaluated.

The motivation was to use a model specifically designed for structured information extraction rather than implementing increasingly complex parsing rules manually.

The intended output was a structured representation of syllabus topics and their relationships.

### 4.2 Observed Limitations

During experimentation, NuExtract did not reliably produce the structured output required for this use case.

One of the major difficulties was generating a valid structured JSON representation consistently.

The model also had limitations in understanding the semantic hierarchy required by the syllabus. The task was not simply "find important phrases," but rather determining which phrases are major topics and which phrases belong underneath those topics.

For example, given:

```text
Size dependent Properties – Thermal, Optical, Chemical,
Electronic and Mechanical
```

the desired interpretation is:

```text
Topic: Size dependent Properties
    Subtopic: Thermal
    Subtopic: Optical
    Subtopic: Chemical
    Subtopic: Electronic
    Subtopic: Mechanical
```

A reliable extraction system must understand that the latter concepts belong to the preceding concept.

### 4.3 Why the Approach Was Changed

The experimentation with NuExtract led to an important design decision.

The problem required more than specialized parsing capability. It required a model capable of following detailed instructions and making contextual hierarchy decisions.

Additionally, the low-parameter extraction model was not reliably producing the structured JSON output required by the pipeline.

Therefore, the project moved from a specialized parsing model toward general-purpose instruction-following LLMs.

---

## 5. Transition to General-Purpose LLMs

The next stage was to evaluate general-purpose LLMs for syllabus hierarchy extraction.

```text
Syllabus text
      |
      v
Understand context
      |
      v
Identify major concepts
      |
      v
Determine relationships
      |
      v
Classify as Topic / Subtopic
```

This is fundamentally a semantic interpretation task.

General-purpose LLMs provide stronger instruction-following and contextual understanding, making them more suitable for determining hierarchy from irregular syllabus text.

Multiple models were subsequently evaluated. The detailed model-level evaluation is documented separately in `model_evaluation.md`.

---

## 6. Current Approach – LLM-Based Unit-Wise Extraction

The current implementation is based on `Topicextractor2.py` and `main.py`.

The current pipeline deliberately separates **PDF parsing** from **semantic topic extraction**.

```text
                Syllabus PDF
                     |
                     v
              pdf_extractor.py
                     |
                     v
              Course Detection
                     |
                     v
               Course Block
                     |
                     v
                Unit Detection
                     |
          +----------+----------+
          |          |          |
        Unit I     Unit II    Unit III ...
          |          |          |
          v          v          v
       LLM Call   LLM Call   LLM Call
          |          |          |
          v          v          v
      Topic /    Topic /    Topic /
      Subtopic   Subtopic   Subtopic
          |          |          |
          +----------+----------+
                     |
                     v
             Source Validation
                     |
             +-------+-------+
             |               |
          Valid            Invalid
             |               |
             v               v
        Accept result      Retry
                             |
                         If failure
                             |
                             v
                    Deterministic fallback
                             |
                             v
                         Excel output
```

---

## 7. PDF and Unit Extraction

The first stage is implemented in `pdf_extractor.py`.

This stage is intentionally responsible only for structural extraction from the PDF. It identifies:

- Course code
- Course title
- Course block
- Unit number
- Unit title
- Unit body

It does **not** attempt to determine topic/subtopic hierarchy.

This separation is important because PDF parsing and semantic hierarchy extraction are different problems.

The unit extraction process produces data conceptually similar to:

```text
Subject:
    UEN2176 - TECHNICAL ENGLISH

Unit:
    Unit I

Unit Body:
    Language development: Subject-Verb Agreement, Tenses...
    Vocabulary development: Root words...
    Reading: ...
    Writing: ...
```

---

## 8. Unit-Wise LLM Processing

The current system does not send the entire subject to the LLM in a single request. Instead, the subject is divided into its individual units.

```text
UEN2176
|
+-- Unit I  -> LLM call
+-- Unit II -> LLM call
+-- Unit III -> LLM call
+-- Unit IV -> LLM call
+-- Unit V  -> LLM call
```

Each LLM request therefore receives only the syllabus text corresponding to one unit. This provides a more focused extraction context and makes the extraction process easier to control and debug.

Each unit is independently interpreted by the model.

---

## 9. Prompt-Based Hierarchy Extraction

The current prompt was developed specifically to handle the different structural patterns observed during testing. Rather than assuming that punctuation always represents hierarchy, the prompt instructs the LLM to reason about the relationship between concepts.

### 9.1 Explicit Topic Categories

```text
Language development: Subject-Verb Agreement, Tenses, Conjunctions
```

Expected interpretation:

```text
Topic: Language development
Subtopic: Subject-Verb Agreement
Subtopic: Tenses
Subtopic: Conjunctions
```

### 9.2 Independent Topics

Some syllabus concepts are already independent topics.

```text
Nanoparticles and its uniqueness.
Classification of nanoparticles.
```

Expected interpretation:

```text
Topic: Nanoparticles and its uniqueness
Topic: Classification of nanoparticles
```

The system should not invent subtopics where the source does not establish a relationship.

### 9.3 Ambiguous Dashes

A dash is not automatically treated as a parent-child relationship.

```text
Characteristic equation – Eigenvalues and Eigenvectors
```

does not automatically mean `Topic: Characteristic equation / Subtopic: Eigenvalues and Eigenvectors`. The LLM must determine whether the relationship is actually supported by the source.

### 9.4 Context-Dependent Commas

Commas are also not blindly interpreted as subtopic separators.

```text
Thermal, Optical, Chemical, Electronic and Mechanical
```

could represent a list of properties belonging to another topic. The system therefore uses contextual information rather than treating every comma-separated value as an independent topic.

### 9.5 Mixed Structures

A single unit may contain multiple structural styles:

```text
Language development: Subject-Verb Agreement, Tenses, Conjunctions;
Vocabulary development: Root words, Prefixes and Suffixes;
Nanoparticles and its uniqueness;
Classification of nanoparticles.
```

The LLM must be able to produce:

```text
Topic: Language development
Subtopic: Subject-Verb Agreement
Subtopic: Tenses
Subtopic: Conjunctions

Topic: Vocabulary development
Subtopic: Root words
Subtopic: Prefixes and Suffixes

Topic: Nanoparticles and its uniqueness

Topic: Classification of nanoparticles
```

This mixed-structure requirement is one of the main reasons a purely rule-based approach was insufficient.

---

## 10. Exact-Source Extraction

The current prompt also imposes a strict source-grounding requirement. The model is instructed not to:

- invent topics
- paraphrase topics
- summarize topics
- introduce outside knowledge
- rename syllabus concepts
- correct source terminology unnecessarily
- discard meaningful syllabus items

The goal is to preserve the syllabus wording while only determining its structural role.

For example:

```text
Input:
Writing: Describing an object, the process of an event/experiment
and others, Paragraph Writing
```

should become:

```text
Topic: Writing
Subtopic: Describing an object
Subtopic: the process of an event/experiment and others
Subtopic: Paragraph Writing
```

rather than collapsing the entire sentence into a single topic.

---

## 11. Plain-Text Output Format

The current LLM interface uses a simple text format:

```text
Topic: ...
Subtopic: ...
Subtopic: ...
```

instead of requiring the model to generate JSON.

This design decision is based on the earlier experimentation with structured extraction models — low-parameter extraction models showed difficulty consistently generating valid structured JSON.

Therefore, the current system separates:

1. **Semantic interpretation** – performed by the LLM
2. **Deterministic parsing** – performed by Python

The model only needs to produce `Topic:` / `Subtopic:` lines. Python then converts those lines into structured records. This reduces the amount of formatting responsibility placed on the LLM.

---

## 12. LLM Response Parsing

`Topicextractor2.py` contains a deterministic parser:

```python
parse_plain_text_response()
```

The parser identifies `Topic:` / `Subtopic:` lines and converts them into `(topic, subtopic)` pairs.

For example:

```text
Topic: Language development
Subtopic: Subject-Verb Agreement
Subtopic: Tenses
```

becomes conceptually:

```text
("Language development", "Subject-Verb Agreement")
("Language development", "Tenses")
```

This structured representation is then used by the main pipeline.

---

## 13. Source-Grounding Validation

An additional validation layer was added to prevent hallucinated content from silently entering the final dataset.

The function:

```python
validate_against_source()
```

checks whether extracted topics and subtopics can be traced back to the original unit text.

```text
LLM output
    |
    v
Parse Topic/Subtopic lines
    |
    v
Normalize extracted text
    |
    v
Compare against source unit
    |
    +---- Valid ----> Accept
    |
    +---- Invalid --> Retry
```

If an extracted item cannot be sufficiently matched against the source, the result is rejected. For example, the system can detect and reject an invented topic rather than silently adding it to the Excel output.

---

## 14. Retry Mechanism

The current implementation allows the LLM extraction to be retried when:

- no valid `Topic:` lines are produced
- source-grounding validation fails

The current configuration uses:

```python
LLM_MAX_RETRIES = 1
```

The system can attempt the extraction again before falling back to deterministic processing.

---

## 15. Deterministic Fallback

The LLM is the primary extraction mechanism, but the pipeline contains a fallback mechanism.

If LLM extraction fails after the configured attempts, `split_topics_fallback()` is used.

The fallback is intentionally deterministic and does not attempt to recreate full semantic hierarchy. Its purpose is to ensure that a failed LLM call does not completely stop the processing pipeline.

```text
LLM extraction
      |
      v
   Success?
   /      \
 Yes       No
 |          |
 v          v
Use LLM   Fallback
result    extraction
```

This also allows the complete syllabus processing run to continue even when an individual LLM request fails.

---

## 16. Excel Generation

The final structured records are written to `syllabus_topics.xlsx`.

The output contains fields including:

```text
id
subject_code
subject_name
module_no
module_title
topic
sub_topic
```

An example record is conceptually:

```text
subject_code: UEN2176
subject_name: TECHNICAL ENGLISH
module_no: I
module_title: ...
topic: Language development
sub_topic: Subject-Verb Agreement
```

This structured dataset forms the input for subsequent syllabus-to-textbook mapping stages.

---

## 17. Model Evaluation

After developing the LLM-based extraction approach, multiple models were evaluated using the same syllabus extraction task.

The evaluation included models such as:

- Mistral
- Gemma 3
- Gemma 3 12B
- Other models explored during development

The detailed evaluation results, observations, strengths, limitations, and model-specific findings are documented separately in `model_evaluation.md`.

The current extraction implementation uses:

```text
gemma3:12b
```

The model was selected based on the observed extraction quality during the evaluation stage.

---

## 18. Important Engineering Decisions

### 18.1 Do not rely entirely on regex for semantic hierarchy

Regular expressions are useful for identifying structural boundaries such as courses and units, but they are not sufficient for determining topic/subtopic relationships.

```text
Regex → structural PDF parsing
LLM   → semantic hierarchy extraction
```

### 18.2 Process one unit at a time

Instead of sending an entire subject to the LLM in one call, the system processes each unit separately:

```text
Subject
   |
   +-- Unit I → LLM
   +-- Unit II → LLM
   +-- Unit III → LLM
   +-- Unit IV → LLM
   +-- Unit V → LLM
```

This provides a more focused extraction context.

### 18.3 Separate semantic extraction from structured parsing

The LLM determines *what is a topic*, *what is a subtopic*, and *what belongs under what*. Python determines how the response should be converted into dataset rows.

This separation reduces dependence on perfectly formatted LLM-generated JSON.

### 18.4 Validate generated information against the source

LLM output is not automatically trusted. Extracted items are checked against the original unit text before being accepted. This provides an additional protection against hallucinated syllabus content.

---

## 19. Current Architecture

```text
                    UNIVERSITY SYLLABUS PDF
                              |
                              v
                    ┌───────────────────┐
                    │ pdf_extractor.py  │
                    │                   │
                    │ PDF text          │
                    │ Course detection  │
                    │ Unit detection    │
                    └─────────┬─────────┘
                              |
                              v
                     Course + Unit Body
                              |
                              v
                    ┌───────────────────┐
                    │ Topicextractor2   │
                    │                   │
                    │ Prompt-based      │
                    │ LLM extraction    │
                    └─────────┬─────────┘
                              |
                              v
                    Topic / Subtopic text
                              |
                              v
                    ┌───────────────────┐
                    │ Deterministic     │
                    │ Response Parser   │
                    └─────────┬─────────┘
                              |
                              v
                    ┌───────────────────┐
                    │ Source Grounding  │
                    │ Validation        │
                    └─────────┬─────────┘
                              |
                     +--------+--------+
                     |                 |
                   Valid             Invalid
                     |                 |
                     v                 v
                  Accept             Retry
                                       |
                                  If failure
                                       |
                                       v
                                  Fallback
                                       |
                     +-----------------+
                     |
                     v
              Structured Topic Records
                     |
                     v
              syllabus_topics.xlsx
```

---

## 20. Development Timeline

### Stage 1 – Rule-Based Extraction

A deterministic approach was initially implemented to extract syllabus topics.

**Result:** The approach exposed the highly irregular structure of real syllabus documents and did not provide reliable topic/subtopic hierarchy extraction.

### Stage 2 – NuExtract

A specialized information-extraction model was evaluated as an alternative.

**Result:** The model did not reliably produce the required structured JSON output and was not sufficiently reliable for the semantic hierarchy required by the task.

### Stage 3 – General-Purpose LLM Evaluation

The project shifted toward instruction-following LLMs because the extraction task required contextual and semantic interpretation. Multiple models were evaluated.

**Result:** LLMs demonstrated stronger suitability for interpreting topic/subtopic relationships.

### Stage 4 – Current LLM Pipeline

The extraction process was redesigned around unit-wise LLM calls.

The current system combines:

- deterministic PDF parsing
- unit-wise processing
- prompt-based semantic extraction
- plain-text structured output
- deterministic response parsing
- source-grounding validation
- retry handling
- deterministic fallback
- Excel generation

This is the current approach.

---

## 21. Current Status

The project has moved from a purely rule-based extraction system to an LLM-assisted semantic extraction pipeline.

The current system successfully separates the problem into two stages:

```text
Structural extraction
        +
Semantic hierarchy extraction
```

The structural stage uses deterministic Python processing to identify courses and units. The semantic stage uses an LLM to identify topic/subtopic relationships within each unit.

The current implementation is therefore:

> **A unit-wise LLM-based syllabus topic and subtopic extraction pipeline with source-grounding validation and deterministic fallback.**

The current model under evaluation/usage is:

```text
Gemma 3 12B
```

Detailed model comparisons are maintained separately in `model_evaluation.md`.

---

## 22. Current Limitations and Areas for Further Improvement

Although the current approach is substantially more flexible than the initial rule-based approach, syllabus documents can still contain highly irregular formatting and ambiguous relationships.

Potential future improvements include:

- stronger structured-output constraints
- improved source-grounding validation
- more comprehensive hierarchy validation
- improved handling of malformed PDF text
- evaluation across a larger variety of university syllabus formats
- more systematic automated evaluation of topic/subtopic correctness
- reducing unnecessary topic fragmentation
- improving handling of ambiguous punctuation and formatting artifacts

The current development therefore focuses on improving extraction reliability while maintaining the requirement that the model must remain grounded in the original syllabus text.
