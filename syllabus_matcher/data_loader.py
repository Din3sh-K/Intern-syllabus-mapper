"""
Data Loader for Extracted Syllabus and Textbook Table of Contents (TOC).
Extracts real, noise-free textbook chapters and verified multi-page spans,
avoiding single-page subtopic collapse and OCR noise.
"""

import os
import re
import json
import glob
from typing import List, Optional, Dict, Union, Any
import pandas as pd


FRONTMATTER_KEYWORDS = {
    "contents",
    "table of contents",
    "brief contents",
    "preface",
    "index",
    "about the author",
    "about the authors",
    "acknowledgments",
    "acknowledgements",
    "cover",
    "title page",
    "copyright",
    "half title",
}


def clean_text(val: Any) -> str:
    """Cleans null values and converts to stripped string."""
    if pd.isna(val) or val is None:
        return ""
    text = str(val).strip()
    return re.sub(r"\s+", " ", text)


# -----------------------------------------------------------------------------
# Syllabus Loader
# -----------------------------------------------------------------------------

def load_syllabus(
    source_path: Optional[str] = None,
    subject_filter: Optional[Union[str, List[str]]] = None,
) -> pd.DataFrame:
    """
    Loads extracted syllabus topics from an Excel file.
    Defaults to model_outputs/gemma3_4b/syllabus_topics.xlsx or syllabus_topics.xlsx.
    """
    if not source_path:
        candidates = [
            "model_outputs/gemma3_4b/syllabus_topics.xlsx",
            "syllabus_topics.xlsx",
            "model_outputs/gemma3_12b/syllabus_topics.xlsx",
        ]
        for c in candidates:
            if os.path.isfile(c):
                source_path = c
                break

    if not source_path or not os.path.isfile(source_path):
        raise FileNotFoundError(f"Syllabus file not found at: {source_path}")

    df = pd.read_excel(source_path)

    required_cols = ["subject_code", "topic"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Required syllabus column '{col}' missing from {source_path}")

    # Standardize column strings
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].apply(clean_text)

    # Optional subject filtering
    if subject_filter:
        if isinstance(subject_filter, str):
            subject_filter = [subject_filter]
        subject_filter = [s.strip().upper() for s in subject_filter]
        df = df[df["subject_code"].str.upper().isin(subject_filter)].copy()

    if df.empty:
        raise ValueError("No syllabus records found after filtering.")

    # Generate semantic query texts
    def make_query_text(row):
        parts = []
        if "subject_name" in row and row["subject_name"]:
            parts.append(row["subject_name"])
        if "module_title" in row and row["module_title"]:
            module_info = f"Unit {row.get('module_no', '')}: {row['module_title']}".strip()
            parts.append(module_info)
        
        topic = row.get("topic", "")
        sub_topic = row.get("sub_topic", "")
        if topic and sub_topic:
            parts.append(f"{topic} - {sub_topic}")
        elif topic:
            parts.append(topic)
        elif sub_topic:
            parts.append(sub_topic)

        return " | ".join(p for p in parts if p)

    def make_short_query(row):
        topic = row.get("topic", "")
        sub_topic = row.get("sub_topic", "")
        if topic and sub_topic:
            return f"{topic}: {sub_topic}"
        return topic or sub_topic or ""

    df["query_text"] = df.apply(make_query_text, axis=1)
    df["short_query"] = df.apply(make_short_query, axis=1)

    return df.reset_index(drop=True)


# -----------------------------------------------------------------------------
# Textbook Real Chapters & Clean TOC Extractor
# -----------------------------------------------------------------------------

def resolve_book_path(book_path_or_stem: str, output_dir: str = "output_results") -> str:
    """Finds the .xlsx or _data.json file for a given book name or stem."""
    if os.path.isfile(book_path_or_stem):
        return book_path_or_stem

    direct_excel = os.path.join(output_dir, book_path_or_stem)
    if os.path.isfile(direct_excel):
        return direct_excel

    stem = os.path.splitext(book_path_or_stem)[0]
    excel_candidate = os.path.join(output_dir, f"{stem}.xlsx")
    if os.path.isfile(excel_candidate):
        return excel_candidate

    matches = glob.glob(os.path.join(output_dir, f"*{stem}*.xlsx"))
    if matches:
        return matches[0]

    json_candidate = os.path.join(output_dir, f"{stem}_data.json")
    if os.path.isfile(json_candidate):
        return json_candidate

    raise FileNotFoundError(f"Could not locate book outline for '{book_path_or_stem}' in '{output_dir}'.")


