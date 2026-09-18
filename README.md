# Syllabus → Textbook Page Mapper

An end-to-end automated pipeline that extracts structured academic courses, units, topics, and subtopics from university syllabus PDFs, analyzes reference textbook PDFs to extract hierarchical headings and page ranges, and lays the foundation for mapping syllabus topics directly to textbook pages.

> [!NOTE]
> The experimental `VisionModels/` directory is an isolated test module and is excluded from this core pipeline documentation.

---

## Architecture Overview

The system consists of two primary operational pipelines:

```
                          ┌─────────────────────────────────────────────────────────┐
                          │               Syllabus Extraction Pipeline              │
                          └─────────────────────────────────────────────────────────┘
                                                       │
                                      Syllabus PDF (e.g. SSN_BE_CSE.pdf)
                                                       │
                                                       ▼
                                            [ pdf_extractor.py ]
                                  • Regex course header detection (L T P E C)
                                  • Course block extraction & segmentation
                                  • Unit isolation & noise filtering
                                                       │
                                                       ▼
                                           [ Topicextractor2.py ]
                                  • Local LLM via Ollama (e.g. deepseek-r1:14b)
                                  • Strict Topic / Subtopic prompt formatting
                                  • Source-grounding anti-hallucination validation
                                  • Deterministic regex fallback if LLM fails
                                                       │
                                                       ▼
                                              [ main.py ]
                                  • Generates syllabus_topics.xlsx
                                  • Logs raw responses to model_outputs/

─────────────────────────────────────────────────────────────────────────────────────────

                          ┌─────────────────────────────────────────────────────────┐
                          │            Textbook Batch Hierarchy Pipeline            │
                          └─────────────────────────────────────────────────────────┘
                                                       │
                                        Textbook PDFs (input_books/)
                                                       │
                                                       ▼
                                    [ textbook_extractor/batch_pdf_pipeline.py ]
                                  • Scanned PDF detection heuristic (skip image-only)
                                  • DocLayout-YOLO (DocStructBench) title detection
                                  • PyMuPDF text & font typography extraction
                                  • Unsupervised font-size hierarchy clustering
                                  • Section page-range computation
                                                       │
                                                       ▼
                                              [ output_results/ ]
                                  • Formatted Excel outlines (<book>.xlsx)
                                  • Per-book JSON metadata (<book>_data.json)
                                  • Central atomic state tracker (processing_status.json)
```

---

## Repository Structure

```
Intern-syllabus-mapper/
├── main.py                             # Syllabus extraction orchestrator & Excel exporter
├── pdf_extractor.py                    # Syllabus PDF text parser, course & unit splitter
├── Topicextractor2.py                 # LLM topic extraction, hallucination check & fallback
├── Model_evaluation.md                # Benchmarking report of LLMs across syllabus styles
├── requirements.txt                   # Project Python dependencies
├── syllabus_topics.xlsx               # Generated structured syllabus dataset
├── input_books/                       # Input folder containing reference textbook PDFs
├── textbook_extractor/
│   ├── __init__.py
│   └── batch_pdf_pipeline.py          # Batch textbook layout & hierarchy extraction engine
├── model_outputs/                     # Raw LLM inference logs grouped by model name
│   └── deepseek-r1_14b/               # E.g., raw prompts and outputs per course code (.txt)
└── output_results/                    # Output folder for textbook batch extraction
    ├── processing_status.json         # Central resume & status ledger (JSON)
    ├── *.xlsx                         # Formatted hierarchical outlines per textbook
    └── *_data.json                    # Metadata and extracted heading nodes per textbook
```

---

## Core Components

### 1. Syllabus Extraction Pipeline

* **`pdf_extractor.py`**:
  * Extracts normalized text using `pdfplumber`.
  * Identifies course headers using regex patterns matching course codes and university credit schemas (`L T P E C`).
  * Splits syllabus documents into discrete course blocks.
  * Extracts units/modules (Roman or decimal numbers), titles, and bodies while stripping non-content sections (`COURSE OUTCOMES`, `TEXT BOOKS`, `REFERENCES`, `TOTAL PERIODS`).
* **`Topicextractor2.py`**:
  * Interfaces with local LLMs via Ollama's REST API (`/api/generate`).
  * Enforces plain-text `Topic:` / `Subtopic:` formatting without conversational filler.
  * **Source-Grounding Validation (`validate_against_source`)**: Verifies every extracted topic and subtopic against the original source text using sliding n-gram matching to prevent hallucinated concepts.
  * **Deterministic Fallback (`split_topics_fallback`)**: Splits on punctuation boundaries (en-dashes, hyphens) if the LLM encounters a timeout, server error, or validation failure.
* **`main.py`**:
  * Orchestrates the extraction of courses and units from the syllabus PDF.
  * Processes each unit through LLM extraction with automatic fallback.
  * Logs full raw LLM responses to `model_outputs/<safe_model_name>/<subject_code>.txt`.
  * Exports records to `syllabus_topics.xlsx` with columns:
    * `id` (`{PREFIX}_M{module}_T{index}`)
    * `subject_code`
    * `subject_name`
    * `module_no`
    * `module_title`
    * `topic`
    * `sub_topic`

### 2. Textbook Hierarchy Extraction Pipeline

