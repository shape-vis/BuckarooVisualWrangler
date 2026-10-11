"""
A saved node comparison - October 11, 2026

The compare panel is driven by one plain record of its settings: which two nodes, what is plotted and
how it is viewed. Saving keeps that record on the session's graph so it can later be pinned to a node.

Only the settings are kept, never the plotted numbers. Node tables never change once they are made, so
asking for the plot again from the same settings draws the same plot - and a settings record is a few
hundred bytes where a plot's bins or flows can run to hundreds of kilobytes. The records live on the
PGraph rather than in a table of their own because the graph itself lives only in memory: a comparison
pinned to a node could not outlive the node anyway.

from_json is the one way in, and checks everything a client sends, since the record is later handed
back to whoever opens it.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.pgraph.compare import PLOT_KINDS

COMPARISON_VERSION = 1

KINDS = (*PLOT_KINDS, "drift")
VIEWS = ("side", "overlay", "difference", "ridgeline", "flows")
MEASURES = ("items", "errors", "missing", "mismatch", "anomaly", "incomplete")
REFERENCES = ("root", "ancestor")
RANKINGS = ("error", "drift")
ERROR_DELTAS = ("ab", "rootA", "rootB")

# A record is settings, so anything past these is a malformed or hostile request rather than a real one
MAX_CATEGORIES = 500
MAX_NAME_LENGTH = 256


class ComparisonError(ValueError):
    """A comparison record that cannot be stored as sent."""


def _node(body, key, pgraph):
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise ComparisonError(f"missing {key}")
    if value not in pgraph.node_map:
        raise ComparisonError(f"{value} is not a node in this graph")
    return value


def _choice(body, key, options, default):
    value = body.get(key, default)
    if value not in options:
        raise ComparisonError(f"unknown {key} {value!r}")
    return value


def _name(body, key, required=True):
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_NAME_LENGTH:
        raise ComparisonError(f"{key} must be a column name")
    return value


def _names(body, key, nullable=False):
    value = body.get(key)
    if value is None:
        if nullable:
            return None
        return []
    if not isinstance(value, list) or len(value) > MAX_CATEGORIES:
        raise ComparisonError(f"{key} must be a list of at most {MAX_CATEGORIES} categories")
    if not all(isinstance(name, str) and len(name) <= MAX_NAME_LENGTH for name in value):
        raise ComparisonError(f"{key} must hold category names")
    return list(value)


def _zoom(body):
    value = body.get("zoom")
    if value is None:
        return None
    if (not isinstance(value, list) or len(value) != 2
            or not all(isinstance(end, (int, float)) and not isinstance(end, bool) and math.isfinite(end)
                       for end in value)):
        raise ComparisonError("zoom must be two numbers")
    return [float(value[0]), float(value[1])]


@dataclass
class Comparison:
    anchor: str
    a: str
    b: str
    kind: str
    x: str
    y: str | None
    view: str
    measure: str
    reference: str
    hidden: list = field(default_factory=list)
    kept: list | None = None
    rank_by: str = "error"
    error_delta: str = "ab"
    zoom: list | None = None
    id: str | None = None
    created_at: str | None = None

    @classmethod
    def from_json(cls, body, pgraph):
        """
        Build a comparison from what the client sent, refusing anything the panel could not have made.

        Unknown keys are dropped. The id and created_at are the server's to set, so whatever the body
        says about them is ignored.

        :param body: the record as the client sent it - see the shape in ui/src/utils/comparisonSpec.js
        :param pgraph: the session's graph, which every node named must belong to
        :raises ComparisonError: naming the first thing wrong with the record
        """
        if not isinstance(body, dict):
            raise ComparisonError("a comparison must be an object")
        if body.get("version", COMPARISON_VERSION) != COMPARISON_VERSION:
            raise ComparisonError(f"unsupported comparison version {body.get('version')!r}")

        a = _node(body, "a", pgraph)
        b = _node(body, "b", pgraph)
        # Pinned to the current node unless told otherwise - the selection the user was looking at
        anchor = _node(body, "anchor", pgraph) if body.get("anchor") is not None else b
        kind = _choice(body, "kind", KINDS, "histogram")

        return cls(
            anchor=anchor,
            a=a,
            b=b,
            kind=kind,
            x=_name(body, "x"),
            # Only a heatmap has a second axis; anything else keeps none, whatever was sent
            y=_name(body, "y") if kind == "heatmap" else None,
            view=_choice(body, "view", VIEWS, "side"),
            measure=_choice(body, "measure", MEASURES, "items"),
            reference=_choice(body, "reference", REFERENCES, "root"),
            hidden=_names(body, "hidden"),
            kept=_names(body, "kept", nullable=True),
            rank_by=_choice(body, "rankBy", RANKINGS, "error"),
            error_delta=_choice(body, "errorDelta", ERROR_DELTAS, "ab"),
            zoom=_zoom(body),
        )

    def stamp(self, comparison_id, created_at=None):
        """Give a new record its id and creation time, or carry an existing record's over to its replacement."""
        self.id = comparison_id
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        return self

    def __json__(self):
        return {
            "version": COMPARISON_VERSION,
            "id": self.id,
            "anchor": self.anchor,
            "a": self.a,
            "b": self.b,
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "view": self.view,
            "measure": self.measure,
            "reference": self.reference,
            "hidden": self.hidden,
            "kept": self.kept,
            "rankBy": self.rank_by,
            "errorDelta": self.error_delta,
            "zoom": self.zoom,
            "created_at": self.created_at,
        }
