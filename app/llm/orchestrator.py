"""LLM orchestration: build table context, prompt the model, materialize proposals.

Design notes:
- This module never talks to the DB directly. It calls DBOperations (the same
  surface the existing API routes use) so the LLM's view of the data matches
  what a human user gets through the app.
- `build_table_context` is the pluggable seam: today it sends schema + per-column
  summary + error counts + a small sample of error-flagged rows. To switch to
  full-CSV mode later, replace this function — nothing else needs to change.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import text

from app import db_operations, engine
from app.llm.client import LLMClient, get_default_client
from app.llm.prompts import PROPOSAL_SCHEMA, SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT, build_user_prompt


import os

# Inline up to N error-flagged rows in the prompt. Set OLLAMA_SAMPLE_ROWS=0 to
# disable entirely (fastest); higher values give the model more grounding at
# the cost of latency.
SAMPLE_ROWS = int(os.environ.get("OLLAMA_SAMPLE_ROWS", "0"))


def build_table_context(table_name: str) -> dict[str, Any]:
    """Build the compact JSON view of `table_name` the LLM will see.

    Returns: { table, schema, row_count, column_summaries, error_counts, sample_rows }
    """
    with engine.connect() as conn:
        df = pd.read_sql_query(text(f'SELECT * FROM "{table_name}" LIMIT 1000'), conn)
        try:
            err_df = pd.read_sql_query(
                text(f'SELECT row_id, column_id, error_type FROM "errors_{table_name}"'),
                conn,
            )
        except Exception:
            err_df = pd.DataFrame(columns=["row_id", "column_id", "error_type"])

    schema = {c: str(df[c].dtype) for c in df.columns}

    column_summaries: dict[str, Any] = {}
    for c in df.columns:
        col = df[c]
        summary: dict[str, Any] = {"dtype": str(col.dtype), "null_count": int(col.isna().sum())}
        if pd.api.types.is_numeric_dtype(col):
            summary.update({
                "min": _safe(col.min()),
                "max": _safe(col.max()),
                "mean": _safe(col.mean()),
            })
        else:
            top = col.value_counts(dropna=True).head(5).to_dict()
            summary["top_values"] = {str(k): int(v) for k, v in top.items()}
        column_summaries[c] = summary

    error_counts: dict[str, dict[str, int]] = {}
    if not err_df.empty:
        grouped = err_df.groupby(["column_id", "error_type"]).size().reset_index(name="n")
        for _, row in grouped.iterrows():
            error_counts.setdefault(str(row["column_id"]), {})[str(row["error_type"])] = int(row["n"])

    sample_rows: list[dict[str, Any]] = []
    if SAMPLE_ROWS > 0 and not err_df.empty:
        error_row_ids = err_df["row_id"].drop_duplicates().head(SAMPLE_ROWS).tolist()
        sample = df[df["index"].isin(error_row_ids)] if "index" in df.columns else df.head(SAMPLE_ROWS)
        sample_rows = sample.head(SAMPLE_ROWS).to_dict(orient="records")

    return {
        "table": table_name,
        "row_count": int(db_operations.get_row_count(table_name)),
        "schema": schema,
        "column_summaries": column_summaries,
        "error_counts": error_counts,
        "sample_error_rows": sample_rows,
    }


def _safe(v):
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return v.item() if hasattr(v, "item") else v


def _enumerate_candidates(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """One impute + one delete per dirty column. error_type is intentionally
    omitted from params — the materialize step pulls every error row_id in the
    column regardless of type, since the wrangle target is "the dirty rows."
    """
    cands: list[dict[str, Any]] = []
    for col, by_type in ctx.get("error_counts", {}).items():
        total = sum(int(c) for c in by_type.values())
        if total <= 0:
            continue
        for op in ("impute-rows", "delete-rows"):
            cands.append({
                "op": op,
                "params": {"column": col},
                "error_count": total,
                "error_types": sorted(by_type.keys()),
            })
    return cands


def analyze(table_name: str, client: LLMClient | None = None) -> list[dict[str, Any]]:
    """Hybrid candidate generation.

    1. Enumerate candidates deterministically from the error counts — guarantees
       every dirty column gets an option.
    2. Ask the LLM to (a) pick the better of impute vs delete per column,
       (b) write a short rationale, (c) order by priority. If the LLM fails,
       fall back to the raw candidate list with a generic rationale.
    """
    ctx = build_table_context(table_name)
    candidates = _enumerate_candidates(ctx)
    if not candidates:
        return []

    client = client or get_default_client()
    try:
        out = client.chat_json(
            system=SYSTEM_PROMPT,
            user=build_user_prompt({"table_context": ctx, "candidates": candidates}),
        )
        proposals = out.get("proposals", [])
    except Exception as e:
        print(f"[llm] analyze fallback (LLM failed: {e})")
        proposals = [
            {
                **c,
                "rationale": f"{c['error_count']} dirty rows in {c['params']['column']}",
                "predicted_table_name": f"{c['op'].split('-')[0]}_{c['params']['column']}",
            }
            for c in candidates
        ]

    # Backstop: every (column, error_type, op) candidate must appear. If the LLM
    # dropped any, re-add them with a generic rationale so the UI always offers
    # both impute and delete for every dirty column.
    def _key(p):
        return (p.get("params", {}).get("column"), p.get("op"))

    seen = {_key(p) for p in proposals}
    for c in candidates:
        if _key(c) not in seen:
            col = c["params"]["column"]
            proposals.append({
                **c,
                "rationale": f"{c['error_count']} dirty rows in {col}",
                "predicted_table_name": f"{c['op'].split('-')[0]}_{col}",
            })
            seen.add(_key(c))

    for i, p in enumerate(proposals):
        p["id"] = f"prop_{i}"
    return proposals


def propose_plans(table_name: str, client: LLMClient | None = None) -> list[dict[str, Any]]:
    """Ask the LLM for multi-step wrangle plans. Pure LLM call — no deterministic
    enumeration. Returns [] if the model can't produce a clean structured list.
    """
    ctx = build_table_context(table_name)
    if not ctx.get("error_counts"):
        return []
    client = client or get_default_client()
    try:
        out = client.chat_json(
            system=PLAN_SYSTEM_PROMPT,
            user=build_user_prompt(ctx),
        )
        plans = out.get("plans", []) or []
    except Exception as e:
        print(f"[llm] propose_plans failed: {e}")
        return []
    valid_cols = set(ctx.get("schema", {}).keys())
    cleaned: list[dict[str, Any]] = []
    for i, plan in enumerate(plans):
        steps = plan.get("steps") or []
        good_steps = []
        for s in steps:
            op = s.get("op")
            params = s.get("params") or {}
            col = params.get("column")
            if op in ("delete-column", "delete-rows", "impute-rows") and col in valid_cols:
                good_steps.append({"op": op, "params": {"column": col}, "name": s.get("name") or op})
        if 2 <= len(good_steps) <= 5:
            cleaned.append({
                "id": f"plan_{i}",
                "name": plan.get("name") or f"Plan {i + 1}",
                "rationale": plan.get("rationale") or "",
                "steps": good_steps,
            })
    return cleaned


def _resolve_row_ids(node_table: str, column: str, error_type: str | None) -> list[int]:
    """Look up row_ids in errors_<table> matching column (+ optional error_type)."""
    sql = f'SELECT DISTINCT row_id FROM "errors_{node_table}" WHERE column_id = :col'
    params: dict[str, Any] = {"col": column}
    if error_type:
        sql += " AND error_type = :etype"
        params["etype"] = error_type
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [int(r[0]) for r in rows]


def _compute_deltas(source_table: str, preview_table: str) -> list[dict[str, Any]]:
    """Per-column error count deltas between two tables' errors_<...> companions."""
    with engine.connect() as conn:
        before = pd.read_sql_query(
            text(f'SELECT column_id, COUNT(DISTINCT row_id) AS n FROM "errors_{source_table}" GROUP BY column_id'),
            conn,
        )
        after = pd.read_sql_query(
            text(f'SELECT column_id, COUNT(DISTINCT row_id) AS n FROM "errors_{preview_table}" GROUP BY column_id'),
            conn,
        )
    bmap = dict(zip(before["column_id"], before["n"].astype(int)))
    amap = dict(zip(after["column_id"], after["n"].astype(int)))
    out = []
    for c in sorted(set(bmap) | set(amap)):
        b = int(bmap.get(c, 0))
        a = int(amap.get(c, 0))
        pct = None if b == 0 else round((a - b) / b * 100, 1)
        out.append({"column": c, "errors_before": b, "errors_after": a, "pct_change": pct})
    return out


