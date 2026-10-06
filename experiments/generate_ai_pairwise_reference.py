"""Generate a blinded, reproducible AI reference for pairwise review tasks.

The reference is deliberately separate from human ratings. It preserves column
identity, uses robust within-dataset scales for numbers and datetimes, and uses
the cached all-MiniLM-L6-v2 transformer only for textual value meaning.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
import math
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_DIR = ROOT / "outputs" / "semantic_quality_clustering_benchmark_v1"
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
METHOD_VERSION = "buckaroo-column-aware-minilm-reference-v1"
MISSING_MARKERS = {"", "<missing>", "?", "nan", "none", "null", "n/a", "na"}
ID_TOKENS = {"id", "identifier", "invoice", "session", "stockcode", "iata"}
DATETIME_TOKENS = {"date", "time", "timestamp", "created", "closed", "pickup", "dropoff"}
SEMANTIC_TOKENS = {
    "type",
    "category",
    "status",
    "result",
    "country",
    "state",
    "city",
    "borough",
    "zone",
    "place",
    "name",
    "job",
    "education",
    "risk",
    "season",
    "holiday",
    "payment",
    "complaint",
    "descriptor",
    "facility",
    "visitor",
    "revenue",
}
LONG_TEXT_TOKENS = {"description", "complaint", "violation", "comment", "narrative", "text", "descriptor"}


@dataclass(frozen=True)
class FieldScore:
    field: str
    kind: str
    similarity: float
    weight: float
    left: str
    right: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AI pairwise reference judgments.")
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=64)
    return parser.parse_args()


def normalized_field(field: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(field).lower()).strip()


def field_tokens(field: str) -> set[str]:
    return set(normalized_field(field).split())


def parse_row_summary(summary: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    if pd.isna(summary):
        return values
    for part in str(summary).split(" | "):
        if "=" not in part:
            continue
        field, value = part.split("=", 1)
        field = field.strip()
        if field:
            values[field] = value.strip()
    return values


def is_missing(value: Any) -> bool:
    return str(value).strip().lower() in MISSING_MARKERS


def parse_number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if is_missing(text) or not re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def parse_datetime(value: Any) -> pd.Timestamp | None:
    if is_missing(value):
        return None
    text = str(value).strip()
    day_first = bool(re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}(?:\s+.*)?", text))
    try:
        parsed = pd.to_datetime(text, errors="raise", utc=True, dayfirst=day_first)
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed if not pd.isna(parsed) else None


def looks_datetime(field: str, values: list[str]) -> bool:
    tokens = field_tokens(field)
    if tokens & DATETIME_TOKENS:
        parsed = sum(parse_datetime(value) is not None for value in values if not is_missing(value))
        present = sum(not is_missing(value) for value in values)
        return present > 0 and parsed / present >= 0.7
    return False


def looks_identifier(field: str) -> bool:
    normalized = normalized_field(field)
    tokens = set(normalized.split())
    return (
        bool(tokens & ID_TOKENS)
        or normalized.endswith(" id")
        or normalized.endswith(" code")
        or normalized in {"order", "source row number"}
    )


def robust_scale(values: list[float], *, minimum: float) -> float:
    array = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
    if array.size < 2:
        return minimum
    q25, q75 = np.quantile(array, [0.25, 0.75])
    spread = float(np.max(array) - np.min(array))
    return max(float(q75 - q25), spread * 0.10, minimum)


def lexical_similarity(left: str, right: str) -> float:
    left_norm = re.sub(r"\s+", " ", left.lower()).strip()
    right_norm = re.sub(r"\s+", " ", right.lower()).strip()
    if left_norm == right_norm:
        return 1.0
    left_tokens = set(re.findall(r"[a-z0-9]+", left_norm))
    right_tokens = set(re.findall(r"[a-z0-9]+", right_norm))
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    return float(0.60 * jaccard + 0.40 * sequence)


def load_minilm(model_name: str):
    import torch
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
    model = AutoModel.from_pretrained(model_name, local_files_only=True)
    model.eval()
    return tokenizer, model, torch


def encode_prompts(prompts: list[str], model_name: str, batch_size: int) -> dict[str, np.ndarray]:
    if not prompts:
        return {}
    tokenizer, model, torch = load_minilm(model_name)
    unique = list(dict.fromkeys(prompts))
    vectors: list[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(unique), batch_size):
            batch = unique[start : start + batch_size]
            encoded = tokenizer(batch, padding=True, truncation=True, max_length=256, return_tensors="pt")
            hidden = model(**encoded).last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.extend(pooled.cpu().numpy())
    return dict(zip(unique, vectors, strict=True))


def text_prompt(field: str, value: str) -> str:
    value = re.sub(r"\s+", " ", str(value)).strip()
    return f"{normalized_field(field)}: {value[:300]}"


def text_similarity(field: str, left: str, right: str, embeddings: dict[str, np.ndarray]) -> float:
    if left.strip().lower() == right.strip().lower():
        return 1.0
    lexical = lexical_similarity(left, right)
    left_vector = embeddings[text_prompt(field, left)]
    right_vector = embeddings[text_prompt(field, right)]
    cosine = float(np.clip(np.dot(left_vector, right_vector), -1.0, 1.0))
    semantic = float(np.clip((cosine - 0.15) / 0.85, 0.0, 1.0))
    tokens = field_tokens(field)
    is_long_text = bool(tokens & LONG_TEXT_TOKENS) or max(len(left), len(right)) >= 45
    is_place = bool(tokens & {"country", "state", "city", "borough", "zone", "place", "name"})
    if is_long_text:
        return 0.75 * semantic + 0.25 * lexical
    if is_place:
        return 0.60 * semantic + 0.40 * lexical
    return 0.35 * semantic + 0.65 * lexical


def field_weight(field: str, kind: str) -> float:
    tokens = field_tokens(field)
    if looks_identifier(field):
        return 0.12
    if tokens & LONG_TEXT_TOKENS:
        return 1.35
    if tokens & SEMANTIC_TOKENS:
        return 1.20
    if kind == "datetime":
        return 0.55
    if kind == "numeric":
        return 0.80
    return 1.0


def ordinal_score(value: float) -> int:
    anchors = np.asarray([0.0, 0.25, 0.50, 0.75, 1.0])
    return int(np.argmin(np.abs(anchors - float(value))) + 1)


def confidence_score(
    similarity: float,
    field_scores: list[FieldScore],
    union_count: int,
) -> tuple[float, int, dict[str, float]]:
    if not field_scores or union_count <= 0:
        return 0.0, 1, {"coverage": 0.0, "field_agreement": 0.0, "boundary_margin": 0.0}
    weights = np.asarray([item.weight for item in field_scores], dtype=float)
    values = np.asarray([item.similarity for item in field_scores], dtype=float)
    mean = float(np.average(values, weights=weights))
    variance = float(np.average((values - mean) ** 2, weights=weights))
    agreement = float(np.clip(1.0 - 2.0 * math.sqrt(max(variance, 0.0)), 0.0, 1.0))
    coverage = min(1.0, len(field_scores) / union_count)
    count_support = min(1.0, len(field_scores) / 5.0)
    boundaries = np.asarray([0.125, 0.375, 0.625, 0.875])
    boundary_margin = min(1.0, float(np.min(np.abs(boundaries - similarity))) / 0.125)
    confidence = 0.35 * coverage + 0.30 * agreement + 0.20 * boundary_margin + 0.15 * count_support
    confidence = float(np.clip(confidence, 0.0, 1.0))
    return confidence, ordinal_score(confidence), {
        "coverage": coverage,
        "field_agreement": agreement,
        "boundary_margin": boundary_margin,
    }


def field_statistics(parsed_rows: list[tuple[str, dict[str, str], dict[str, str]]]):
    values: dict[tuple[str, str], list[str]] = defaultdict(list)
    for dataset_id, left, right in parsed_rows:
        for row in (left, right):
            for field, value in row.items():
                values[(dataset_id, field)].append(value)

    stats: dict[tuple[str, str], dict[str, Any]] = {}
    text_prompts: list[str] = []
    for key, field_values in values.items():
        _, field = key
        present = [value for value in field_values if not is_missing(value)]
        if looks_datetime(field, present):
            seconds = [float(parse_datetime(value).timestamp()) for value in present if parse_datetime(value) is not None]
            stats[key] = {"kind": "datetime", "scale": robust_scale(seconds, minimum=86400.0)}
            continue
        numbers = [parse_number(value) for value in present]
        numeric_values = [value for value in numbers if value is not None]
        numeric_ratio = len(numeric_values) / len(present) if present else 0.0
        if numeric_ratio >= 0.8 and not looks_identifier(field):
            stats[key] = {"kind": "numeric", "scale": robust_scale(numeric_values, minimum=1e-9)}
            continue
        stats[key] = {"kind": "text", "scale": None}
        text_prompts.extend(text_prompt(field, value) for value in present)
    return stats, text_prompts


def compare_pair(
    dataset_id: str,
    left: dict[str, str],
    right: dict[str, str],
    stats: dict[tuple[str, str], dict[str, Any]],
    embeddings: dict[str, np.ndarray],
) -> tuple[float, list[FieldScore]]:
    scores: list[FieldScore] = []
    fields = sorted(set(left) | set(right))
    for field in fields:
        left_value, right_value = left.get(field, "<missing>"), right.get(field, "<missing>")
        left_missing, right_missing = is_missing(left_value), is_missing(right_value)
        if left_missing and right_missing:
            continue
        kind = stats.get((dataset_id, field), {"kind": "text", "scale": None})["kind"]
        weight = field_weight(field, kind)
        if left_missing != right_missing:
            similarity, reason = 0.0, "present on only one side"
        elif kind == "datetime":
            left_dt, right_dt = parse_datetime(left_value), parse_datetime(right_value)
            scale = float(stats[(dataset_id, field)]["scale"])
            difference = abs(float(left_dt.timestamp()) - float(right_dt.timestamp()))
            similarity = 1.0 / (1.0 + difference / scale)
            reason = f"datetime gap {difference / 86400.0:.1f} days relative to dataset spread"
        elif kind == "numeric":
            left_number, right_number = parse_number(left_value), parse_number(right_value)
            scale = float(stats[(dataset_id, field)]["scale"])
            difference = abs(float(left_number) - float(right_number))
            similarity = 1.0 / (1.0 + difference / scale)
            reason = f"numeric gap {difference:.4g} relative to robust dataset scale"
        else:
            similarity = text_similarity(field, left_value, right_value, embeddings)
            reason = "exact/lexical plus MiniLM textual-value similarity"
        scores.append(
            FieldScore(
                field=field,
                kind=kind,
                similarity=float(np.clip(similarity, 0.0, 1.0)),
                weight=weight,
                left=left_value,
                right=right_value,
                reason=reason,
            )
        )
    if not scores:
        return 0.0, scores
    similarity = float(np.average([item.similarity for item in scores], weights=[item.weight for item in scores]))
    return float(np.clip(similarity, 0.0, 1.0)), scores


def evidence_text(items: list[FieldScore], *, supporting: bool) -> str:
    ordered = sorted(items, key=lambda item: item.similarity, reverse=supporting)
    selected = [item for item in ordered if item.similarity >= 0.62] if supporting else [item for item in ordered if item.similarity <= 0.38]
    selected = selected[:3]
    if not selected:
        return "No strong supporting field" if supporting else "No strong conflicting field"

    def short(value: str) -> str:
        rendered = re.sub(r"\s+", " ", str(value)).strip()
        return rendered if len(rendered) <= 55 else rendered[:52] + "..."

    descriptions = []
    for item in selected:
        left, right = short(item.left), short(item.right)
        if left.lower() == right.lower():
            comparison = f"both are '{left}'"
        else:
            comparison = f"'{left}' versus '{right}'"
        descriptions.append(
            f"{item.field}: {comparison} (field similarity {item.similarity:.2f}; {item.reason})"
        )
    return "; ".join(descriptions)


def build_reference(tasks: pd.DataFrame, model_name: str, batch_size: int) -> pd.DataFrame:
    parsed_rows = [
        (str(row.dataset_id), parse_row_summary(row.row_a), parse_row_summary(row.row_b))
        for row in tasks.itertuples(index=False)
    ]
    stats, prompts = field_statistics(parsed_rows)
    embeddings = encode_prompts(prompts, model_name, batch_size)
    generated_at = datetime.now(timezone.utc).isoformat()
    output: list[dict[str, Any]] = []

    for source, parsed in zip(tasks.itertuples(index=False), parsed_rows, strict=True):
        dataset_id, left, right = parsed
        continuous, fields = compare_pair(dataset_id, left, right, stats, embeddings)
        rating = ordinal_score(continuous)
        useful_group = "yes" if rating >= 4 else "no" if rating <= 2 else "unsure"
        union_count = len(set(left) | set(right))
        confidence_continuous, confidence_rating, confidence_parts = confidence_score(
            continuous,
            fields,
            union_count,
        )
        supports = evidence_text(fields, supporting=True)
        conflicts = evidence_text(fields, supporting=False)
        similarity_meanings = {
            1: "The rows have little shared semantic evidence after identifiers are down-weighted.",
            2: "A few fields overlap, but important semantic or measurement conflicts dominate.",
            3: "The evidence is mixed: some fields support one group while others separate the rows.",
            4: "Most important fields describe the same broad kind of case, with limited conflicts.",
            5: "The important fields strongly agree and the rows describe the same meaningful case type.",
        }
        similarity_reason = (
            f"{similarity_meanings[rating]} Supporting evidence: {supports}. "
            f"Conflicting evidence: {conflicts}. Continuous column-aware score: {continuous:.3f}."
        )
        group_reason = {
            "yes": f"The {rating}/5 semantic rating is strong enough to make one user-facing group defensible; {supports}.",
            "no": f"The {rating}/5 semantic rating indicates that combining these rows would hide meaningful differences; {conflicts}.",
            "unsure": f"The {rating}/5 rating is intentionally treated as uncertain because support and conflict coexist; {supports}; {conflicts}.",
        }[useful_group]
        matching_reason = (
            "Supporting fields are the largest positive column-level contributions and conflicting fields are the smallest. "
            "Identifier-like fields are deliberately down-weighted so matching IDs cannot manufacture semantic similarity."
        )
        confidence_reason = (
            f"Confidence is {confidence_rating}/5 because {len(fields)} of {union_count} visible fields were comparable "
            f"(coverage {confidence_parts['coverage']:.2f}), field-level evidence agreement was "
            f"{confidence_parts['field_agreement']:.2f}, and distance from the nearest rating boundary was "
            f"{confidence_parts['boundary_margin']:.2f}. "
            + (
                "In plain language, most available fields point in the same direction and the rating is not close to changing."
                if confidence_rating >= 4
                else "In plain language, the available fields are partly mixed or the score is close to a neighboring rating, so this judgment deserves human checking."
                if confidence_rating == 3
                else "In plain language, too little evidence agrees strongly, so the AI judgment should be treated cautiously."
            )
        )
        note = (
            f"Column-aware AI reference score {continuous:.3f}. Supports: {supports}. "
            f"Conflicts: {conflicts}. Compared {len(fields)} of {len(set(left) | set(right))} visible fields. "
            "MiniLM is used only for textual values; numeric and datetime evidence uses dataset-relative robust scales. "
            "This is a comparison baseline, not human ground truth or an adjudication decision."
        )
        output.append(
            {
                "task_id": source.task_id,
                "dataset_id": source.dataset_id,
                "partition": source.partition,
                "AI_semantic_similarity_1_to_5": rating,
                "AI_semantic_similarity_reason": similarity_reason,
                "AI_similarity_continuous_0_to_1": round(continuous, 6),
                "AI_same_useful_group": useful_group,
                "AI_same_useful_group_reason": group_reason,
                "AI_supporting_fields": supports,
                "AI_conflicting_fields": conflicts,
                "AI_important_matching_or_conflicting_fields": f"Supports: {supports} | Conflicts: {conflicts}",
                "AI_matching_conflicting_reason": matching_reason,
                "AI_confidence_1_to_5": confidence_rating,
                "AI_confidence_reason": confidence_reason,
                "AI_confidence_continuous_0_to_1": round(confidence_continuous, 6),
                "AI_model_id": model_name,
                "AI_method_version": METHOD_VERSION,
                "AI_review_status": "complete",
                "AI_notes": note,
                "AI_generated_at_utc": generated_at,
            }
        )
    return pd.DataFrame(output)


def main() -> None:
    args = parse_args()
    benchmark_dir = args.benchmark_dir.resolve()
    tasks_path = benchmark_dir / "human_review" / "pairwise_review_tasks_BLINDED.csv"
    output_path = benchmark_dir / "human_review" / "pairwise_ai_reference.csv"
    tasks = pd.read_csv(tasks_path)
    reference = build_reference(tasks, str(args.model), int(args.batch_size))
    if len(reference) != len(tasks) or reference["task_id"].duplicated().any():
        raise ValueError("AI reference must contain exactly one row per blinded pairwise task")
    if set(reference["task_id"]) != set(tasks["task_id"]):
        raise ValueError("AI reference task IDs do not match the blinded human task file")
    reference.to_csv(output_path, index=False)
    print(
        reference.groupby(["dataset_id", "AI_semantic_similarity_1_to_5"])
        .size()
        .unstack(fill_value=0)
        .to_string()
    )
    print(f"Wrote {len(reference)} AI reference judgments to {output_path}")


if __name__ == "__main__":
    main()
