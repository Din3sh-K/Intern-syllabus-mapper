"""
textbook_extractor package
Provides batch PDF extraction, scanned PDF detection, and font-based section hierarchy modeling.
"""

from .batch_pdf_pipeline import process_batch

__all__ = ["process_batch"]
