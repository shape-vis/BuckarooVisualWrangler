"""
A small graph to compare and measure drift across, built the way a user builds one - October 28, 2026:

    root ── child (accepted)  ── grandchild (staged)
       └─── sibling (staged)

The child is a repair of one column's selection, the sibling the other repair of that same selection - the delete
and impute pair from the user's screenshots - and the grandchild a repair staged from the child.
"""
import random
from dataclasses import dataclass

from tests.stress import generators, reference
from tests.stress.conftest import read_stored


@dataclass
class Family:
    root: object
    child: object
    sibling: object
    grandchild: object

    def pairs(self):
        """Every pair worth comparing, named."""
        return {
            "root_child": (self.root, self.child),
            "siblings": (self.child, self.sibling),
            "self": (self.child, self.child),
            "root_grandchild": (self.root, self.grandchild),
            "grandchild_root": (self.grandchild, self.root),
        }


def _stage(client, row_ids, cols):
    response = client.post("/api/wrangle/create-previews", json={"row_ids": row_ids, "cols": cols})
    assert response.status_code == 200, response.get_json()
    staged = {}
    for candidate in response.get_json()["candidates"]:
        staged[candidate["op"]] = candidate
    return staged


def _selection(table, column, rng):
    """
    The column's missing rows when it has any - the usual repair - or else a random third of the rows. A table with no
    rows left is given an id that names none, which stages a candidate identical to it.
    """
    if not table.ids:
        return [1]
    missing = []
    for row_id, values in table.rows():
        if reference.is_missing(values[column]):
            missing.append(row_id)
    if missing:
        return missing
    return sorted(rng.sample(table.ids, max(1, len(table.ids) // 3)))


def build_family(make_root, client, seed):
    rng = random.Random(seed)
    if seed % 2 == 0:
        dataset = generators.make_dataset(seed, personalities=generators.CSV_SAFE)
        root = make_root(dataset, ingest="csv")
    else:
        root = make_root(generators.make_dataset(seed), ingest="direct")

    column = rng.choice(root.data_columns)
    staged = _stage(client, _selection(root, column, rng), [column])
    child_op = rng.choice(["delete", "impute"])
    sibling_op = "impute" if child_op == "delete" else "delete"

    child_table = staged[child_op]["table"]
    response = client.post("/api/candidates/accept", json={"table": child_table})
    assert response.status_code == 200, response.get_json()
    child = read_stored(child_table)
    sibling = read_stored(staged[sibling_op]["table"])

    second_column = rng.choice(child.data_columns)
    grandchild_staged = _stage(client, _selection(child, second_column, rng), [second_column])
    grandchild = read_stored(grandchild_staged[rng.choice(sorted(grandchild_staged))]["table"])

    return Family(root=root, child=child, sibling=sibling, grandchild=grandchild)
