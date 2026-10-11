/**
 * The plot-view kind of supporting sub-node: a comparison kept beside a node, set up by a few questions.
 *
 * The answers do not make new plots. They decide which of the compare panel's own controls the sub-node
 * offers and which it fixes - the plot kinds, and for each kind whether the column is fixed - and everything
 * else is the compare panel's: its plots, its data, its options. See restrictionsOf.
 *
 *   nodes        - "pair": this node against another; "single": this node alone, measured from root
 *   other        - the node compared with, a table name, when nodes is "pair". It is selection A and the
 *                  host selection B, as in the compare panel, where B is the node being looked at
 *   scope        - "full": every option the compare panel has; "specific": the choices below
 *   measure      - "error", "drift" or "both"
 *   errorPlot    - "histogram" or "heatmap"
 *   errorColumns - "all": the column picker stays; "one": errorX - and errorY for a heatmap - fixed
 *   driftColumns - "all", or "one" with driftX fixed
 *   spec         - the comparison object last shown for it (utils/comparisonSpec.js), or null until it
 *                  is first opened. Kept up to date while it is open in the compare panel
 *   group        - shared by the sub-nodes one Save in the compare panel added, so they change together
 *
 * Plain JSON throughout, since records are saved as they are.
 */
import { PLOT_KINDS } from "../../utils/comparison.js";
import { normalizeSpec } from "../../utils/comparisonSpec.js";

export const PLOT_VIEW_DEFAULTS = {
    nodes: null,
    other: null,
    scope: null,
    measure: null,
    errorPlot: null,
    errorColumns: null,
    errorX: "",
    errorY: "",
    driftColumns: null,
    driftX: "",
    spec: null,
    group: null,
};

// The size a sub-node starts at: a single plot drawn in full, or a preview
export const SINGLE_PLOT_SIZE = { width: 380, height: 300 };
export const PREVIEW_SIZE = { width: 260, height: 206 };

/**
 * Where a new plot-view sub-node starts. With a pair set up in the graph that involves another node, it
 * starts as a comparison with that one - the likeliest reason to be adding a plot view at all.
 */
export function plotViewDefaults({ hostId, comparisonPair, serverNodesById }) {
    const paired = comparisonPair && [comparisonPair.a, comparisonPair.b].includes(hostId)
        ? [comparisonPair.a, comparisonPair.b].find((id) => id !== hostId)
        : comparisonPair?.a;
    const other = paired && paired !== hostId && serverNodesById?.[paired] ? paired : null;
    return { ...PLOT_VIEW_DEFAULTS, nodes: other ? "pair" : null, other };
}

const usesError = (config) => config.measure === "error" || config.measure === "both";
const usesDrift = (config) => config.measure === "drift" || config.measure === "both";

/** What the settings still need, as a sentence for the modal, or null once they are complete. */
export function plotViewIncomplete(config) {
    if (!config.nodes) return "Choose whether to compare two nodes or look at this one.";
    if (config.nodes === "pair" && !config.other) return "Choose the node to compare with.";
    if (!config.scope) return "Choose a full comparison or a specific view.";
    if (config.scope === "full") return null;
    if (!config.measure) return "Choose error, drift or both.";
    if (usesError(config)) {
        if (!config.errorPlot) return "Choose a histogram or a heatmap for errors.";
        if (!config.errorColumns) return "Choose all columns or one for errors.";
        if (config.errorColumns === "one") {
            if (!config.errorX) return config.errorPlot === "heatmap" ? "Choose the heatmap's X column." : "Choose the error column.";
            if (config.errorPlot === "heatmap" && !config.errorY) return "Choose the heatmap's Y column.";
        }
    }
    if (usesDrift(config)) {
        if (!config.driftColumns) return "Choose all columns or one for drift.";
        if (config.driftColumns === "one" && !config.driftX) return "Choose the drift column.";
    }
    return null;
}

/**
 * Which of the compare panel's options the sub-node leaves open: the plot kinds it offers, null for all,
 * and for each kind whose column it fixed, that column. A full comparison fixes nothing.
 */
export function restrictionsOf(config) {
    if (config.scope !== "specific") return { kinds: null, columns: null };
    const kinds = [];
    const columns = {};
    if (usesError(config)) {
        kinds.push(config.errorPlot);
        if (config.errorColumns === "one") {
            columns[config.errorPlot] = { x: config.errorX, y: config.errorPlot === "heatmap" ? config.errorY : null };
        }
    }
    if (usesDrift(config)) {
        kinds.push("drift");
        if (config.driftColumns === "one") columns.drift = { x: config.driftX };
    }
    return { kinds, columns };
}

/** Whether every choice is fixed - one kind of plot of one column - so the sub-node draws it in full. */
export function isSinglePlot(config) {
    if (config.scope !== "specific" || config.measure === "both") return false;
    return config.measure === "error" ? config.errorColumns === "one" : config.driftColumns === "one";
}

/**
 * The comparison the sub-node shows: what it last showed, or where its answers start it - the first kind
 * they allow, on its fixed column if it has one. A column left open starts on the host's first column.
 */
export function specOfPlotView(record, hostColumns) {
    const { config, hostId } = record;
    if (config.spec) return normalizeSpec(config.spec);

    const { kinds, columns } = restrictionsOf(config);
    const kind = kinds?.[0] ?? PLOT_KINDS[0].id;
    const fixed = columns?.[kind];
    return normalizeSpec({
        a: config.nodes === "pair" ? config.other : hostId,
        b: hostId,
        anchor: hostId,
        kind,
        x: fixed?.x || hostColumns[0] || "",
        y: fixed?.y || hostColumns[1] || hostColumns[0] || null,
        // One node only ever has the one panel to draw, and its error change runs from root
        errorDelta: config.nodes === "pair" ? "ab" : "rootB",
    });
}

/** A short line saying what a sub-node was set up to show, for its own header. */
export function describePlotView(config) {
    if (config.scope === "full") return "Full comparison";
    const parts = [];
    if (usesError(config)) {
        parts.push(`Error ${config.errorPlot}${config.errorColumns === "one"
            ? ` · ${config.errorPlot === "heatmap" ? `${config.errorX} × ${config.errorY}` : config.errorX}` : ""}`);
    }
    if (usesDrift(config)) parts.push(`Drift${config.driftColumns === "one" ? ` · ${config.driftX}` : ""}`);
    return parts.join(", ");
}

/** The settings a Save in the compare panel keeps a comparison with: every option, as it stands. */
export function savedPlotViewConfig(spec, hostId, group) {
    const other = hostId === spec.a ? spec.b : spec.a;
    return { ...PLOT_VIEW_DEFAULTS, nodes: "pair", other, scope: "full", spec, group };
}
