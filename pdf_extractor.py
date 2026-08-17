import re
import pdfplumber


# ============================================================
# Phase 1: PDF -> Course -> Unit extraction
#
# This phase only identifies:
#   Course code
#   Course title
#   Unit number
#   Unit title
#   Unit body
#
# It does NOT decide topic/subtopic hierarchy.
# ============================================================


# ------------------------------------------------------------
# Text cleanup
# ------------------------------------------------------------

def normalize_text(text):
    text = text.replace("\r", "")
    text = text.replace("\u00ad", "")
    text = text.replace("\xa0", " ")

    # Normalize spaces but preserve newlines.
    text = re.sub(r"[ \t]+", " ", text)

    # Remove whitespace-only lines.
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)

    return text.strip()


def clean_line(line):
    line = line.replace("\xa0", " ")
    line = re.sub(r"\s+", " ", line)
    return line.strip()


# ------------------------------------------------------------
# PDF -> text
# ------------------------------------------------------------

def extract_text(pdf_path, start_page=1, end_page=None):

    with pdfplumber.open(pdf_path) as pdf:

        end_page = end_page or len(pdf.pages)

        pages = []

        for i in range(start_page - 1, end_page):

            page_text = pdf.pages[i].extract_text() or ""

            if page_text.strip():
                pages.append(page_text)

    return normalize_text("\n".join(pages))


# ------------------------------------------------------------
# Course detection
# ------------------------------------------------------------

# Match a course-header line: code at start of line, followed (on the same
# line) by the L T P E C credit pattern, e.g. "CS3301 DATABASE MGMT 3 0 0 0 3".
# This prevents false hits on in-text course-code references.
COURSE_CODE_RE = re.compile(
    r"(?m)^\s*([A-Z]{2,6}\d{3,5})\b.*\b\d\s+\d\s+\d\s+\d\s+\d\s*$"
)


def find_course_headers(text):

    headers = []

    for match in COURSE_CODE_RE.finditer(text):

        code = match.group(1)

        headers.append(
            (code, match.start())
        )

    return headers


def extract_course_header(text, position, code):

    region = text[position:]

    lines = region.splitlines()

    if not lines:
        return code, ""

    # First line normally contains:
    #
    # CS3301 DATABASE MANAGEMENT SYSTEMS 3 0 0 0 3
    #
    first_line = clean_line(lines[0])

    title_part = re.sub(
        rf"^\s*{re.escape(code)}\b",
        "",
        first_line,
        count=1,
        flags=re.IGNORECASE
    ).strip()

    title_parts = []

    if title_part:
        title_parts.append(title_part)

    # Sometimes title continues onto the next few lines.
    for line in lines[1:7]:

        line = clean_line(line)

        if not line:
            continue

        # L T P E C
        if re.fullmatch(r"\d\s+\d\s+\d\s+\d\s+\d", line):
            break

        # Unit begins.
        if re.match(r"^UNIT\b", line, re.IGNORECASE):
            break

        # Common sections.
        if re.match(
            r"^(OBJECTIVES|COURSE OBJECTIVES|OUTCOMES|COURSE OUTCOMES|"
            r"TEXTBOOKS|REFERENCE BOOKS|REFERENCES)\b",
            line,
            re.IGNORECASE
        ):
            break

        # Numeric header.
        if re.fullmatch(r"[\d\s]+", line):
            break

        title_parts.append(line)

    title = " ".join(title_parts)

    # Remove accidental L/T/P/E/C values.
    title = re.sub(
        r"\s+\d\s+\d\s+\d\s+\d\s+\d\s*$",
        "",
        title
    )

    title = re.sub(
        r"\s+",
        " ",
        title
    ).strip(" -:.")

    return code, title


# ------------------------------------------------------------
# Course blocks
# ------------------------------------------------------------

def split_course_blocks(text):

    headers = find_course_headers(text)

    blocks = []

    for i, (code, position) in enumerate(headers):

        next_position = (
            headers[i + 1][1]
            if i + 1 < len(headers)
            else len(text)
        )

        code, title = extract_course_header(
            text,
            position,
            code
        )

        course_text = text[position:next_position]

        blocks.append(
            (
                code,
                title,
                course_text
            )
        )

    return blocks


# ------------------------------------------------------------
# Unit detection
# ------------------------------------------------------------

UNIT_RE = re.compile(
    r"""
    (?im)
    ^\s*
    UNIT
    \s*
    (?:[-:]\s*)?
    ([IVXLC]+|\d+)
    \s*
    (?:[-:]\s*)?
    ([A-Z0-9][A-Za-z0-9 &,\-\'\./()]{0,100}?)
    \s*
    (?:[-:]?\s*)?
    (\d{1,3})?
    \s*$
    """,
    re.VERBOSE
)


def extract_units(course_text):

    course_text = normalize_text(course_text)

    matches = list(UNIT_RE.finditer(course_text))

    units = []

    for i, match in enumerate(matches):

        unit_no = match.group(1)

        unit_title = match.group(2) or ""

        unit_title = re.sub(
            r"\s+",
            " ",
            unit_title
        ).strip(" -:.")

        start = match.end()

        end = (
            matches[i + 1].start()
            if i + 1 < len(matches)
            else len(course_text)
        )

        body = course_text[start:end]

        # Remove sections that aren't unit topics.
        body = re.split(
            r"\bTOTAL\s+PERIODS\b",
            body,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0]

        body = re.split(
            r"\bCOURSE\s+OUTCOMES?\b",
            body,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0]

        body = re.split(
            r"\bTEXT\s+BOOKS?\b|\bTEXTBOOKS\b|\bREFERENCE\s+BOOKS?\b|\bREFERENCES\b",
            body,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0]

        body = normalize_text(body)

        units.append(
            (
                unit_no,
                unit_title,
                body
            )
        )

    return units