"""
Semantic Matcher Engine for Syllabus-to-TOC Real Chapter Alignment.
Embeds syllabus topics and real textbook chapters using Ollama nomic-embed-text,
mapping topics directly to authoritative chapters and true multi-page spans.
"""

from typing import List, Dict, Optional, Union, Any
import numpy as np
import pandas as pd

from .ollama_embedder import OllamaEmbedder, DEFAULT_MODEL
from .data_loader import clean_text


class SyllabusBookMapper:
    """
    Orchestrates semantic alignment between syllabus topics and a textbook's real chapters and TOC.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = "http://localhost:11434",
        cache_dir: Optional[str] = ".embeddings_cache",
        batch_size: int = 32,
    ):
        self.embedder = OllamaEmbedder(
            model=model,
            base_url=base_url,
            cache_dir=cache_dir,
            batch_size=batch_size,
        )

    def _normalize_vectors(self, matrix: np.ndarray) -> np.ndarray:
        """L2 normalizes embedding matrix for fast cosine similarity dot product."""
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1e-12
        return matrix / norms

    def map_syllabus_to_toc(
        self,
        syllabus_df: pd.DataFrame,
        toc_df: pd.DataFrame,
        top_k: int = 1,
        threshold: float = 0.40,
        show_progress: bool = True,
    ) -> pd.DataFrame:
        """
        Maps syllabus topics to real chapters in the book TOC.

        Args:
            syllabus_df: DataFrame of extracted syllabus topics.
            toc_df: Structured TOC DataFrame from load_book_toc.
            top_k: Maximum candidate chapters per syllabus item (default: 1).
            threshold: Minimum similarity score threshold.
            show_progress: Print progress logs.

        Returns:
            pd.DataFrame: Table containing Topic, Real Chapter, and True Page Range.
        """
        if syllabus_df.empty or toc_df.empty:
            return pd.DataFrame()

        if show_progress:
            print(f"--> Preparing {len(syllabus_df)} syllabus query embeddings...")

        # 1. Embed syllabus queries
        query_texts = syllabus_df["query_text"].tolist()
        q_embeddings = self.embedder.embed_queries(query_texts, show_progress=show_progress)
        q_norm = self._normalize_vectors(q_embeddings)

        # 2. Embed TOC chapters
        if show_progress:
            print(f"--> Preparing {len(toc_df)} chapter/TOC embeddings...")
        doc_texts = toc_df["doc_text"].tolist()
        d_embeddings = self.embedder.embed_documents(doc_texts, show_progress=show_progress)
        d_norm = self._normalize_vectors(d_embeddings)

        # 3. Compute cosine similarity matrix
        sim_matrix = q_norm @ d_norm.T  # shape: [num_queries, num_toc_entries]

        results = []

        for q_idx in range(len(syllabus_df)):
            s_row = syllabus_df.iloc[q_idx]
            sims = sim_matrix[q_idx]

            candidate_indices = np.argsort(sims)[::-1]
            emitted = 0
            best_cand_idx = candidate_indices[0] if len(candidate_indices) > 0 else None

            for d_idx in candidate_indices:
                score = float(sims[d_idx])
                if score < threshold and emitted > 0:
                    break

                t_row = toc_df.iloc[d_idx]

                if score >= 0.70:
                    confidence = "High"
                elif score >= 0.55:
                    confidence = "Medium"
                elif score >= threshold:
                    confidence = "Low"
                else:
                    confidence = "Below Threshold"

                emitted += 1

                results.append({
                    "syllabus_id": s_row.get("id", f"TOPIC_{q_idx+1}"),
                    "subject_code": clean_text(s_row.get("subject_code", "")),
                    "subject_name": clean_text(s_row.get("subject_name", "")),
                    "module_no": clean_text(s_row.get("module_no", "")),
                    "module_title": clean_text(s_row.get("module_title", "")),
                    "syllabus_topic": clean_text(s_row.get("topic", "")),
                    "syllabus_subtopic": clean_text(s_row.get("sub_topic", "")),
                    "match_rank": emitted,
                    "similarity_score": round(score, 4),
                    "confidence": confidence,
                    "book_stem": clean_text(t_row.get("book_stem", "")),
                    "main_chapter": clean_text(t_row.get("main_chapter", "")),
                    "chapter_page_range": clean_text(t_row.get("chapter_page_range", "")),
                    "chapter_start_page": t_row.get("chapter_start_page", ""),
                    "chapter_end_page": t_row.get("chapter_end_page", ""),
                    "matched_toc_subtopic": clean_text(t_row.get("toc_topic", "")),
                    "toc_level": clean_text(t_row.get("toc_level", "")),
                    "extract_page_range": clean_text(t_row.get("extract_page_range", "")),
                    "extract_start_page": t_row.get("extract_start_page", ""),
                    "extract_end_page": t_row.get("extract_end_page", ""),
                })

                if emitted >= top_k:
                    break

            if emitted == 0 and best_cand_idx is not None:
                score = float(sims[best_cand_idx])
                t_row = toc_df.iloc[best_cand_idx]
                results.append({
                    "syllabus_id": s_row.get("id", f"TOPIC_{q_idx+1}"),
                    "subject_code": clean_text(s_row.get("subject_code", "")),
                    "subject_name": clean_text(s_row.get("subject_name", "")),
                    "module_no": clean_text(s_row.get("module_no", "")),
                    "module_title": clean_text(s_row.get("module_title", "")),
                    "syllabus_topic": clean_text(s_row.get("topic", "")),
                    "syllabus_subtopic": clean_text(s_row.get("sub_topic", "")),
                    "match_rank": 1,
                    "similarity_score": round(score, 4),
                    "confidence": "Below Threshold",
                    "book_stem": clean_text(t_row.get("book_stem", "")),
                    "main_chapter": clean_text(t_row.get("main_chapter", "")),
                    "chapter_page_range": clean_text(t_row.get("chapter_page_range", "")),
                    "chapter_start_page": t_row.get("chapter_start_page", ""),
                    "chapter_end_page": t_row.get("chapter_end_page", ""),
                    "matched_toc_subtopic": clean_text(t_row.get("toc_topic", "")),
                    "toc_level": clean_text(t_row.get("toc_level", "")),
                    "extract_page_range": clean_text(t_row.get("extract_page_range", "")),
                    "extract_start_page": t_row.get("extract_start_page", ""),
                    "extract_end_page": t_row.get("extract_end_page", ""),
                })

        return pd.DataFrame(results)
