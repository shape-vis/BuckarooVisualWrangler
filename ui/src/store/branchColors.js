/**
 * Colors identifying downstream branches in the node detail panel.
 *
 * Deliberately distinct from errorColors: those say which *error type* a mark represents, these say
 * which *branch* a line belongs to, and both appear at once in the trajectory view. The same color is
 * applied to that branch's edges in the provenance graph, so a line in the panel can be traced to a
 * path in the tree.
 */

const BRANCH_PALETTE = [
    "#0f766e", // teal
    "#7c3aed", // violet
    "#b45309", // amber
    "#1d4ed8", // blue
    "#be185d", // magenta
    "#4d7c0f", // olive
];

// Branches diverging from the selected node share the edges before their fork. A shared edge belongs
// to no single branch, so it stays neutral rather than claiming one branch's color.
export const SHARED_BRANCH_COLOR = "#8c939d";

export function branchColor(index) {
    return BRANCH_PALETTE[index % BRANCH_PALETTE.length];
}