def load_book_toc(
    book_source: str,
    output_dir: str = "output_results",
    mode: str = "chapter",
    include_frontmatter: bool = False,
) -> pd.DataFrame:
    """
    Extracts structured, noise-free Table of Contents (TOC) with Real Chapters and multi-page spans.
    
    Args:
        book_source: Book filename, stem, or full path.
        output_dir: Directory containing parsed textbook files.
        mode: 'chapter' (default, pure real chapters with true multi-page ranges)
              or 'detailed' (chapters plus major sections spanning >= 2 pages).
        include_frontmatter: Whether to include frontmatter sections (Preface, Contents).

    Returns:
        pd.DataFrame: Noise-free TOC with true chapter page ranges.
    """
    file_path = resolve_book_path(book_source, output_dir=output_dir)
    book_stem = os.path.splitext(os.path.basename(file_path))[0]
    if book_stem.endswith(".pdf"):
        book_stem = book_stem[:-4]

    # Read Excel header row dynamically
    df_raw = pd.read_excel(file_path, header=None)
    header_row_idx = 0
    for idx in range(min(10, len(df_raw))):
        row_vals = [clean_text(x).lower() for x in df_raw.iloc[idx].tolist()]
        if any("section header" == x for x in row_vals) or (
            any("section header" in x for x in row_vals) and any("chapter" in x for x in row_vals)
        ):
            header_row_idx = idx
            break

    df = pd.read_excel(file_path, skiprows=header_row_idx)

    col_map = {
        "Main Chapter / Topic": "main_chapter",
        "Section Header": "section_header",
        "Hierarchy Level": "hierarchy_level",
        "Parent Topic": "parent_topic",
        "Start Page": "start_page",
        "End Page": "end_page",
        "Page Range": "page_range",
    }
    df = df.rename(columns={c: col_map[c.strip()] for c in df.columns if c.strip() in col_map})
    df = df[df["section_header"].notna() & (df["section_header"].astype(str).str.strip() != "")].copy()

    # Extract numeric level: e.g. "Level 3" -> 3
    df["lvl_num"] = df["hierarchy_level"].apply(
        lambda x: int(re.search(r"\d+", str(x)).group(0)) if re.search(r"\d+", str(x)) else 99
    )

    # Identify the Real Chapter Level: tier with 3 to 50 occurrences
    counts = df["lvl_num"].value_counts()
    candidates = [lvl for lvl, count in counts.items() if 3 <= count <= 50]
    chap_lvl = min(candidates) if candidates else min(counts.index)

    raw_chaps = df[df["lvl_num"] == chap_lvl].copy()
    if not include_frontmatter:
        raw_chaps = raw_chaps[~raw_chaps["section_header"].str.lower().isin(FRONTMATTER_KEYWORDS)]
    raw_chaps = raw_chaps[raw_chaps["section_header"].str.len() > 2]

    # Fusing "Chapter X" with the following title on adjacent pages
    chapter_entries = []
    rows = list(raw_chaps.iterrows())
    i = 0
    while i < len(rows):
        _, curr = rows[i]
        curr_title = clean_text(curr["section_header"])
        curr_sp = int(curr["start_page"])
        curr_ep = int(curr["end_page"])

        if re.match(r"^chapter\s+\d+$", curr_title, re.I) and i + 1 < len(rows):
            _, nxt = rows[i + 1]
            nxt_title = clean_text(nxt["section_header"])
            nxt_sp = int(nxt["start_page"])
            nxt_ep = int(nxt["end_page"])
            if nxt_sp - curr_sp <= 1:
                curr_title = f"{curr_title}: {nxt_title}"
                curr_ep = max(curr_ep, nxt_ep)
                i += 1

        chapter_entries.append({
            "title": curr_title,
            "start_page": curr_sp,
            "end_page": curr_ep,
            "level": f"Level {curr['lvl_num']}",
        })
        i += 1

    # Recompute end_page as next_chapter.start_page - 1 for proper chapter spans
    total_pages = int(df["end_page"].max())
    for j in range(len(chapter_entries)):
        sp = chapter_entries[j]["start_page"]
        if j + 1 < len(chapter_entries):
            ep = max(sp, chapter_entries[j + 1]["start_page"] - 1)
        else:
            ep = max(sp, total_pages)
        chapter_entries[j]["end_page"] = ep
        chapter_entries[j]["page_range"] = f"{sp} - {ep}" if sp != ep else str(sp)
        chapter_entries[j]["total_pages"] = ep - sp + 1

    # Format into DataFrame
    records = []
    for chap in chapter_entries:
        # Ignore 1-page cover/title artifacts at page <= 5
        if not include_frontmatter and chap["start_page"] <= 5 and chap["total_pages"] <= 2:
            continue

        records.append({
            "book_stem": book_stem,
            "is_chapter": True,
            "main_chapter": chap["title"],
            "chapter_start_page": chap["start_page"],
            "chapter_end_page": chap["end_page"],
            "chapter_page_range": chap["page_range"],
            "toc_topic": chap["title"],
            "toc_level": chap["level"],
            "extract_start_page": chap["start_page"],
            "extract_end_page": chap["end_page"],
            "extract_page_range": chap["page_range"],
            "doc_text": f"Chapter: {chap['title']}",
        })

    # Optional: include clean major sections (mode="detailed")
    if mode == "detailed":
        first_chap_sp = chapter_entries[0]["start_page"] if chapter_entries else 1
        for idx, r in df.iterrows():
            lvl = r["lvl_num"]
            header = clean_text(r["section_header"])
            sp = int(r["start_page"])
            ep = int(r["end_page"])

            # Keep only major subtopics that span at least 2 pages and are within chapter body
            if lvl > chap_lvl and sp >= first_chap_sp and (ep - sp >= 1):
                if header.lower() not in FRONTMATTER_KEYWORDS and len(header) > 3:
                    # Find which chapter it belongs to
                    owning_chap = None
                    for chap in chapter_entries:
                        if chap["start_page"] <= sp <= chap["end_page"]:
                            owning_chap = chap
                            break
                    if owning_chap:
                        sub_range = f"{sp} - {ep}" if sp != ep else str(sp)
                        records.append({
                            "book_stem": book_stem,
                            "is_chapter": False,
                            "main_chapter": owning_chap["title"],
                            "chapter_start_page": owning_chap["start_page"],
                            "chapter_end_page": owning_chap["end_page"],
                            "chapter_page_range": owning_chap["page_range"],
                            "toc_topic": header,
                            "toc_level": f"Level {lvl}",
                            "extract_start_page": sp,
                            "extract_end_page": ep,
                            "extract_page_range": sub_range,
                            "doc_text": f"{owning_chap['title']} > {header}",
                        })

    return pd.DataFrame(records).reset_index(drop=True)


