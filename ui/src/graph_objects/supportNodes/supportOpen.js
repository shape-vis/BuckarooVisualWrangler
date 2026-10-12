/**
 * Opening a supporting sub-node's plot in the Plots view - the standard Open in every sub-node's header.
 *
 * Each kind that holds a plot says where it goes through its registry entry's open: (record, context) => void,
 * and canOpen: ({record, host}) => whether there is anything to open. The context is everything those need -
 * gathered once by useSupportOpenContext, so the kinds' open functions stay plain functions:
 *
 *   errorPlot   - the Plots view's matrix, zoomed to its plot, on its node made current - where brushing and
 *                 repair live, and a wrangle always runs on the current node
 *   drift       - the compare window, its node against root on its column
 *   compare     - the compare window, as Save left it
 *
 * Wrangle diffs, quality metrics and quality sparklines have no Open.
 */
import {useContext} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {useTableName} from "../../store/TableNameContext.jsx";
import {useCompare} from "../../store/CompareContext.jsx";
import {ViewContext} from "../../pages/Buckaroo.jsx";

/** What a kind's open needs from the app, gathered for the sub-node frame to hand over. */
export function useSupportOpenContext() {
    const {navigateToNode} = usePgraph();
    const {tableName} = useTableName();
    const {focusPlot} = useContext(ViewContext) ?? {};
    const {setPlotsTab, openCompareNode, openDriftNode} = useCompare() ?? {};
    return {tableName, navigateToNode, focusPlot, setPlotsTab, openCompareNode, openDriftNode};
}

/* Brushing and repair run on the current node, so the host becomes it - as double-clicking it would - and the
   Plots view opens on its matrix, zoomed to this plot. */
export async function openErrorPlot(record, context) {
    if (record.hostId !== context.tableName) await context.navigateToNode(record.hostId);
    context.focusPlot?.(record.config.columns);
    context.setPlotsTab?.("attributes");
}

export function openDrift(record, context) {
    context.openDriftNode?.(record);
}

export function openCompare(record, context) {
    context.openCompareNode?.(record);
}
