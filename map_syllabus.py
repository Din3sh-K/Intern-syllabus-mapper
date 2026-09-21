#!/usr/bin/env python3
"""
Syllabus to Textbook TOC & Real Chapter Page Range Mapper (Ollama Nomic)
Maps extracted syllabus topics to real textbook chapters and multi-page spans,
eliminating single-page noise and micro-heading artifacts.

Usage Examples:
    # 1. Map syllabus topics to real textbook chapters (default mode)
    python map_syllabus.py

    # 2. Map Technical English (UEN2176) to the English textbook chapters
    python map_syllabus.py --subject UEN2176 --book communicative-english-for-engineers-professionals_compress

    # 3. Map Matrices and Calculus (UMA2176) to thinkstats2 chapters
    python map_syllabus.py --subject UMA2176 --book thinkstats2

    # 4. Detailed mode (includes major sections spanning >= 2 pages)
    python map_syllabus.py --mode detailed
"""

import os
import sys
import argparse
import pandas as pd

from syllabus_matcher import (
    SyllabusBookMapper,
    load_syllabus,
    load_book_toc,
    discover_books,
    export_to_excel,
    export_to_json,
)


DEFAULT_SYLLABUS = "model_outputs/gemma3_4b/syllabus_topics.xlsx"
DEFAULT_BOOKS_DIR = "output_results"
DEFAULT_OUTPUT_EXCEL = "syllabus_book_mapping.xlsx"
DEFAULT_MODEL = "nomic-embed-text"

