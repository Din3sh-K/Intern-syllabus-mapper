import re
import os
import pandas as pd

from pdf_extractor import (
    extract_text,
    split_course_blocks,
    extract_units
)

from Topicextractor2 import (
    extract_topics_llm,
    split_topics_fallback,
    OLLAMA_MODEL
)


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

PDF_PATH = "SSN_BE_CSE.pdf"

START_PAGE = 29
END_PAGE = None

OUTPUT_EXCEL = "syllabus_topics.xlsx"

# Actual model name, e.g. gemma3:4b
MODEL_NAME = OLLAMA_MODEL

# Windows does not allow ":" in folder names
SAFE_MODEL_NAME = MODEL_NAME.replace(":", "_")

OUTPUT_DIR = os.path.join(
    "model_outputs",
    SAFE_MODEL_NAME
)


# ------------------------------------------------------------
# SAVE RAW MODEL OUTPUT
# ------------------------------------------------------------

def save_raw_output(
    subject_code,
    subject_name,
    unit_no,
    unit_body,
    raw_response
):

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # One file per SUBJECT
    filename = f"{subject_code}.txt"

    filepath = os.path.join(
        OUTPUT_DIR,
        filename
    )

    # "a" = append, so Unit I, II, III... all go
    # into the same subject file.
    with open(
        filepath,
        "a",
        encoding="utf-8"
    ) as f:

        f.write("\n")
        f.write("=" * 70 + "\n")

        f.write(
            f"SUBJECT: {subject_code} - {subject_name}\n"
        )

        f.write(
            f"UNIT: {unit_no}\n"
        )

        f.write(
            f"MODEL: {MODEL_NAME}\n"
        )

        f.write("=" * 70 + "\n\n")


        # ----------------------------------------------------
        # Original input given to the LLM
        # ----------------------------------------------------

        f.write("INPUT\n")
        f.write("-" * 70 + "\n")

        f.write(unit_body)

        f.write("\n\n")


        # ----------------------------------------------------
        # Raw LLM response
        # ----------------------------------------------------

        f.write("RAW MODEL OUTPUT\n")
        f.write("-" * 70 + "\n")

        if raw_response:
            f.write(raw_response)
        else:
            f.write("[NO RESPONSE]")

        f.write("\n\n")


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    # --------------------------------------------------------
    # Extract syllabus PDF
    # --------------------------------------------------------

    raw_text = extract_text(
        PDF_PATH,
        START_PAGE,
        END_PAGE
    )

    blocks = split_course_blocks(
        raw_text
    )


    # --------------------------------------------------------
    # Storage for Excel
    # --------------------------------------------------------

    rows = []

    llm_success_count = 0
    fallback_count = 0


    # --------------------------------------------------------
    # TEST ONLY FIRST 4 SUBJECTS
    # --------------------------------------------------------

    for ctr, block in enumerate(blocks):

        if ctr == 4:
            break


        subject_code, subject_name, course_text = block


        subject_prefix = re.sub(
            r"[^A-Z]",
            "",
            subject_code
        )[:4]


        units = extract_units(
            course_text
        )


        # ----------------------------------------------------
        # Process each unit
        # ----------------------------------------------------

        for unit_no, unit_title, unit_body in units:

            if not unit_body.strip():

                print(
                    f"Skipping "
                    f"{subject_code} "
                    f"Unit {unit_no} — empty body."
                )

                continue


            print(
                f"Processing "
                f"{subject_code} "
                f"Unit {unit_no}..."
            )


            # ------------------------------------------------
            # LLM extraction
            # ------------------------------------------------

            topic_pairs, raw_response = extract_topics_llm(
                unit_body
            )


            # ------------------------------------------------
            # SAVE RAW RESPONSE
            #
            # No judgement here.
            # Whatever the model returned gets saved.
            # ------------------------------------------------

            save_raw_output(
                subject_code,
                subject_name,
                unit_no,
                unit_body,
                raw_response
            )


            # ------------------------------------------------
            # Fallback only for Excel generation
            # ------------------------------------------------

            if topic_pairs is None:

                topic_pairs = split_topics_fallback(
                    unit_body
                )

                fallback_count += 1

            else:

                llm_success_count += 1


            # ------------------------------------------------
            # Add extracted topics to Excel
            # ------------------------------------------------

            for index, (topic, sub_topic) in enumerate(
                topic_pairs,
                start=1
            ):

                rows.append({

                    "id":
                        f"{subject_prefix}_M{unit_no}_T{index}",

                    "subject_code":
                        subject_code,

                    "subject_name":
                        subject_name,

                    "module_no":
                        unit_no,

                    "module_title":
                        unit_title,

                    "topic":
                        topic,

                    "sub_topic":
                        sub_topic,
                })


    # --------------------------------------------------------
    # Create Excel
    # --------------------------------------------------------

    df = pd.DataFrame(
        rows
    )

    df.to_excel(
        OUTPUT_EXCEL,
        index=False
    )


    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("\n" + "=" * 60)

    print(
        "Courses detected in PDF:",
        len(blocks)
    )

    print(
        "Subjects tested:",
        min(4, len(blocks))
    )

    print(
        "Topic Records:",
        len(df)
    )

    print(
        "Units parsed by LLM:",
        llm_success_count
    )

    print(
        "Units using fallback:",
        fallback_count
    )

    print("=" * 60)


    print(
        df.head(30)
    )

    print(
        f"\nOutput saved to: {OUTPUT_EXCEL}"
    )

    print(
        f"Raw model outputs saved to: "
        f"{OUTPUT_DIR}/"
    )


# ------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------

if __name__ == "__main__":
    main()