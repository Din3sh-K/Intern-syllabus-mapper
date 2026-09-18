#!/usr/bin/env python3
"""
=============================================================================
BATCH PDF HEADING EXTRACTION & HIERARCHY PIPELINE (Textbook Extractor)
=============================================================================

Pipeline Overview:
  Folder of local PDF books
        ↓
  Scanned PDF check (character density & image coverage heuristic)
        ↓
  DocLayout-YOLO (DocStructBench) — detected "title" regions
        ↓
  PyMuPDF — extracts text, font name, font size, flags for detected boxes
        ↓
  Font-size hierarchy clustering (Level 1 / Level 2 / Level 3...)
        ↓
  Formatted Excel (.xlsx) per PDF saved to the output folder
        ↓
  Central Key-Value Status Tracker JSON + Per-Book Extraction JSON

Key Features:
  - Local folder selection: Works locally (macOS, Linux, Windows) or in Google Colab.
  - Automatically identifies scanned / image-only books and skips them.
  - Key-value paired Status JSON file:
      * Maps book name -> status object ("Parsed", "Scanned book (skip it)", "Error: ...")
      * Ensures the same book will not be parsed again on subsequent runs.
      * Saves immediately after each book so progress is never lost.
  - Per-book extraction JSON saved in the output directory (<book_name>_data.json).
  - Output Excel file with hierarchical font formatting, page ranges, and styling.
=============================================================================
"""

import os
import sys
import time
import json
import shutil
import argparse
import traceback
from datetime import datetime
from collections import Counter
from io import BytesIO


# =============================================================================
# CONFIGURATION (Defaults - can be modified here or overridden via CLI flags)
# =============================================================================

# Folder containing the PDF books to process
DEFAULT_INPUT_FOLDER = "./input_books"

# Folder where .xlsx and .json outputs will be saved
DEFAULT_OUTPUT_FOLDER = "./output_results"

# Filename of the key-value tracking JSON (saved inside output folder)
STATUS_TRACKER_FILENAME = "processing_status.json"

# If True: skips any book already marked as "Parsed" in the status JSON
SKIP_ALREADY_DONE = True

# If True: skips books previously flagged as "Scanned book (skip it)"
SKIP_PREVIOUS_SCANNED = True

# If True: saves an individual metadata JSON for each parsed book (<book_stem>_data.json)
SAVE_PER_BOOK_JSON = True

# -----------------------------------------------------------------------------
# SCANNED-PDF DETECTION PARAMETERS
# -----------------------------------------------------------------------------
SCANNED_CHECK_PAGES = 5
SCANNED_MIN_CHARS_PER_PAGE = 30
SCANNED_MIN_IMAGE_COVERAGE = 0.85

# -----------------------------------------------------------------------------
# MODEL INFERENCE PARAMETERS
# -----------------------------------------------------------------------------
MODEL_REPO = "juliozhao/DocLayout-YOLO-DocStructBench"
MODEL_FILENAME = "doclayout_yolo_docstructbench_imgsz1024.pt"

DPI = 150
IMGSZ = 1024
CONF = 0.3
MAX_PAGES = None  # None = process all pages in the PDF

SOURCE_LABELS = {"title"}
OUTPUT_LABEL = "Section-header"

FONT_SIZE_TOLERANCE = 0.3
RUNNING_HEADER_Y_MAX = 45.0
REPEAT_COUNT_THRESHOLD = 4


# =============================================================================
# DEPENDENCY CHECK
# =============================================================================

