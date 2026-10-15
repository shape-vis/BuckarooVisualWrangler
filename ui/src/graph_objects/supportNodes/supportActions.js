/**
 * The action in a supporting sub-node's header, for the kinds that have one. Each says what it does through its
 * registry entry's action: {label, busyLabel, title, run(record, context), blockedReason?(record, context)}. The
 * context is everything those need - gathered once by useSupportActionContext, so the kinds' actions stay plain
 * functions:
 *
 *   errorPlot   - Repair: its node made current, then the sub-node grows into the matrix's own plot, to brush and
 *                 repair on there - a wrangle always runs on the current node (see ErrorPlotSupport)
 *   drift       - Open: the compare window, its node against root on its column
 *   compare     - Open: the compare window, as Save left it
 *
 * Wrangle diffs, quality metrics and sparklines have none.
 */
import {usePgraph} from "../../store/PGraphContext.jsx";
import {useTableName} from "../../store/TableNameContext.jsx";
import {useCompare} from "../../store/CompareContext.jsx";
import {CANDIDATE_LOCKED} from "../../store/RepairContext.jsx";

/** What a kind's action needs from the app, gathered for the sub-node frame to hand over. */
export function useSupportActionContext() {
    const {navigateToNode, startWrangling, isCandidate} = usePgraph();
    const {tableName} = useTableName();
    const {openCompareNode, openDriftNode} = useCompare() ?? {};
    return {tableName, navigateToNode, startWrangling, isCandidate, openCompareNode, openDriftNode};
}

/* Brushing and repair run on the current node, so the host becomes it - as double-clicking it would - and then
   the sub-node grows into the plot to wrangle on. */
export async function startErrorPlotRepair(record, context) {
    if (record.hostId !== context.tableName) await context.navigateToNode(record.hostId);
    context.startWrangling(record);
}

// Nothing is repaired from a staged candidate until it is accepted
export function errorPlotRepairBlocked(record, context) {
    if (context.isCandidate(record.hostId)) return `${CANDIDATE_LOCKED}.`;
    return null;
}

export function openDrift(record, context) {
    context.openDriftNode?.(record);
}

export function openCompare(record, context) {
    context.openCompareNode?.(record);
}