def discover_books(output_dir: str = "output_results") -> List[Dict[str, Any]]:
    """Discovers all parsed books in the output_results directory."""
    status_path = os.path.join(output_dir, "processing_status.json")
    books = []

    if os.path.isfile(status_path):
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                status_data = json.load(f)
            for orig_name, info in status_data.items():
                if info.get("status") == "Parsed":
                    excel_file = info.get("excel_file")
                    excel_path = os.path.join(output_dir, excel_file) if excel_file else None
                    if excel_path and os.path.isfile(excel_path):
                        books.append({
                            "name": orig_name,
                            "stem": os.path.splitext(excel_file)[0],
                            "excel_file": excel_file,
                            "excel_path": excel_path,
                            "headings_count": info.get("headings_count", 0),
                            "total_pages": info.get("total_pages", 0),
                        })
        except Exception as e:
            print(f"Warning reading status json: {e}")

    if not books:
        for f in glob.glob(os.path.join(output_dir, "*.xlsx")):
            base = os.path.basename(f)
            if base.startswith("~$") or base.startswith("mapped_"):
                continue
            books.append({
                "name": base,
                "stem": os.path.splitext(base)[0],
                "excel_file": base,
                "excel_path": f,
                "headings_count": 0,
                "total_pages": 0,
            })

    return books