def check_dependencies():
    """Verifies all required libraries are installed."""
    missing = []
    for pkg in ["fitz", "torch", "pandas", "openpyxl", "PIL", "doclayout_yolo", "huggingface_hub"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        pkg_names = {
            "fitz": "pymupdf",
            "PIL": "pillow",
            "doclayout_yolo": "doclayout-yolo",
            "huggingface_hub": "huggingface_hub",
            "torch": "torch",
            "pandas": "pandas",
            "openpyxl": "openpyxl"
        }
        install_cmd = "pip install " + " ".join(pkg_names.get(p, p) for p in missing)
        print("=" * 70)
        print("ERROR: Missing required Python packages!")
        print(f"Missing: {', '.join(missing)}")
        print("\nPlease install them using:")
        print(f"  {install_cmd}")
        print("=" * 70)
        sys.exit(1)


# =============================================================================
# STATUS TRACKER HELPERS (KEY-VALUE JSON LEDGER)
# =============================================================================

def load_status_tracker(tracker_path):
    """
    Loads the persistent status tracker JSON.
    Returns a dictionary mapping: filename -> status_metadata_dict
    """
    if os.path.isfile(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Warning] Failed to read status tracker at {tracker_path}: {e}")
            backup_path = f"{tracker_path}.bak.{int(time.time())}"
            shutil.copyfile(tracker_path, backup_path)
            print(f"  Corrupted file backed up to: {backup_path}")
            return {}
    return {}


def save_status_tracker(tracker_path, status_dict):
    """
    Atomically writes the status dictionary to disk using a temporary file
    and atomic rename so file corruption never happens if interrupted.
    """
    os.makedirs(os.path.dirname(os.path.abspath(tracker_path)), exist_ok=True)
    temp_path = f"{tracker_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(status_dict, f, indent=2, ensure_ascii=False)
    os.replace(temp_path, tracker_path)


# =============================================================================
# DEVICE DETECTION & MODEL LOADING
# =============================================================================

def select_device():
    """Detects available hardware acceleration: CUDA, Apple Silicon MPS, or CPU."""
    import torch
    if torch.cuda.is_available():
        device = "cuda"
        print(f"Acceleration: NVIDIA CUDA ({torch.cuda.get_device_name(0)})")
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
        print("Acceleration: Apple Silicon MPS (Metal)")
    else:
        device = "cpu"
        print("Acceleration: CPU (Warning: inference will be slower)")
    return device


def load_model(device):
    """Downloads weights from Hugging Face Hub (cached) and loads DocLayout-YOLO."""
    from doclayout_yolo import YOLOv10
    from huggingface_hub import hf_hub_download

    print("=" * 70)
    print("DocLayout-YOLO Model Initialization")
    print("=" * 70)
    print(f"Downloading/verifying weights from HuggingFace ({MODEL_REPO})...")
    model_path = hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILENAME)
    print(f"Weights ready at: {model_path}")

    print("Loading YOLOv10 model weights...")
    start_t = time.perf_counter()
    model = YOLOv10(model_path)
    print(f"Model loaded in {time.perf_counter() - start_t:.2f}s\n")
    return model


# =============================================================================
# PDF SCANNING & HEURISTICS
# =============================================================================

def find_pdfs(folder):
    """Lists all PDF files in the specified folder (non-recursive, sorted)."""
    if not os.path.isdir(folder):
        return []
    pdfs = []
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith(".pdf") and not name.startswith("._"):
            pdfs.append(os.path.join(folder, name))
    return pdfs


def safe_stem(pdf_path):
    """Returns a filesystem-safe basename without extension."""
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    return stem.strip()


