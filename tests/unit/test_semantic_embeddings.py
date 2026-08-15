import numpy as np
import pandas as pd

from app.server_utils.adaptive_grouping_policy import natural_break_threshold
from app.server_utils.semantic_embeddings import (
    build_embedding_matrix,
    embed_unique_values,
    embedding_eligible_columns,
    free_text_embedding_eligible_columns,
)


def profile(role, confidence=0.9):
    return {"role": role, "confidence": confidence}


def fake_embedder_factory():
    """A deterministic, offline stand-in for the real SBERT model.

    Records every call so tests can assert the cache-per-unique-value contract
    without downloading or running a real ~80MB model.
    """
    calls = []

    def embedder(values):
        calls.append(list(values))
        # Two orthogonal directions: "developer"-ish strings vs everything else,
        # enough to prove the matrix-building plumbing without needing real
        # semantic quality (that's validated separately, offline, against the
        # live model -- see the session's manual verification).
        vectors = []
        for value in values:
            if "developer" in value.lower():
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return np.asarray(vectors, dtype=float)

    embedder.calls = calls
    return embedder


def test_embedding_eligible_columns_requires_role_and_cardinality_gate():
    frame = pd.DataFrame({
        "job_title": ["Back-end developer", "Front-end developer", "Full-stack developer", "QA engineer"] * 10,
        "country": ["USA", "India", "Germany", "Brazil"] * 10,
        "gender": ["Male", "Female"] * 20,
        "status_code": ["A", "B"] * 20,
    })
    profile_map = {
        "job_title": profile("categorical"),
        "country": profile("categorical"),
        "gender": profile("binary_category"),
        "status_code": profile("numeric_code_category"),
    }
    columns = list(profile_map)

    eligible = embedding_eligible_columns(columns, frame, profile_map, natural_break_threshold)

    # Binary/coded categories never qualify, regardless of cardinality -- equality
    # is the correct model there, and embedding "Male" vs "Female" adds noise.
    assert "gender" not in eligible
    assert "status_code" not in eligible
    # With only two role-eligible candidates (job_title, country), the >= 3
    # candidate floor means nothing is promoted -- the conservative default.
    assert eligible == []


def test_embedding_eligible_columns_promotes_the_higher_cardinality_class():
    frame = pd.DataFrame({
        "job_title": [f"Job {i}" for i in range(40)],  # 40/40 unique -> high cardinality
        "country": [f"Country {i}" for i in range(35)] + ["Country 0"] * 5,  # 35/40 unique
        "education": [f"Level {i}" for i in range(30)] + ["Level 0"] * 10,  # 30/40 unique
        "small_set": (["A", "B", "C"] * 14)[:40],  # 3/40 unique -- clearly low cardinality
    })
    profile_map = {col: profile("categorical") for col in frame.columns}
    columns = list(profile_map)

    eligible = embedding_eligible_columns(columns, frame, profile_map, natural_break_threshold)

    assert "small_set" not in eligible
    assert "job_title" in eligible


def test_free_text_embedding_eligible_columns_is_a_plain_role_gate():
    # Unlike embedding_eligible_columns, this is not a cardinality split -- free
    # text is high-cardinality by construction, so a cardinality gate would carry
    # no signal. Every free_text-role column is eligible; nothing else is, no
    # matter how it looks statistically.
    profile_map = {
        "complaint_narrative": profile("free_text"),
        "company_response": profile("free_text"),
        "job_title": profile("categorical"),
        "gender": profile("binary_category"),
    }
    columns = list(profile_map)

    eligible = free_text_embedding_eligible_columns(columns, profile_map)

    assert set(eligible) == {"complaint_narrative", "company_response"}
    # No 3-candidate floor here (unlike the categorical path) -- a single
    # free_text column is still a legitimate TF-IDF-vs-SBERT swap candidate.
    assert free_text_embedding_eligible_columns(
        ["complaint_narrative"], {"complaint_narrative": profile("free_text")},
    ) == ["complaint_narrative"]


def test_embed_unique_values_caches_per_unique_value_not_per_row():
    series = pd.Series(["Back-end developer"] * 50 + ["Front-end developer"] * 50)
    embedder = fake_embedder_factory()

    cache = embed_unique_values(series, embedder=embedder)

    assert set(cache.keys()) == {"Back-end developer", "Front-end developer"}
    # The embedder must be called once, with exactly the 2 unique values -- not
    # once per row (100 rows would be a real cost blowup on any nontrivial column).
    assert len(embedder.calls) == 1
    assert sorted(embedder.calls[0]) == ["Back-end developer", "Front-end developer"]


def test_build_embedding_matrix_gives_missing_values_a_zero_vector():
    frame = pd.DataFrame({
        "job_title": ["Back-end developer", None, "Front-end developer"],
    })
    profile_map = {"job_title": profile("categorical", confidence=1.0)}
    embedder = fake_embedder_factory()

    matrix, names, caches = build_embedding_matrix(frame, ["job_title"], profile_map, embedder=embedder)

    assert matrix.shape == (3, 2)
    assert names == ["job_title:embed:0", "job_title:embed:1"]
    assert set(caches["job_title"].keys()) == {"Back-end developer", "Front-end developer"}
    # Missing row gets no fabricated signal, not an interpolated/default embedding.
    assert np.array_equal(matrix[1], np.zeros(2))
    assert not np.array_equal(matrix[0], np.zeros(2))


def test_build_embedding_matrix_weights_by_profile_confidence():
    frame = pd.DataFrame({"job_title": ["Back-end developer", "Front-end developer"]})
    embedder = fake_embedder_factory()

    full_weight, _, _ = build_embedding_matrix(
        frame, ["job_title"], {"job_title": profile("categorical", confidence=1.0)}, embedder=embedder,
    )
    half_weight, _, _ = build_embedding_matrix(
        frame, ["job_title"], {"job_title": profile("categorical", confidence=0.5)}, embedder=embedder,
    )

    assert np.allclose(half_weight, full_weight * 0.5)
