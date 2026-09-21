"""
Ollama Embedding Client with nomic-embed-text support, dual-encoder task prefixes,
batching, and persistent disk caching.
"""

import os
import json
import hashlib
import requests
import numpy as np
from typing import List, Optional, Dict, Any


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_CACHE_DIR = ".embeddings_cache"
DEFAULT_BATCH_SIZE = 32


class OllamaEmbedder:
    """
    Client for extracting vector embeddings from Ollama models, optimized for
    nomic-embed-text dual-encoder prefixing and disk-backed caching.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_OLLAMA_URL,
        cache_dir: Optional[str] = DEFAULT_CACHE_DIR,
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout: int = 60,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.batch_size = batch_size
        self.timeout = timeout
        self.embed_endpoint = f"{self.base_url}/api/embed"
        self.legacy_endpoint = f"{self.base_url}/api/embeddings"
        self._use_legacy = False

        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)

    def check_health(self) -> bool:
        """Verifies if the Ollama daemon is active and the model exists."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            # Check model name or model prefix (e.g. nomic-embed-text in nomic-embed-text:latest)
            matched = any(
                self.model in m or m.startswith(self.model) for m in models
            )
            return matched
        except Exception:
            return False

    def _cache_key(self, text: str, prefix: str) -> str:
        """Generate unique cache filename for a given model, prefix, and text."""
        raw = f"{self.model}:{prefix}:{text}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{digest}.json")

    def _get_from_cache(self, text: str, prefix: str) -> Optional[List[float]]:
        if not self.cache_dir:
            return None
        cache_path = self._cache_key(text, prefix)
        if os.path.isfile(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _save_to_cache(self, text: str, prefix: str, vector: List[float]) -> None:
        if not self.cache_dir:
            return
        cache_path = self._cache_key(text, prefix)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(vector, f)
        except Exception:
            pass

    def _call_embed_api(self, batch_texts: List[str]) -> List[List[float]]:
        """Calls the /api/embed batch endpoint."""
        payload = {
            "model": self.model,
            "input": batch_texts,
        }
        resp = requests.post(
            self.embed_endpoint,
            json=payload,
            timeout=self.timeout
        )
        if resp.status_code == 404:
            # Fallback to legacy endpoint if /api/embed is unsupported
            self._use_legacy = True
            return self._call_legacy_api(batch_texts)

        resp.raise_for_status()
        data = resp.json()
        return data.get("embeddings", [])

    def _call_legacy_api(self, batch_texts: List[str]) -> List[List[float]]:
        """Calls /api/embeddings sequentially for older Ollama versions."""
        results = []
        for text in batch_texts:
            payload = {
                "model": self.model,
                "prompt": text,
            }
            resp = requests.post(
                self.legacy_endpoint,
                json=payload,
                timeout=self.timeout
            )
            resp.raise_for_status()
            results.append(resp.json().get("embedding", []))
        return results

    def get_embeddings(
        self,
        texts: List[str],
        prefix: str = "",
        show_progress: bool = False,
    ) -> np.ndarray:
        """
        Retrieves vector embeddings for a list of texts, checking disk cache first.
        Prefix is prepended to each text before sending to the model (e.g. 'search_query: ').
        """
        if not texts:
            return np.empty((0, 768), dtype=np.float32)

        vectors: List[Optional[List[float]]] = [None] * len(texts)
        missing_indices = []
        missing_prompts = []

        # 1. Check Cache
        for i, text in enumerate(texts):
            cached = self._get_from_cache(text, prefix)
            if cached is not None:
                vectors[i] = cached
            else:
                missing_indices.append(i)
                prefixed_text = f"{prefix}{text}" if prefix else text
                missing_prompts.append(prefixed_text)

        # 2. Fetch missing in batches
        if missing_prompts:
            num_batches = (len(missing_prompts) + self.batch_size - 1) // self.batch_size
            for b in range(num_batches):
                start = b * self.batch_size
                end = min(start + self.batch_size, len(missing_prompts))
                batch = missing_prompts[start:end]

                if show_progress:
                    print(f"    [Embedding] Processing batch {b+1}/{num_batches} ({len(batch)} items)...")

                if self._use_legacy:
                    new_embeddings = self._call_legacy_api(batch)
                else:
                    try:
                        new_embeddings = self._call_embed_api(batch)
                    except Exception as e:
                        if not self._use_legacy:
                            # Try legacy fallback on error
                            new_embeddings = self._call_legacy_api(batch)
                        else:
                            raise e

                for batch_idx, emb in enumerate(new_embeddings):
                    orig_idx = missing_indices[start + batch_idx]
                    orig_text = texts[orig_idx]
                    vectors[orig_idx] = emb
                    self._save_to_cache(orig_text, prefix, emb)

        return np.array(vectors, dtype=np.float32)

    def embed_queries(self, queries: List[str], show_progress: bool = False) -> np.ndarray:
        """Embeds queries with 'search_query: ' prefix for nomic-embed-text."""
        prefix = "search_query: " if "nomic" in self.model.lower() else ""
        return self.get_embeddings(queries, prefix=prefix, show_progress=show_progress)

    def embed_documents(self, documents: List[str], show_progress: bool = False) -> np.ndarray:
        """Embeds document texts with 'search_document: ' prefix for nomic-embed-text."""
        prefix = "search_document: " if "nomic" in self.model.lower() else ""
        return self.get_embeddings(documents, prefix=prefix, show_progress=show_progress)