def is_scanned_pdf(
    pdf_path,
    sample_pages=SCANNED_CHECK_PAGES,
    min_chars_per_page=SCANNED_MIN_CHARS_PER_PAGE,
    min_image_coverage=SCANNED_MIN_IMAGE_COVERAGE,
):
    """
    Inspects sampled pages across the PDF for:
      1. Extractable text density (character count).
      2. Dominant full-page image coverage (scanned pages).
    Returns: (is_scanned: bool, avg_chars: float, avg_image_cov: float)
    """
    import fitz
    doc = fitz.open(pdf_path)
    try:
        total_pages = len(doc)
        if total_pages == 0:
            return True, 0.0, 0.0

        n = min(sample_pages, total_pages)
        indices = sorted(set(
            round(i * (total_pages - 1) / max(1, n - 1))
            for i in range(n)
        ))

        char_counts = []
        image_coverages = []

        for i in indices:
            page = doc[i]
            page_dict = page.get_text("dict")
            page_area = page.rect.width * page.rect.height

            text_chars = 0
            image_area = 0.0

            for block in page_dict.get("blocks", []):
                if block.get("type") == 1:
                    bbox = block.get("bbox", [0, 0, 0, 0])
                    w = max(0.0, bbox[2] - bbox[0])
                    h = max(0.0, bbox[3] - bbox[1])
                    image_area += w * h
                else:
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text_chars += len(span.get("text", "").strip())

            char_counts.append(text_chars)
            image_coverages.append(image_area / page_area if page_area > 0 else 0.0)

        avg_chars = sum(char_counts) / len(char_counts)
        avg_image_coverage = sum(image_coverages) / len(image_coverages)
        scanned = (avg_chars < min_chars_per_page) or (avg_image_coverage >= min_image_coverage)
        return scanned, avg_chars, avg_image_coverage
    finally:
        doc.close()


# =============================================================================
# PYMUPDF + DOCLAYOUT-YOLO EXTRACTION
# =============================================================================

def extract_text_spans(page):
    """Extracts raw text spans with font metadata from PyMuPDF."""
    page_dict = page.get_text("dict")
    spans = []

    for block_no, block in enumerate(page_dict.get("blocks", [])):
        if "lines" not in block:
            continue
        for line_no, line in enumerate(block.get("lines", [])):
            for span_no, span in enumerate(line.get("spans", [])):
                text = span.get("text", "")
                if not text.strip():
                    continue
                spans.append({
                    "text": text,
                    "bbox": [round(float(x), 2) for x in span["bbox"]],
                    "font": span.get("font", ""),
                    "size": round(float(span.get("size", 0.0)), 2),
                    "flags": int(span.get("flags", 0)),
                    "color": span.get("color", 0),
                    "block_no": block_no,
                    "line_no": line_no,
                    "span_no": span_no,
                })
    return spans


def spans_inside_bbox(region_bbox, spans, overlap_threshold=0.20):
    """Filters spans that geometrically overlap with a YOLO-detected bounding box."""
    rx1, ry1, rx2, ry2 = region_bbox
    matched = []

    for span in spans:
        sx1, sy1, sx2, sy2 = span["bbox"]
        ix1, iy1 = max(rx1, sx1), max(ry1, sy1)
        ix2, iy2 = min(rx2, sx2), min(ry2, sy2)

        iw = max(0, ix2 - ix1)
        ih = max(0, iy2 - iy1)
        intersection_area = iw * ih

        span_area = max(0, sx2 - sx1) * max(0, sy2 - sy1)
        if span_area <= 0:
            continue

        if (intersection_area / span_area) >= overlap_threshold:
            matched.append(span)

    matched.sort(key=lambda s: (s["block_no"], s["line_no"], s["span_no"]))
    return matched


