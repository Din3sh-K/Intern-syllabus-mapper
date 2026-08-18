# Model Performance Analysis — Syllabus Topic/Subtopic Extraction

**Task:** Given a raw syllabus-unit paragraph as input, extract a clean `Topic: / Subtopic:` hierarchy.
**Models compared:** `gemma3:12b`, `gemma3:4b`, `mistral`, `phi3:mini`
**Data:** 20 syllabus units each (4 subjects × 5 units), sourced from `all_model_outputs.txt`

This doc groups the input formats into three "use cases" based on how the source text is structured, since that is what actually determines each model's behavior — not the subject matter.

---

## Use Case Definitions

| Use Case | Description | Example Subject |
|---|---|---|
| **UC1 – Labeled category list** | Input uses explicit `Category: item1, item2, item3;` structure with semicolons separating clear sections (Language development, Vocabulary development, Reading, Writing…) | UEN2176 (Technical English) |
| **UC2 – Em-dash (–) chained paragraph** | Long paragraph where topics/subtopics are only separated by en-dashes/hyphens, no explicit labels, ambiguous nesting | UCY2176 (Chemistry), UPH2176 (Physics) |
| **UC3 – Short dense single-sentence unit** | Very short input (1–2 sentences), still em-dash chained, but so compact that topic/subtopic boundaries are hard to infer | UMA2176 (Matrices & Calculus) |

---

## Scorecard

