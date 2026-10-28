"""
Supporting sub-nodes kept on the graph's nodes - October 27, 2026

A supporting sub-node is a plot or a panel the user hangs beside a node to help read it: an error plot, a drift plot,
the quality metrics, a sparkline of a branch, a comparison with another node, the diff of the wrangle that made it.
Each is kept on its host GraphNode as a plain JSON record - {id, hostId, kind, side, config, size} - which is the
recipe for drawing it, never the plot itself. The front end fetches the plot when it draws one, so keeping a record
costs nothing, and copying one costs a dictionary copy.

That is what lets a new node start with the sub-nodes its parent has: when a candidate is staged, its parent's
records are copied onto it, each pointed at the candidate. They arrive minimised - badges on the candidate - so a
repair staging three candidates doesn't fill the graph with plots, and accepting the candidate chooses what becomes
of them: shown, kept hidden, or dropped - see apply_inherit_choice.

Nothing here touches the database, so it is all testable on its own.
"""
import copy
import secrets

# The kinds the front end's registry knows - ui/src/graph_objects/supportNodes/registry.js
SUPPORT_KINDS = ("qualityMetrics", "wrangleDiff", "errorPlot", "drift", "qualitySparkline", "compare")

# Describes the one edge into its host, which a child does not share, so it is never inherited
NOT_INHERITED = ("wrangleDiff",)

# What accepting a candidate does with the sub-nodes it inherited
INHERIT_CHOICES = ("show", "hide", "drop")

# Table names never contain a colon, so the prefix keeps every sub-node id clear of them - see graphTopology.js
SUPPORT_PREFIX = "support:"


def support_id(host_id):
    """:return: a new sub-node id on this host, as the front end's supportId makes them"""
    return f"{SUPPORT_PREFIX}{host_id}:{secrets.token_hex(4)}"


def _swapped(value, parent_id, child_id):
    """:return: child_id where value names the parent, else value unchanged"""
    if value == parent_id:
        return child_id
    return value


def _inherited_compare_config(config, parent_id, child_id):
    """
    The parent's comparison, run again with the child in the parent's place.

    The comparator - `other` - stays. The child takes whichever selection the parent held, A or B, so the plot reads
    the same way round; a single-node comparison of the parent against root becomes one of the child.

    The copy belongs to no group: a group's records follow one another's settings, which would put the parent's pair
    back. Zoom and the chosen categories are for one pair's data, so they start over.
    """
    inherited = copy.deepcopy(config)
    inherited["group"] = None

    spec = inherited.get("spec")
    if spec:
        spec["a"] = _swapped(spec.get("a"), parent_id, child_id)
        spec["b"] = _swapped(spec.get("b"), parent_id, child_id)
        spec["anchor"] = _swapped(spec.get("anchor"), parent_id, child_id)
        spec["zoom"] = None
        spec["kept"] = None
        spec["hidden"] = []

    return inherited


def _inherited_sparkline_config(config, child_id):
    """
    The parent's branch, carried on down to the child.

    The branch leaves through the same edge - it is above the parent, so it is above the child too - and now ends at
    the child. The values measured for the parent's branch don't hold for this one, so they are cleared, and the front
    end measures the branch again when it draws it.
    """
    inherited = copy.deepcopy(config)
    branch = inherited.get("branch")
    if branch:
        branch["destination"] = child_id
        # Empty, as a sparkline is before it is measured - not None, which the front end would read as values
        inherited["nodes"] = []
        inherited["values"] = []
        inherited["deltas"] = []
    return inherited


def _inherited_config(record, parent_id, child_id):
    """:return: the config a child's copy of this record has"""
    kind = record.get("kind")
    config = record.get("config") or {}

    if kind == "compare":
        return _inherited_compare_config(config, parent_id, child_id)
    if kind == "qualitySparkline":
        return _inherited_sparkline_config(config, child_id)

    # The rest name no node: an error plot, a drift plot and the metrics read whichever node hosts them, so the
    # same settings - which plot, which columns - show the child's own data
    return copy.deepcopy(config)


def inherited_support_nodes(parent_records, parent_id, child_id):
    """
    The sub-nodes a new child starts with: a copy of each of its parent's, pointed at the child.

    :param parent_records: the parent's support-node records
    :param parent_id: the parent's table name
    :param child_id: the child's table name
    :return: new records, marked inherited and to start minimised
    """
    inherited = []
    for record in parent_records:
        if record.get("kind") in NOT_INHERITED:
            continue

        child_record = {
            "id": support_id(child_id),
            "hostId": child_id,
            "kind": record.get("kind"),
            "side": record.get("side", "auto"),
            "config": _inherited_config(record, parent_id, child_id),
            "size": copy.deepcopy(record.get("size")),
            # Copied, and not touched since - what accepting without them takes away
            "inherited": True,
            # Shown as a badge the first time the front end sees it, so the child doesn't arrive buried in plots
            "startMinimized": True,
        }
        inherited.append(child_record)

    return inherited


def apply_inherit_choice(records, choice):
    """
    What accepting a candidate does with the sub-nodes it inherited.

        show  they open on the accepted node
        hide  they stay badges until the user opens one
        drop  they are taken away - all but any the user changed while looking the candidate over, which are theirs

    Either way, what is left is an ordinary record from then on.

    :param records: the candidate's support-node records
    :param choice: one of INHERIT_CHOICES
    :return: the records the accepted node keeps
    """
    if choice not in INHERIT_CHOICES:
        raise ValueError(f"unknown inherit choice {choice!r}")

    kept = []
    for record in records:
        was_inherited = record.get("inherited", False)
        if was_inherited and choice == "drop":
            continue

        kept_record = dict(record)
        kept_record["inherited"] = False
        if was_inherited and choice == "show":
            kept_record["startMinimized"] = False
        kept.append(kept_record)

    return kept