def run_doclayout_extraction(model, device, pdf_path, max_pages=None):
    """
    Renders pages, runs DocLayout-YOLO inference to detect title regions,
    and correlates them with PyMuPDF text spans.
    """
    import fitz
    import torch
    from PIL import Image

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    effective_max = max_pages if max_pages is not None else MAX_PAGES
    pages_to_process = total_pages if effective_max is None else min(effective_max, total_pages)

    print(f"  Total PDF pages: {total_pages} | Processing: {pages_to_process}")

    pages_data = []
    benchmark_start = time.perf_counter()
    total_yolo_time = total_render_time = total_text_time = 0.0

    for page_index in range(pages_to_process):
        page_number = page_index + 1
        page = doc[page_index]
        page_start = time.perf_counter()

        pdf_width = round(float(page.rect.width), 2)
        pdf_height = round(float(page.rect.height), 2)

        # PyMuPDF text spans
        text_start = time.perf_counter()
        text_spans = extract_text_spans(page)
        text_time = time.perf_counter() - text_start

        # Render page pixmap
        render_start = time.perf_counter()
        pix = page.get_pixmap(dpi=DPI)
        image_width, image_height = pix.width, pix.height
        image = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
        render_time = time.perf_counter() - render_start

        scale_x = pdf_width / image_width if image_width > 0 else 1.0
        scale_y = pdf_height / image_height if image_height > 0 else 1.0

        if device == "cuda":
            torch.cuda.synchronize()

        yolo_start = time.perf_counter()
        results = model.predict(source=image, imgsz=IMGSZ, conf=CONF, device=device, verbose=False)
        if device == "cuda":
            torch.cuda.synchronize()
        yolo_time = time.perf_counter() - yolo_start

        result = results[0]
        section_headers = []

        if result.boxes is not None and len(result.boxes) > 0:
            for i in range(len(result.boxes)):
                box = result.boxes[i]
                class_id = int(box.cls[0])
                source_label = str(model.names[class_id])

                if source_label not in SOURCE_LABELS:
                    continue

                confidence = float(box.conf[0])
                bbox_image = [round(float(c), 2) for c in box.xyxy[0].tolist()]
                x1, y1, x2, y2 = bbox_image
                bbox_pdf = [
                    round(x1 * scale_x, 2),
                    round(y1 * scale_y, 2),
                    round(x2 * scale_x, 2),
                    round(y2 * scale_y, 2),
                ]

                matched_spans = spans_inside_bbox(bbox_pdf, text_spans)
                header_text = " ".join(
                    s["text"].strip() for s in matched_spans if s["text"].strip()
                )

                if not header_text.strip():
                    continue

                section_headers.append({
                    "label": OUTPUT_LABEL,
                    "source_label": source_label,
                    "confidence": round(confidence, 4),
                    "bbox_image": bbox_image,
                    "bbox_pdf": bbox_pdf,
                    "text": header_text,
                    "spans": matched_spans,
                })

        section_headers.sort(key=lambda r: (r["bbox_pdf"][1], r["bbox_pdf"][0]))

        page_time = time.perf_counter() - page_start
        total_yolo_time += yolo_time
        total_render_time += render_time
        total_text_time += text_time

        pages_data.append({
            "pdf_page": page_number,
            "page_width": pdf_width,
            "page_height": pdf_height,
            "section_header_count": len(section_headers),
            "regions": section_headers,
            "timing": {
                "processing_time_sec": round(page_time, 3),
                "render_time_sec": round(render_time, 3),
                "text_extraction_time_sec": round(text_time, 3),
                "yolo_time_sec": round(yolo_time, 3),
            },
        })

        if page_number % 10 == 0 or page_number == pages_to_process:
            print(
                f"    Page {page_number:4d}/{pages_to_process} | "
                f"Render: {render_time:.2f}s | YOLO: {yolo_time:.2f}s | "
                f"Headers: {len(section_headers)}"
            )

    benchmark_time = time.perf_counter() - benchmark_start
    doc.close()

    n = pages_to_process if pages_to_process > 0 else 1
    total_headers = sum(p["section_header_count"] for p in pages_data)

    output = {
        "book": os.path.basename(pdf_path),
        "total_pages": total_pages,
        "processed_pages": pages_to_process,
        "device": device,
        "model": MODEL_FILENAME,
        "benchmark": {
            "total_time_sec": round(benchmark_time, 3),
            "total_yolo_time_sec": round(total_yolo_time, 3),
            "average_page_time_sec": round(benchmark_time / n, 3),
            "pages_per_second": round(pages_to_process / benchmark_time, 2) if benchmark_time > 0 else 0,
        },
        "section_headers_detected": total_headers,
        "pages": pages_data,
    }

    print(f"  Section headers detected: {total_headers}")
    print(f"  Extraction time: {benchmark_time:.2f}s\n")
    return output