def preview_plan(node_table: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Build a chain of preview tables (NOT committed) and return per-step
    deltas. delete-column steps are reported but not chained — they break
    the preview chain since they're in-place.
    Note: preview tables linger in the DB; cleanup happens on next commit.
    """
    from app.server_utils.service_helpers import create_previews_1d, _safe_pg_name
    from app.routes.wrangler_routes_sql import update_errors_table

    steps = plan.get("steps") or []
    current = node_table
    out_steps: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        op = step.get("op")
        col = step.get("params", {}).get("column")
        if op == "delete-column":
            out_steps.append({
                "step": i, "op": op, "name": step.get("name") or op,
                "column": col, "source_table": current, "preview_table": None,
                "deltas": [], "note": "delete-column previews not supported; chain stops here",
            })
            break
        if op not in ("delete-rows", "impute-rows"):
            out_steps.append({"step": i, "op": op, "name": step.get("name") or op, "skipped": True})
            continue
        db_operations.load_table(current, f"errors_{current}")
        row_ids = _resolve_row_ids(current, col, None)
        if not row_ids:
            out_steps.append({
                "step": i, "op": op, "name": step.get("name") or op,
                "column": col, "source_table": current, "preview_table": None,
                "deltas": [], "note": "no dirty rows at this step",
            })
            continue
        previews = create_previews_1d(current, row_ids, [col], _safe_pg_name, update_errors_table)
        preview_table = previews["preview_delete"] if op == "delete-rows" else previews["preview_impute"]
        deltas = _compute_deltas(current, preview_table)
        out_steps.append({
            "step": i, "op": op, "name": step.get("name") or op,
            "column": col, "source_table": current, "preview_table": preview_table,
            "deltas": deltas,
        })
        current = preview_table
    return {"steps": out_steps}


def preview(node_table: str, proposal: dict[str, Any]) -> dict[str, Any]:
    """Build preview tables for a proposal *without* committing them.

    Returns:
      {
        preview_table: <name>,
        affected_column: <col>,
        deltas: [{column, errors_before, errors_after, pct_change}, ...]
      }
    """
    from app.server_utils.service_helpers import create_previews_1d, _safe_pg_name
    from app.routes.wrangler_routes_sql import update_errors_table

    op = proposal.get("op")
    params = proposal.get("params", {})
    if op not in ("delete-rows", "impute-rows"):
        raise ValueError(f"preview only supports 1D ops (got {op})")
    col = params["column"]

    db_operations.load_table(node_table, f"errors_{node_table}")
    row_ids = params.get("row_ids") or _resolve_row_ids(node_table, col, params.get("error_type"))
    if not row_ids:
        raise ValueError(f"{op} on column '{col}' resolved to zero rows")
    previews = create_previews_1d(node_table, row_ids, [col], _safe_pg_name, update_errors_table)
    preview_table = previews["preview_delete"] if op == "delete-rows" else previews["preview_impute"]
    return {
        "preview_table": preview_table,
        "affected_column": col,
        "deltas": _compute_deltas(node_table, preview_table),
    }


def materialize(node_table: str, proposal: dict[str, Any]) -> dict[str, Any]:
    """Run a single proposal through the existing preview + execute pipeline.

    Returns: { table: <new_node_table_name> } on success.
    For delete-column (in-place, no new node) the returned table is the same.
    """
    from app.db_utils import query
    from app.server_utils.service_helpers import (
        create_previews_1d,
        create_previews_2d,
        execute_wrangle_preview,
        _safe_pg_name,
    )
    from app.routes.wrangler_routes_sql import update_errors_table

    op = proposal.get("op")
    params = proposal.get("params", {})

    # Make the proposal's source node the current main table so the wrangle
    # branches from it (mirrors what /api/setGraphToClickedNode does).
    db_operations.load_table(node_table, f"errors_{node_table}")

    if op in ("delete-rows", "impute-rows"):
        col = params["column"]
        # Prefer explicit row_ids if the model gave them; otherwise resolve from errors table.
        row_ids = params.get("row_ids") or _resolve_row_ids(node_table, col, params.get("error_type"))
        if not row_ids:
            raise ValueError(f"{op} on column '{col}' resolved to zero rows")
        previews = create_previews_1d(node_table, row_ids, [col], _safe_pg_name, update_errors_table)
        chosen = previews["preview_delete"] if op == "delete-rows" else previews["preview_impute"]
        result = execute_wrangle_preview(node_table, chosen, _safe_pg_name, db_operations)
        return {"table": result.get("table")}

    if op in ("2d-delete", "2d-impute-x", "2d-impute-y"):
        cols = params["columns"]
        if len(cols) != 2:
            raise ValueError(f"{op} requires columns=[a,b]")
        # Union of error row_ids across both columns (no error_type filter for 2D)
        row_ids = params.get("row_ids")
        if not row_ids:
            ids_a = set(_resolve_row_ids(node_table, cols[0], params.get("error_type")))
            ids_b = set(_resolve_row_ids(node_table, cols[1], params.get("error_type")))
            row_ids = sorted(ids_a | ids_b)
        if not row_ids:
            raise ValueError(f"{op} on columns {cols} resolved to zero rows")
        previews = create_previews_2d(node_table, row_ids, cols, _safe_pg_name, update_errors_table)
        chosen = {
            "2d-delete":   previews["preview_delete"],
            "2d-impute-x": previews["preview_impute_x"],
            "2d-impute-y": previews["preview_impute_y"],
        }[op]
        result = execute_wrangle_preview(node_table, chosen, _safe_pg_name, db_operations)
        return {"table": result.get("table")}

    if op == "delete-column":
        col = params["column"]
        # delete-column is in-place — no new pgraph node, same table name.
        query.delete_column(table=node_table, column=col)
        update_errors_table(node_table)
        return {"table": node_table, "in_place": True}

    raise ValueError(f"unknown op: {op}")


def materialize_plan(node_table: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Run every step in plan.steps sequentially, chaining each new node into
    the next step. Returns the chain of new tables produced (one per step).

    delete-column steps are in-place (no new node) and do NOT advance the
    chain head.
    """
    steps = plan.get("steps") or []
    if not steps:
        raise ValueError("plan has no steps")
    current = node_table
    chain: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        try:
            result = materialize(current, step)
        except Exception as e:
            return {"chain": chain, "stopped_at": i, "error": str(e)}
        chain.append({"step": i, "op": step.get("op"), "table": result.get("table"), "in_place": result.get("in_place", False)})
        if not result.get("in_place"):
            current = result["table"]
    return {"chain": chain, "final_table": current}
