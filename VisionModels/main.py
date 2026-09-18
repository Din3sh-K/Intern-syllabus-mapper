"""
single_page_vision_test.py

Renders ONE page of the syllabus PDF as an image and sends it to a
vision-capable Ollama model, so you can manually eyeball extraction
accuracy before committing to a full vision-based pipeline.

Change PAGE_NUM below and re-run to test different pages.

Requires:
    pip install pdfplumber requests Pillow
    # pdfplumber's to_image() also needs a system dependency for
    # rendering — either poppler (pdftoppm) or ImageMagick, depending
    # on your pdfplumber version. On macOS:
    #   brew install poppler
    ollama pull qwen3.8:27b
    ollama serve             (must be running)
"""

import io
import base64
import requests
import pdfplumber


# ------------------------------------------------------------
# CONFIG — edit these
# ------------------------------------------------------------

PDF_PATH = "SSN_BE_CSE.pdf"

PAGE_NUM = 29          # 1-indexed, same as what your PDF viewer shows

OLLAMA_MODEL = "qwen3-vl:8b"
OLLAMA_URL = "http://localhost:11434/api/generate"

DPI = 200               # higher = sharper but slower / more memory


PROMPT = """You are reading one page from a university engineering syllabus PDF.

Extract the syllabus content on this page as a hierarchy of Topics and Subtopics.

Rules:
- A "Topic" is a major heading.
- A "Subtopic" is a specific concept listed under that topic. Concepts in the
  source are often separated by commas, dashes, or bullets — but do NOT split
  a single multi-word concept into fragments just because it contains an
  internal comma or hyphen. For example "A-scan, B-scan, C-scan displays" is
  ONE subtopic, not four.
- Preserve the exact wording from the page. Do not summarize or rephrase.
- Output ONLY lines in this exact format, nothing else:
Topic: <topic text>
Subtopic: <subtopic text>
"""


# ------------------------------------------------------------
# FUNCTIONS
# ------------------------------------------------------------

def render_page_as_image(pdf_path, page_num_1_indexed, dpi):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_num_1_indexed - 1]   # pdfplumber is 0-indexed internally
        page_image = page.to_image(resolution=dpi)

        buf = io.BytesIO()
        page_image.original.save(buf, format="PNG")
        return buf.getvalue()


def call_ollama_vision(image_bytes, prompt, model):
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": model,
        "prompt": prompt,
        "images": [b64_image],
        "stream": False,
        "thinking": False,
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=None
    )

    print("\nHTTP STATUS:", response.status_code)
    print("\nRAW HTTP RESPONSE:")
    print(response.text)

    response.raise_for_status()

    data = response.json()

    print("\nPARSED JSON:")
    print(data)

    return data.get("response", "")


def main():
    print(f"Rendering page {PAGE_NUM} of {PDF_PATH} at {DPI} DPI...")
    img_bytes = render_page_as_image(PDF_PATH, PAGE_NUM, DPI)

    # Save the rendered page so you can visually confirm it's the
    # page you meant to test.
    with open("test_page_preview.png", "wb") as f:
        f.write(img_bytes)
    print("Saved preview -> test_page_preview.png (check it's the right page)")

    print(f"Sending to {OLLAMA_MODEL}...")
    raw_response = call_ollama_vision(img_bytes, PROMPT, OLLAMA_MODEL)

    print("\n" + "=" * 70)
    print("RAW MODEL OUTPUT")
    print("=" * 70)
    print(raw_response)


if __name__ == "__main__":
    main()