# =============================================================================
# EXCEL HIERARCHY GENERATOR
# =============================================================================

def build_font_size_level_map(data, tolerance=FONT_SIZE_TOLERANCE):
    """Clusters distinct font sizes into hierarchy levels (Level 1 = largest)."""
    sizes = []
    for page in data.get("pages", []):
        for region in page.get("regions", []):
            if region.get("label") != "Section-header":
                continue
            spans = region.get("spans", [])
            if not spans:
                continue
            try:
                size = float(spans[0].get("size", 0))
            except (TypeError, ValueError):
                continue
            if size > 0:
                sizes.append(round(size, 2))

    if not sizes:
        return {}

    unique_sizes = sorted(set(sizes), reverse=True)
    clusters = []
    for size in unique_sizes:
        if clusters and abs(clusters[-1][-1] - size) <= tolerance:
            clusters[-1].append(size)
        else:
            clusters.append([size])

    size_to_level = {}
    for level, cluster in enumerate(clusters, start=1):
        for size in cluster:
            size_to_level[size] = level

    return size_to_level


def is_running_header(region, text_counts, this_text):
    """Heuristic to eliminate repeating running headers and footers."""
    bbox = region.get("bbox_pdf", [0, 0, 0, 0])
    if len(bbox) < 2:
        return False
    if bbox[1] < RUNNING_HEADER_Y_MAX:
        return True
    if text_counts[this_text] >= REPEAT_COUNT_THRESHOLD:
        return True
    return False


def sanitize_excel_text(value):
    """Strips XML-invalid Unicode control characters to prevent openpyxl errors."""
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    return value