| Model | UC1 (labeled lists) | UC2 (em-dash paragraphs) | UC3 (short dense units) | Repetition/Loop Risk | Hallucination Risk |
|---|---|---|---|---|---|
| **gemma3:12b** | Excellent | Very good | Good, but **one total failure** (see below) | None observed | None observed |
| **mistral** | Excellent | Very good | Good | None observed (aside from a pipeline-level duplicate file re-run, not model's fault) | None observed |
| **gemma3:4b** | Good | Weak — frequently splits mid-sentence, producing fragment subtopics | Decent | None observed | None observed |
| **phi3:mini** | Good on short inputs | **Fails badly** on medium/long inputs | Good on short inputs | **Severe** — repeats same subtopic blocks verbatim until output is truncated mid-word | **Severe** — injects entire unrelated subject content (English syllabus text inside a Chemistry unit; invented "Vector direction/magnitude" lists; invented generic subject catalog) |

**Bottom line:** `gemma3:12b` and `mistral` are essentially tied for best and are safe to use in production. `gemma3:4b` is usable but sloppy on em-dash-heavy text. `phi3:mini` is not reliable for anything beyond short inputs — it hallucinates and loops on longer real-world syllabus text.

---

## 1. gemma3:12b

### Where it performs well
On UC1 (labeled lists) and most of UC2, gemma3:12b is the cleanest of all four models — it correctly separates compound phrases like `"Point, line (Edge and Screw dislocations – Burger vectors) Surface (stacking faults) and Volume defects"` into four distinct, correctly-scoped subtopics:

```
INPUT (UPH2176 Unit I, excerpt):
...Crystal Imperfections – Point, line (Edge and Screw dislocations – Burger vectors)
Surface (stacking faults) and Volume defects.

OUTPUT:
Topic: Crystal Imperfections
Subtopic: Point
Subtopic: line (Edge and Screw dislocations – Burger vectors)
Subtopic: Surface (stacking faults)
Subtopic: Volume defects
```
This is the "textbook correct" output — no other model in this dataset (except mistral, closely) achieves this level of decomposition consistently.

### Where it fails — CONFIRMED example
**Subject:** UMA2176 – Matrices and Calculus, **Unit III**

```
INPUT
----------------------------------------------------------------------
Curvature, radius of curvature – Cartesian and parametric co-ordinates – Centre of curvature – Circle of
curvature in Cartesian form, Evolutes, Envelopes (including two parameter family), Evolute as envelope
of normal.

RAW MODEL OUTPUT (gemma3:12b)
----------------------------------------------------------------------
Topic: Curvature, radius of curvature – Cartesian and parametric co-ordinates – Centre of curvature – Circle of
curvature in Cartesian form, Evolutes, Envelopes (including two parameter family), Evolute as envelope
of normal.
```

This is a **total extraction failure**: the model returned the *entire raw input verbatim as a single `Topic:` line*, with **zero `Subtopic:` lines** and **zero segmentation** at all — it did not even split off "Curvature" as the topic. Every other model (gemma3:4b, mistral, phi3:mini) correctly parsed this exact same input into a proper Topic + 6 Subtopics structure. This is the clearest, most isolated "model just gave up" case in the entire dataset for gemma3:12b — it happens on a short, single-paragraph, math-heavy unit, not a long one, which is the opposite of where you'd expect a large model to struggle.

**Compare to mistral on the identical input:**
```
Topic: Curvature
Subtopic: radius of curvature – Cartesian and parametric co-ordinates
Subtopic: Centre of curvature
Subtopic: Circle of curvature in Cartesian form
Subtopic: Evolutes
Subtopic: Envelopes (including two parameter family)
Subtopic: Evolute as envelope of normal.
```

**Takeaway:** gemma3:12b is otherwise the strongest model on this dataset, but it is not 100% reliable — expect roughly a 1-in-20 chance (1/20 units in this sample) of a complete non-parse on a given unit, with no partial credit and no warning signal in the output itself (it looks like valid output, just wrong).

---

## 2. mistral

### Where it performs well
Mistral matches gemma3:12b in quality across almost every unit and never produced a total-failure case like the one above. On UC2 em-dash paragraphs it segments cleanly:

```
INPUT (UPH2176 Unit III, excerpt):
Ultrasonics: Pro- duction of ultrasonics by Magnetostriction and piezoelectric methods – acoustic grating
- Non-Destructive Testing – pulse echo system through transmission and reflection modes – A, B and C – scan displays.

OUTPUT:
Topic: Ultrasonics
Subtopic: Production of ultrasonics by Magnetostriction and piezoelectric methods
Subtopic: acoustic grating
Subtopic: Non-Destructive Testing
Subtopic: pulse echo system through transmission and reflection modes
Subtopic: A, B and C – scan displays.
```
It even auto-corrects the OCR artifact `"Pro- duction"` → `"Production"`, which gemma3:12b did not attempt.

### Minor issues found
1. **Redundant self-referential subtopics** (UMA2176 Unit II): the model sometimes repeats the topic text as its own subtopic instead of finding a real child concept:
```
Topic: Sequences – Definition and examples
Subtopic: Definition and examples          <-- just restates part of the topic, not a real subtopic
```
This happened for all 9 items in that unit — not a crash, but a low-value/degenerate hierarchy.

2. **Pipeline-level duplication** (not a model error, a data artifact worth flagging): the `UEN2176` file for mistral contains **Units I–III twice** in the raw output log — the exact same input/output pair appears twice in sequence. This looks like a re-run or logging bug in the harness rather than the model hallucinating, since the two copies are byte-identical.

**Takeaway:** mistral is the most *consistently* reliable model — no catastrophic failures — but has a tendency toward "lazy" subtopic duplication on very short, tightly-packed math units.

---

## 3. gemma3:4b

### Where it performs well
On UC1 (clean labeled-list English syllabus), gemma3:4b matches the 12b model almost line-for-line:
```
Topic: Language development
Subtopic: Subject-Verb Agreement
Subtopic: Tenses (simple)
Subtopic: Conjunctions
Subtopic: Numerical adjective
```

### Where it fails — CONFIRMED examples

**(a) Sentence-fragment subtopics** — UPH2176 Unit II (Properties of matter), a dense em-dash paragraph, breaks apart mid-phrase instead of at logical concept boundaries:
```
INPUT (excerpt):
...stress -strain diagram– Poisson's ratio – Factors affecting elasticity – Torsional stress & deformations –
Twisting couple – Torsion pendulum...

OUTPUT (gemma3:4b):
Subtopic: Elasticity – Hooke's law – Relationship between three moduli of elasticity – stress
Subtopic: -strain diagram– Poisson's ratio – Factors affecting elasticity – Torsional stress & deformations –
Subtopic: Twisting couple – Torsion pendulum - theory and experiment – bending of beams-bending moment –
Subtopic: cantilever: theory and experiment – uniform and non-uniform bending: theory and experiment – I-shaped
Subtopic: girders.
```
This is a clear formatting failure: subtopics are cut at arbitrary line-wrap points, not concept boundaries. `"-strain diagram– Poisson's ratio..."` starting with a stray hyphen, and `"girders."` as its own orphaned one-word subtopic, are not usable outputs — a human reading this would have to manually re-merge these lines.

**(b) Hierarchy/structure collapse** — UEN2176 Unit III: instead of treating Reading/Writing/Listening/Speaking as sibling `Topic:` entries (as it correctly did in Units I, II, IV, V of the *same file*), it demotes all of them into `Subtopic:` children of "Vocabulary development":
```
Topic: Vocabulary development
Subtopic: Compound words
Subtopic: Formal and informal vocabulary
Subtopic: Reading: Reading reviews, advertisements, SOPs for higher studies      <-- should be its own Topic
Subtopic: Writing: Writing instruction and recommendations...                    <-- should be its own Topic
Subtopic: Listening: Listening to longer technical talks and discussion          <-- should be its own Topic
Subtopic: Speaking: Demonstrating working mechanisms                             <-- should be its own Topic
```
Inconsistent — the model gets the identical pattern right 4 out of 5 times in that same file, then collapses it once.

**(c) Run-on merged subtopic** — UMA2176 Unit IV:
```
OUTPUT:
Topic: Partial derivatives – Total derivative – Differentiation of implicit functions – Jacobian and its properties
Subtopic: Taylor's series for functions of two variables – Maxima and minima of functions of two variables –
Lagrange's method of undetermined multipliers.
```
Four distinct subtopics (Total derivative, Differentiation of implicit functions, Jacobian, Taylor's series, Maxima/minima, Lagrange's method) got merged into one bloated Topic line and one run-on Subtopic line, instead of being split out individually like every other model did on this exact input.

**Takeaway:** gemma3:4b never crashes or hallucinates, but its segmentation is noticeably less reliable than the 12b or mistral on em-dash-heavy paragraphs — it tends to break at the wrong character (a hyphen mid-word) rather than at a real concept boundary, and its topic/subtopic hierarchy assignment is inconsistent within the same document.

---

## 4. phi3:mini — most failure-prone model

phi3:mini does fine on short inputs (e.g. UMA2176 Units III–V, UPH2176 Unit III) but breaks down badly as soon as the input gets moderately long or dense. Three distinct, confirmed failure modes:

### (a) Cross-document hallucination / content bleed
**Subject:** UCY2176 (Chemistry), **Unit I** — input is entirely about atoms, molecules, and nanoparticles. The model correctly extracts that content, but then, unprompted, appends this to the *same output*:
```
Topic: Language development
Subtopic: Subject-Verb Agreement
Subtopic: Tenses (simple)
Subtopic: Conjunctions

Topic: Vocabulary development
Subtopic: Root words – Prefixes and Suffixes
Subtopic: Standard abbreviations
```
"Language development" and "Subject-Verb Agreement" never appear anywhere in the Chemistry input — they are the exact topic labels from the *English* syllabus (UEN2176) elsewhere in the corpus. This is content bleeding in from a different document, not the model's own invention, but it's still a hallucination relative to the given input — nothing in the prompt should have produced this.

### (b) Full generic-subject-catalog hallucination
**Subject:** UCY2176, **Unit III** (Corrosion) — input is entirely about corrosion, coatings, and electroplating. The model correctly extracts a Corrosion topic block, then invents an entire, completely unrelated table of contents for a general-knowledge encyclopedia:
```
Topic: Mathematics
Subtopic: Algebra
Subtopic: Geometry
Subtopic: Calculus

Topic: Physics
Subtopic: Mechanics
Subtopic: Electromagnetism
Subtopic: Thermodynamics

Topic: Biology
Subtopic: Cell Biology
...
Topic: History / Literature / Art / Music / Psychology / Sociology / Economics /
Political Science / Geography / Health and Medicine / Law / Philosophy / Religion /
Languages / Science and Technology / Education / Business
```
None of these 20 topics (Math, Physics, Biology, History, Literature, Art, Music, Psychology, Sociology, Economics, Political Science, Geography, Health/Medicine, Law, Philosophy, Religion, Languages, Science/Tech, Education, Business) appear anywhere in the Corrosion input. This is a pure hallucination — the model appears to fall back to a memorized "list of academic subjects" template when it loses track of the actual input.

### (c) Runaway repetition loop (never terminates cleanly — output gets cut off mid-word)
**Subject:** UCY2176, **Unit V** (Polymers) — the model correctly extracts the polymer topics once, then re-emits the *identical* topic list over and over:
```
Topic: Epoxy resin
Topic: Polyurethans
Topic: Nylon 6:6
Topic: Polycarbonate
Topic: PS
Topic: PVC and PET

Topic: Polymers and Polymerization: definition, classification
...
[same 6-item block repeats 6+ times]
...
Topic: mechanism of addition polymerization (cationic, anionic, free radical and coord   <- cut off mid-word
```
Similarly, **UPH2176 Unit IV** (Black body radiation / matter waves) degenerates into a 200+ line loop of invented vector-algebra subtopics that don't exist in the input at all:
```
Subtopic: Vector addition
Subtopic: Vector subtraction
Subtopic: Vector multiplication
Subtopic: Vector division
Subtopic: Vector projection
Subtopic: Vector resolution
Subtopic: Vector components
Subtopic: Vector magnitude
Subtopic: Vector direction
Subtopic: Vector components   <- repeats ~15 more times identically, then output ends abruptly
```
And **UEN2176 Unit V** (Job Interviews) invents plausible-sounding but non-existent subtopics ("advanced techniques", "common mistakes to avoid", "body language and non-verbal cues", "dealing with difficult questions"...) that are **not in the source syllabus at all**, then loops through the same fabricated list twice before truncating mid-sentence: `"Topic: Speaking / Subtopic: Job Interviews (face"`.

### Where it does work
On short, self-contained inputs it is fine and comparable to the other models:
```
INPUT (UMA2176 Unit IV, full):
Partial derivatives – Total derivative – Differentiation of implicit functions – Jacobian and its properties
– Taylor's series for functions of two variables – Maxima and minima of functions of two variables –
Lagrange's method of undetermined multipliers.

OUTPUT (phi3:mini) — clean, correct, no hallucination:
Topic: Partial derivatives
Subtopic: Total derivative
Subtopic: Differentiation of implicit functions
Subtopic: Jacobian and its properties
Subtopic: Taylor's series for functions of two variables
Subtopic: Maxima and minima of functions of two variables
Subtopic: Lagrange's method of undetermined multipliers.
```

**Takeaway:** phi3:mini is not safe for any input longer than roughly 3–4 lines. It has three real failure modes — content bleed from other documents, full hallucination of unrelated academic subjects, and non-terminating repetition loops that silently truncate output. None of the other three models exhibit any of these three failure types anywhere in this dataset.

---

## Recommendation


|---|---|
| Best overall accuracy, willing to spot-check for rare total failures | **gemma3:12b** |
| Most *consistent* / production-safe (no crashes, no hallucination, minor redundancy only) | **mistral** |
| Smaller/faster model, acceptable on clean labeled inputs, avoid for long em-dash paragraphs | **gemma3:4b** (with post-processing to re-merge fragment subtopics) |
| Do not use for real syllabus parsing beyond trivially short units | **phi3:mini** — needs a max-token cap / repetition penalty / dedup post-filter at minimum, and ideally should be dropped from the pipeline given mistral and gemma3:12b are already available and don't exhibit these failure modes |