* **`textbook_extractor/batch_pdf_pipeline.py`**:
  * **Scanned PDF Detection**: Inspects sample pages for character density and image area coverage (`SCANNED_MIN_CHARS_PER_PAGE = 30`, `SCANNED_MIN_IMAGE_COVERAGE = 0.85`). Automatically flags and skips image-only PDFs that lack an extractable text layer.
  * **Layout Detection**: Utilizes `DocLayout-YOLO` (`juliozhao/DocLayout-YOLO-DocStructBench`) to identify bounding boxes classified as `"title"` regions.
  * **Typography Extraction**: Employs `PyMuPDF` (`fitz`) to extract text, exact font families, font sizes, and formatting flags within detected bounding boxes.
  * **Hierarchy Clustering**: Dynamically clusters font sizes into structural levels (e.g., Level 1: Chapter titles, Level 2: Main sections, Level 3: Subsections) and filters out running headers/footers.
  * **Page Range Computation**: Calculates page spans for each heading based on document flow.
  * **Persistent Status Tracking**: Maintains `output_results/processing_status.json` with atomic writes, recording status (`Parsed`, `Scanned book (skip it)`, `Error: ...`), page counts, and paths, allowing batch runs to resume seamlessly.
  * **Dual Outputs**: Produces a stylistically formatted Excel spreadsheet (`.xlsx`) with hierarchical indentation and a machine-readable JSON file (`_data.json`) per textbook.

### 3. Model Evaluation & Benchmarks

* **`Model_evaluation.md`**:
  * Comprehensive benchmark comparing local LLMs (`gemma3:12b`, `mistral`, `gemma3:4b`, `phi3:mini`) across diverse syllabus formatting styles:
    * **UC1**: Labeled category lists with semicolons.
    * **UC2**: Em-dash chained paragraphs with ambiguous nesting.
    * **UC3**: Short, dense single-sentence units.
  * Evaluates hallucination risk, repetition loops, and formatting consistency.

---

## Installation & Setup

### 1. Prerequisites

* **Python**: Python 3.10 or higher
* **Hardware Acceleration**: NVIDIA CUDA, Apple Silicon (Metal/MPS), or CPU
* **Ollama**: Required for syllabus topic extraction ([Download Ollama](https://ollama.com/))

### 2. Clone Repository & Setup Virtual Environment

```bash
git clone <repository_url>
cd Intern-syllabus-mapper

python3 -m venv venv
source venv/bin/activate    # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

*Note: On Apple Silicon or Linux, PyTorch and DocLayout-YOLO will automatically utilize available acceleration (`mps` or `cuda`).*

### 4. Setup Ollama (for Syllabus Extraction)

Pull the desired model into Ollama and ensure the Ollama daemon is running:

```bash
ollama serve

# In another terminal, pull the model configured in Topicextractor2.py:
ollama pull deepseek-r1:14b
# or models evaluated in Model_evaluation.md:
# ollama pull gemma3:12b
# ollama pull mistral
```

---

## Usage Guide

### Running Syllabus Extraction

1. Verify configuration in `main.py`:
   ```python
   PDF_PATH = "SSN_BE_CSE.pdf"
   START_PAGE = 29
   END_PAGE = None
   OUTPUT_EXCEL = "syllabus_topics.xlsx"
   ```
2. Verify model selection in `Topicextractor2.py`:
   ```python
   OLLAMA_MODEL = "deepseek-r1:14b"  # or gemma3:12b / mistral
   ```
3. Run the extraction script:
   ```bash
   python3 main.py
   ```
4. Output files generated:
   * Structured spreadsheet: `syllabus_topics.xlsx`
   * Subject log files: `model_outputs/<model_name>/<subject_code>.txt`

---

### Running Batch Textbook Extraction

1. Place your textbook PDFs into the `input_books/` folder.
2. Run the batch pipeline:
   ```bash
   python3 textbook_extractor/batch_pdf_pipeline.py -i input_books -o output_results
   ```

#### Command-Line Options

| Flag | Long Flag | Default | Description |
|---|---|---|---|
| `-i` | `--input-dir` | `./input_books` | Directory containing PDF textbooks |
| `-o` | `--output-dir` | `./output_results` | Directory to save `.xlsx` and `.json` files |
| `-s` | `--status-file` | `processing_status.json` | Status ledger tracking processed files |
| `-m` | `--max-pages` | `None` | Max pages to process per book (for rapid testing) |
| `-f` | `--force` | `False` | Force re-processing even if already marked `Parsed` |
| | `--conf` | `0.3` | Confidence threshold for DocLayout-YOLO |
| | `--dpi` | `150` | Rendering DPI for page image inference |

#### Pipeline Outputs

* **Status Ledger (`output_results/processing_status.json`)**:
  ```json
  {
    "Software_Engineering.pdf": {
      "status": "Parsed",
      "timestamp": "2026-09-07T10:41:41",
      "excel_file": "Software_Engineering.xlsx",
      "total_pages": 930,
      "processed_pages": 930,
      "headings_count": 1413
    },
    "Scanned_Math_Book.pdf": {
      "status": "Scanned book (skip it)",
      "reason": "Scanned/image-only PDF detected (0 chars/page, 83% image coverage)."
    }
  }
  ```
* **Hierarchical Excel (`<book_name>.xlsx`)**: Formatted sheet with columns `Heading Level`, `Heading Text`, `Page Number`, `Font Size`, and `Page Range`.
* **JSON Metadata (`<book_name>_data.json`)**: Structured document hierarchy tree for downstream mapping.

---

## Status & Roadmap

- [x] **Syllabus PDF Parsing**: Regex course header and unit block segmentation (`pdf_extractor.py`).
- [x] **LLM Topic Extraction**: Few-shot plain-text extraction with Ollama and hallucination validation (`Topicextractor2.py`).
- [x] **Batch Textbook Parsing**: Layout analysis via DocLayout-YOLO + PyMuPDF font clustering (`batch_pdf_pipeline.py`).
- [x] **Scanned PDF Filtering**: Automatic heuristic detection for image-only books.
- [ ] **Topic-to-Page Semantic Alignment**: Embedding-based cross-matching between syllabus topic entities and textbook heading hierarchy.
- [ ] **Interactive Visualizer**: UI to review and inspect mapped syllabus-textbook page associations.