def build_excel_from_json(data, excel_output_path):
    """Creates a styled Excel workbook representing the section hierarchy."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    book_name = sanitize_excel_text(data.get("book", "Unknown Book"))
    print(f"  Building Excel hierarchy for: {book_name}")

    size_to_level = build_font_size_level_map(data)
    if not size_to_level:
        print("  WARNING: No valid font-size information found — cannot build hierarchy.")
        return False, 0

    print("  Font size hierarchy levels:")
    for size, level in sorted(size_to_level.items(), reverse=True):
        print(f"    {size:>6.2f} pt  →  Level {level}")

    raw_candidates = []
    for page in data.get("pages", []):
        pdf_page = page.get("pdf_page", 1)
        for region in page.get("regions", []):
            if region.get("label") != "Section-header":
                continue
            text = region.get("text", "").strip()
            if not text:
                continue
            raw_candidates.append((pdf_page, region, text))

    text_counts = Counter(text for _, _, text in raw_candidates)

    headings = []
    for pdf_page, region, text in raw_candidates:
        if is_running_header(region, text_counts, text):
            continue

        spans = region.get("spans", [])
        if not spans:
            continue

        try:
            font_size = float(spans[0].get("size", 0))
        except (TypeError, ValueError):
            continue

        font_name = spans[0].get("font", "")
        font_flags = int(spans[0].get("flags", 0))

        is_bold = bool(font_flags & 16 or "bold" in font_name.lower())
        is_italic = bool(font_flags & 2 or "italic" in font_name.lower())

        key = round(font_size, 2)
        level = size_to_level.get(key)
        if level is None:
            closest = min(size_to_level, key=lambda s: abs(s - key))
            if abs(closest - key) <= FONT_SIZE_TOLERANCE:
                level = size_to_level[closest]
            else:
                continue

        headings.append({
            "pdf_page": pdf_page,
            "level": level,
            "title": text,
            "font_name": font_name,
            "font_size": round(font_size, 2),
            "is_bold": is_bold,
            "is_italic": is_italic,
            "confidence": round(float(region.get("confidence", 0)), 4),
            "bbox_pdf": region.get("bbox_pdf", []),
        })

    headings.sort(key=lambda h: (h["pdf_page"], h["bbox_pdf"][1] if len(h["bbox_pdf"]) >= 2 else 0))
    print(f"  Headings after filtering running headers: {len(headings)}")

    if not headings:
        print("  WARNING: No headings survived filtering.")
        return False, 0

    # Derive main chapters and parent topics
    current_level_titles = {}
    for heading in headings:
        level, title = heading["level"], heading["title"]
        current_level_titles[level] = title
        for deeper_level in list(current_level_titles.keys()):
            if deeper_level > level:
                del current_level_titles[deeper_level]

        heading["main_chapter"] = current_level_titles.get(1, "General / Overview")
        heading["parent_topic"] = current_level_titles.get(level - 1, "") if level > 1 else ""

    total_pages = data.get("total_pages", data.get("processed_pages", headings[-1]["pdf_page"]))

    # Derive page ranges
    for i, heading in enumerate(headings):
        start_page, level = heading["pdf_page"], heading["level"]
        next_boundary = None

        for j in range(i + 1, len(headings)):
            if headings[j]["level"] <= level:
                next_boundary = headings[j]["pdf_page"]
                break

        end_page = max(start_page, next_boundary - 1) if next_boundary is not None else max(start_page, total_pages)
        heading["start_page"] = start_page
        heading["end_page"] = end_page
        heading["page_range"] = str(start_page) if start_page == end_page else f"{start_page} - {end_page}"

    rows = []
    for heading in headings:
        if heading["is_bold"] and heading["is_italic"]:
            font_style = "Bold, Italic"
        elif heading["is_bold"]:
            font_style = "Bold"
        elif heading["is_italic"]:
            font_style = "Italic"
        else:
            font_style = "Regular"

        rows.append({
            "Main Chapter / Topic": sanitize_excel_text(heading["main_chapter"]),
            "Section Header": sanitize_excel_text(heading["title"]),
            "Hierarchy Level": f"Level {heading['level']}",
            "Parent Topic": sanitize_excel_text(heading["parent_topic"]),
            "Start Page": heading["start_page"],
            "End Page": heading["end_page"],
            "Page Range": heading["page_range"],
            "Font Name": sanitize_excel_text(heading["font_name"]),
            "Font Size (pt)": heading["font_size"],
            "Font Style": font_style,
            "Confidence": heading["confidence"],
        })

    import pandas as pd
    df = pd.DataFrame(rows)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Extracted Section Headers"

    # Title header
    ws.append([f"Extracted Section Headers & Page Ranges — {book_name}"])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(df.columns))
    ws["A1"].font = Font(name="Calibri", size=14, bold=True, color="1F497D")
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.append([])

    # Table styling
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )
    alt_fill = PatternFill(start_color="F2F5F9", end_color="F2F5F9", fill_type="solid")

    ws.append(list(df.columns))
    for col_num in range(1, len(df.columns) + 1):
        cell = ws.cell(row=3, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row_idx, row in enumerate(df.itertuples(index=False, name=None), start=4):
        ws.append(list(row))
        for col_idx in range(1, len(df.columns) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = thin_border
            cell.font = Font(name="Calibri", size=10)
            if row_idx % 2 == 0:
                cell.fill = alt_fill
            if col_idx in (3, 5, 6, 7, 9, 11):
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # Column width fitting
    for column_cells in ws.columns:
        column_letter = get_column_letter(column_cells[0].column)
        max_length = 0
        for cell in column_cells:
            if cell.row == 1:
                continue
            max_length = max(max_length, len(str(cell.value or "")))
        ws.column_dimensions[column_letter].width = min(max(max_length + 3, 12), 65)

    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:{get_column_letter(len(df.columns))}{ws.max_row}"

    wb.save(excel_output_path)
    print(f"  Excel saved: {excel_output_path}\n")
    return True, len(headings)


# =============================================================================
# MAIN BATCH CONTROLLER
# =============================================================================

def process_batch(input_folder, output_folder, status_tracker_file, force=False, max_pages=None):
    """
    Scans input_folder, processes PDFs, writes results to output_folder,
    and records every status in the key-value status tracker JSON.
    """
    check_dependencies()

    os.makedirs(output_folder, exist_ok=True)
    status_tracker_path = os.path.join(output_folder, status_tracker_file)

    pdf_paths = find_pdfs(input_folder)
    if not pdf_paths:
        print(f"\n[!] No PDF files found in input directory: {os.path.abspath(input_folder)}")
        print("    Please add .pdf books to this folder and run again.\n")
        return

    print("=" * 70)
    print("BATCH PDF PROCESSOR: LOCAL FOLDER MODE")
    print("=" * 70)
    print(f"Input folder:       {os.path.abspath(input_folder)}")
    print(f"Output folder:      {os.path.abspath(output_folder)}")
    print(f"Status tracker:     {os.path.abspath(status_tracker_path)}")
    print(f"PDFs found:         {len(pdf_paths)}")
    if max_pages:
        print(f"Max pages/PDF:      {max_pages}")
    print("=" * 70)

    # Load persistent key-value status dictionary
    status_data = load_status_tracker(status_tracker_path)
    print(f"Previously tracked entries in status JSON: {len(status_data)}\n")

    device = select_device()
    model = load_model(device)

    batch_start = time.perf_counter()
    succeeded, failed, skipped = [], [], []

    for idx, pdf_path in enumerate(pdf_paths, start=1):
        filename = os.path.basename(pdf_path)
        stem = safe_stem(pdf_path)
        excel_filename = f"{stem}.xlsx"
        excel_path = os.path.join(output_folder, excel_filename)
        json_meta_path = os.path.join(output_folder, f"{stem}_data.json")

        print("=" * 70)
        print(f"[{idx}/{len(pdf_paths)}] Processing: {filename}")
        print("=" * 70)

        # Check existing key in status tracker
        prev_record = status_data.get(filename)
        if not force and prev_record:
            prev_status = prev_record.get("status", "")
            if SKIP_ALREADY_DONE and prev_status == "Parsed" and os.path.isfile(excel_path):
                print(f"  [SKIPPED] Already marked 'Parsed' in status JSON and {excel_filename} exists.\n")
                skipped.append((filename, "Already Parsed"))
                continue
            if SKIP_PREVIOUS_SCANNED and prev_status == "Scanned book (skip it)":
                print(f"  [SKIPPED] Previously identified as 'Scanned book (skip it)'.\n")
                skipped.append((filename, "Previously Scanned (skipped)"))
                continue

        # Check 1: Scanned/Image-only heuristic
        scanned, avg_chars, avg_coverage = is_scanned_pdf(pdf_path)
        if scanned:
            msg = (
                f"Scanned/image-only PDF detected (avg {avg_chars:.0f} chars/page, "
                f"{avg_coverage * 100:.0f}% page image coverage). No extractable text layer."
            )
            print(f"  {msg} Skipping.\n")

            # Update status JSON immediately
            status_data[filename] = {
                "status": "Scanned book (skip it)",
                "timestamp": datetime.now().isoformat(),
                "reason": msg,
                "avg_chars_per_page": round(avg_chars, 1),
                "avg_image_coverage": round(avg_coverage, 3),
                "file_path": os.path.abspath(pdf_path),
            }
            save_status_tracker(status_tracker_path, status_data)
            failed.append((filename, "Scanned book (skip it)"))
            continue

        # Check 2: Run DocLayout-YOLO + PyMuPDF
        try:
            extraction_data = run_doclayout_extraction(model, device, pdf_path, max_pages=max_pages)
            extraction_data["book"] = filename

            # Save individual metadata JSON
            if SAVE_PER_BOOK_JSON:
                with open(json_meta_path, "w", encoding="utf-8") as jf:
                    json.dump(extraction_data, jf, indent=2, ensure_ascii=False)
                print(f"  Saved metadata JSON: {json_meta_path}")

            # Build Excel hierarchy
            ok, header_count = build_excel_from_json(extraction_data, excel_path)

            if ok:
                status_data[filename] = {
                    "status": "Parsed",
                    "timestamp": datetime.now().isoformat(),
                    "excel_file": excel_filename,
                    "excel_path": os.path.abspath(excel_path),
                    "json_metadata": os.path.basename(json_meta_path) if SAVE_PER_BOOK_JSON else None,
                    "total_pages": extraction_data.get("total_pages", 0),
                    "processed_pages": extraction_data.get("processed_pages", 0),
                    "headings_count": header_count,
                    "file_path": os.path.abspath(pdf_path),
                }
                save_status_tracker(status_tracker_path, status_data)
                succeeded.append(filename)
            else:
                reason = "No headings survived filtering"
                status_data[filename] = {
                    "status": "No headings found",
                    "timestamp": datetime.now().isoformat(),
                    "reason": reason,
                    "file_path": os.path.abspath(pdf_path),
                }
                save_status_tracker(status_tracker_path, status_data)
                failed.append((filename, reason))

        except Exception as e:
            err_msg = str(e)
            print(f"  ERROR processing {filename}: {err_msg}")
            traceback.print_exc()

            status_data[filename] = {
                "status": f"Error: {err_msg}",
                "timestamp": datetime.now().isoformat(),
                "traceback": traceback.format_exc(),
                "file_path": os.path.abspath(pdf_path),
            }
            save_status_tracker(status_tracker_path, status_data)
            failed.append((filename, f"Error: {err_msg}"))

    batch_duration = time.perf_counter() - batch_start

    # Final summary
    print()
    print("=" * 70)
    print("BATCH RUN SUMMARY")
    print("=" * 70)
    print(f"Total PDFs found:       {len(pdf_paths)}")
    print(f"Successfully parsed:    {len(succeeded)}")
    print(f"Skipped (already done): {len(skipped)}")
    print(f"Failed / Scanned:       {len(failed)}")
    print(f"Total elapsed time:     {batch_duration:.1f}s")
    print(f"Output folder:          {os.path.abspath(output_folder)}")
    print(f"Status Tracker JSON:    {os.path.abspath(status_tracker_path)}")

    if failed:
        print("\nSkipped or Failed Books:")
        for name, reason in failed:
            print(f"  - {name}: {reason}")
    print("=" * 70)


# =============================================================================
# CLI PARSER
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Batch PDF Section Header & Hierarchy Extractor using DocLayout-YOLO and PyMuPDF"
    )
    parser.add_argument(
        "-i", "--input-dir",
        default=DEFAULT_INPUT_FOLDER,
        help=f"Folder containing PDF books (default: {DEFAULT_INPUT_FOLDER})"
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=DEFAULT_OUTPUT_FOLDER,
        help=f"Folder where .xlsx and .json files will be written (default: {DEFAULT_OUTPUT_FOLDER})"
    )
    parser.add_argument(
        "-s", "--status-file",
        default=STATUS_TRACKER_FILENAME,
        help=f"Name of tracking JSON file (default: {STATUS_TRACKER_FILENAME})"
    )
    parser.add_argument(
        "-m", "--max-pages",
        type=int,
        default=None,
        help="Maximum pages to process per PDF (default: None = all pages)"
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force re-processing of books even if already marked as Parsed in status JSON"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    process_batch(
        input_folder=args.input_dir,
        output_folder=args.output_dir,
        status_tracker_file=args.status_file,
        force=args.force,
        max_pages=args.max_pages,
    )