# Default textbook pairings for the 4 gemma3:4b subjects
DEFAULT_SUBJECT_BOOK_PAIRS = {
    "UEN2176": "communicative-english-for-engineers-professionals_compress",
    "UMA2176": "thinkstats2",
    "UPH2176": "quantum-computation-and-quantum-information-nielsen-chuang",
    "UCY2176": "quantum-computation-and-quantum-information-nielsen-chuang",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Map syllabus topics to real textbook chapters and verified multi-page ranges."
    )
    parser.add_argument(
        "-s", "--syllabus",
        default=DEFAULT_SYLLABUS,
        help=f"Path to syllabus topics Excel file (default: {DEFAULT_SYLLABUS})"
    )
    parser.add_argument(
        "-d", "--books-dir",
        default=DEFAULT_BOOKS_DIR,
        help=f"Directory containing parsed textbook Excel/JSON outputs (default: {DEFAULT_BOOKS_DIR})"
    )
    parser.add_argument(
        "-b", "--book",
        default=None,
        help="Specific textbook name or stem to map against (e.g. 'thinkstats2' or 'communicative-english...')"
    )
    parser.add_argument(
        "--subject",
        default=None,
        help="Filter syllabus to a specific subject code (e.g. 'UEN2176', 'UMA2176', 'UPH2176', 'UCY2176')"
    )
    parser.add_argument(
        "--mode",
        choices=["chapter", "detailed"],
        default="chapter",
        help="Mapping granularity: 'chapter' (default, noise-free real chapters) or 'detailed' (includes major sections)"
    )
    parser.add_argument(
        "-k", "--top-k",
        type=int,
        default=1,
        help="Number of candidate chapters to retrieve per syllabus topic (default: 1)"
    )
    parser.add_argument(
        "-t", "--threshold",
        type=float,
        default=0.40,
        help="Minimum cosine similarity threshold (default: 0.40)"
    )
    parser.add_argument(
        "-m", "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama embedding model name (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "-o", "--output",
        default=DEFAULT_OUTPUT_EXCEL,
        help=f"Output Excel file path (default: {DEFAULT_OUTPUT_EXCEL})"
    )
    parser.add_argument(
        "--json",
        nargs="?",
        const="syllabus_book_mapping.json",
        default=None,
        help="Also export results to JSON format (optional path, default: syllabus_book_mapping.json)"
    )
    parser.add_argument(
        "--include-frontmatter",
        action="store_true",
        help="Include frontmatter sections (Contents, Preface) in candidates"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 75)
    print("SYLLABUS → TEXTBOOK REAL CHAPTER & PAGE RANGE MAPPER (Ollama Nomic)")
    print("=" * 75)

    # 1. Load Syllabus
    try:
        subject_filter = [args.subject] if args.subject else None
        syllabus_df = load_syllabus(args.syllabus, subject_filter=subject_filter)
    except Exception as e:
        print(f"Error loading syllabus: {e}")
        sys.exit(1)

    subjects_present = syllabus_df[["subject_code", "subject_name"]].drop_duplicates().to_dict(orient="records")
    print(f"Loaded {len(syllabus_df)} syllabus topics across {len(subjects_present)} subjects:")
    for s in subjects_present:
        cnt = len(syllabus_df[syllabus_df["subject_code"] == s["subject_code"]])
        print(f"  - {s['subject_code']} ({s['subject_name']}): {cnt} topics")

    # 2. Initialize Mapper
    mapper = SyllabusBookMapper(model=args.model)
    if not mapper.embedder.check_health():
        print(f"Warning: Model '{args.model}' not reported in active tags or Ollama is offline.")

    all_mappings = []

    # 3. Process mappings per subject / target book
    if args.book:
        print(f"\nLoading TOC ({args.mode} mode) for textbook: '{args.book}'...")
        toc_df = load_book_toc(
            args.book,
            output_dir=args.books_dir,
            mode=args.mode,
            include_frontmatter=args.include_frontmatter,
        )
        print(f"  Extracted {len(toc_df)} entries with true multi-page spans.")

        print("\nAligning syllabus topics to textbook chapters...")
        res_df = mapper.map_syllabus_to_toc(
            syllabus_df=syllabus_df,
            toc_df=toc_df,
            top_k=args.top_k,
            threshold=args.threshold,
            show_progress=True,
        )
        all_mappings.append(res_df)

    else:
        # Map each of the subjects to its designated textbook TOC
        for s in subjects_present:
            sub_code = s["subject_code"]
            sub_df = syllabus_df[syllabus_df["subject_code"] == sub_code].copy()

            target_book = DEFAULT_SUBJECT_BOOK_PAIRS.get(sub_code)
            if not target_book:
                print(f"\nWarning: No default textbook configured for {sub_code}. Skipping.")
                continue

            print("\n" + "-" * 75)
            print(f"Mapping {sub_code} ({s['subject_name']}) → Chapters of '{target_book}'")
            print("-" * 75)

            try:
                toc_df = load_book_toc(
                    target_book,
                    output_dir=args.books_dir,
                    mode=args.mode,
                    include_frontmatter=args.include_frontmatter,
                )
                chaps = toc_df[toc_df["is_chapter"]]["main_chapter"].unique()
                print(f"  Extracted {len(chaps)} Real Chapters: {', '.join(chaps[:4])}...")

                res_df = mapper.map_syllabus_to_toc(
                    syllabus_df=sub_df,
                    toc_df=toc_df,
                    top_k=args.top_k,
                    threshold=args.threshold,
                    show_progress=False,
                )
                print(f"  -> Successfully mapped {len(res_df)} topics to chapters & multi-page ranges.")
                all_mappings.append(res_df)

            except Exception as e:
                print(f"Error mapping {sub_code} to {target_book}: {e}")

    if not all_mappings or all(df.empty for df in all_mappings):
        print("No matches generated.")
        sys.exit(0)

    final_df = pd.concat(all_mappings, ignore_index=True)

    # 4. Summary & Quality Breakdown
    print("\n" + "=" * 75)
    print(f"MAPPING COMPLETE: Generated {len(final_df)} alignment entries.")
    print("Match Quality Breakdown:")
    for k, v in final_df["confidence"].value_counts().items():
        print(f"  - {k}: {v} matches")

    export_to_excel(
        final_df,
        output_path=args.output,
        model_name=args.model,
    )

    if args.json:
        export_to_json(final_df, output_path=args.json)

    print(f"Output Excel saved to: {os.path.abspath(args.output)}")
    if args.json:
        print(f"JSON saved to:         {os.path.abspath(args.json)}")
    print("=" * 75)


if __name__ == "__main__":
    main()
