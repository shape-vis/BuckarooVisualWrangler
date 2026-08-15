"""Optional SBERT-style embedding similarity for open-vocabulary categorical values.

This module is intentionally isolated from multi_view_grouping.py: the heavy
dependency (sentence-transformers -> torch) is imported lazily, only when this
path is actually used, so every existing clustering run and test stays fast and
offline-safe. This is an opt-in evidence path (see EMBEDDING_STRATEGY_VALUE in
multi_view_grouping.py), not the default -- per the project's standing rule that
a representation swap needs a controlled benchmark comparison before it can
replace an established mechanism in production ranking.

Why this exists: one-hot / TF-IDF token equality treats "Back-end developer" and
"Front-end developer" as no more related than "Back-end developer" and "France" --
identical strings match, everything else is equally "different". For open-vocabulary
categorical fields (job titles, education levels, uncoded location names) that is
the wrong model. Embedding similarity lets values that mean similar things sit
close together without hand-written per-value rules for any specific dataset.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Role gate: only genuinely open-vocabulary categorical roles are eligible. Binary
# and coded categories (Yes/No, small enumerated codes) are already correctly
# modeled by exact match -- embedding "Male" vs "Female" would inject a similarity
# score that means nothing. Structured/coordinate geography is handled by its own
# spherical-distance block already; this only covers uncoded categorical text.
EMBEDDING_ELIGIBLE_ROLES = {"categorical"}

_model_cache: dict[str, Any] = {}


def _load_model(model_name: str = EMBEDDING_MODEL_NAME):
    """Lazily import and cache the sentence-transformers model as a singleton.

    Deliberately not imported at module load time: this keeps the heavy
    torch/sentence-transformers dependency out of every clustering run that
    doesn't opt into embeddings, and out of the test suite entirely (tests use
    embed_values(..., embedder=<fake>) instead of loading a real model).
    """
    if model_name not in _model_cache:
        from sentence_transformers import SentenceTransformer  # local import by design

        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


def default_embedder(values: list[str]) -> np.ndarray:
    """Encode strings to L2-normalized vectors using the cached SBERT model."""
    model = _load_model()
    return np.asarray(model.encode(values, normalize_embeddings=True), dtype=float)


def embed_unique_values(
    values: pd.Series,
    *,
    embedder: Callable[[list[str]], np.ndarray] | None = None,
) -> dict[str, np.ndarray]:
    """Embed each distinct present value once, not once per row.

    Cost scales with column cardinality, not row count -- a 10,000-row sample with
    50 distinct Country values costs 50 embeddings, not 10,000.
    """
    unique_values = sorted({str(value) for value in values.tolist() if pd.notna(value) and str(value).strip()})
    if not unique_values:
        return {}
    embed_fn = embedder or default_embedder
    vectors = embed_fn(unique_values)
    return {value: np.asarray(vector, dtype=float) for value, vector in zip(unique_values, vectors)}


def build_embedding_matrix(
    frame: pd.DataFrame,
    columns: list[str],
    profile_map: dict[str, dict],
    *,
    embedder: Callable[[list[str]], np.ndarray] | None = None,
) -> tuple[np.ndarray, list[str], dict[str, dict[str, np.ndarray]]]:
    """One dense, weighted embedding block per eligible column, concatenated.

    A row with a missing value gets an all-zero vector for that column's segment
    (contributes no signal in this dimension), not a fabricated embedding.

    Also returns the raw (unweighted) value->vector cache per column so callers
    building group descriptions later can explain *why* values were grouped --
    which values sit close together in meaning -- without re-embedding.
    """
    blocks = []
    names = []
    caches: dict[str, dict[str, np.ndarray]] = {}
    for column in columns:
        cache = embed_unique_values(frame[column], embedder=embedder)
        if not cache:
            continue
        caches[column] = cache
        dim = next(iter(cache.values())).shape[0]
        weight = max(np.finfo(float).eps, float(profile_map[column].get("confidence", 1.0)))
        block = np.zeros((len(frame), dim), dtype=float)
        for row_index, value in enumerate(frame[column].tolist()):
            if pd.isna(value):
                continue
            vector = cache.get(str(value))
            if vector is not None:
                block[row_index] = vector * weight
        blocks.append(block)
        names.extend(f"{column}:embed:{i}" for i in range(dim))
    if not blocks:
        return np.zeros((len(frame), 0), dtype=float), [], caches
    return np.hstack(blocks), names, caches


def embedding_eligible_columns(
    columns: list[str],
    frame: pd.DataFrame,
    profile_map: dict[str, dict],
    natural_break_threshold: Callable[[Any], float | None],
) -> list[str]:
    """Which categorical columns should use embeddings instead of exact-match tokens.

    Two gates, both dataset-derived, neither a hardcoded number:
    1. Role gate: only roles in EMBEDDING_ELIGIBLE_ROLES (open-vocabulary categorical).
       Binary/coded categories stay on exact match, where equality is correct.
    2. Cardinality gate: among role-eligible candidates, only the naturally
       higher-cardinality class (Otsu-style split on unique-value ratio across
       this dataset's own candidate columns) is embedded. A column with few
       distinct values has little to gain from semantic similarity and exact
       match is cheaper and just as informative there. With fewer than 3
       candidates, or no natural separation, nothing is promoted -- the
       conservative default, consistent with score_separation elsewhere.
    """
    role_eligible = [
        column for column in columns
        if profile_map.get(column, {}).get("role") in EMBEDDING_ELIGIBLE_ROLES
    ]
    if len(role_eligible) < 3:
        return []
    ratios = {}
    for column in role_eligible:
        series = frame[column]
        non_missing = series.dropna()
        if non_missing.empty:
            continue
        ratios[column] = float(non_missing.nunique()) / float(len(non_missing))
    if len(ratios) < 3:
        return []
    threshold = natural_break_threshold(ratios.values())
    if threshold is None:
        return []
    return [column for column, ratio in ratios.items() if ratio > threshold]


# Free text (unstructured prose, not a coded/enumerated category) is a separate
# eligibility path from EMBEDDING_ELIGIBLE_ROLES above -- see
# free_text_embedding_eligible_columns for why it needs a different gate.
FREE_TEXT_EMBEDDING_ROLES = {"free_text"}


def free_text_embedding_eligible_columns(
    columns: list[str],
    profile_map: dict[str, dict],
) -> list[str]:
    """Which free-text columns should use SBERT embeddings instead of TF-IDF.

    A plain role gate, not a cardinality split. embedding_eligible_columns uses
    cardinality to separate genuinely open-vocabulary categorical columns from
    small enumerated ones -- but free text is high-cardinality by construction
    (cells are typically near-unique prose), so a cardinality split carries no
    signal here; every column the profiler has already classified as free_text
    is a candidate. This is a distinct, narrower replacement of TF-IDF (opt-in,
    separately gated from the always-on categorical path -- see
    plot_routes.py's semantic_quality_free_text_embeddings strategy), not an
    addition to it: TF-IDF finds shared vocabulary, SBERT finds meaning without
    shared words, and running both for the same column would double-count it
    without a principled way to weight the two against each other.
    """
    return [
        column for column in columns
        if profile_map.get(column, {}).get("role") in FREE_TEXT_EMBEDDING_ROLES
    ]
