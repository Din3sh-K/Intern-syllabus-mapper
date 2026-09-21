"""
Syllabus Matcher Package:
Semantic alignment between university syllabus topics and textbook Table of Contents (TOC)
using Ollama's nomic-embed-text embedding model.
"""

from .ollama_embedder import OllamaEmbedder
from .data_loader import (
    load_syllabus,
    load_book_toc,
    discover_books,
)
from .matcher import SyllabusBookMapper
from .exporter import export_to_excel, export_to_json

__all__ = [
    "OllamaEmbedder",
    "SyllabusBookMapper",
    "load_syllabus",
    "load_book_toc",
    "discover_books",
    "export_to_excel",
    "export_to_json",
]
