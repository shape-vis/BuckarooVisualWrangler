/**
 * Every kind of supporting sub-node the graph can hang beside a node, by id.
 *
 * A kind is everything the rest of the app needs to know about it, so adding one is a new file and an
 * entry here - the graph, the layout and the support-nodes window read kinds only through this registry:
 *
 *   id            - the key below, and what a sub-node's record stores as `kind`
 *   label         - its name in the window and on the sub-node
 *   description   - one line in the window saying what it is for
 *   anchor        - "side" (default): beside its host node, left or right
 *                   "edge": beside the edge leading into its host, which in a tree is the host's one
 *                   incoming wrangle - so the record still belongs to the host node
 *   side          - for a side kind: "left", "right", or "auto" to balance the host's two sides
 *   size          - optional {width, height} it is drawn at; DEFAULT_SUPPORT_SIZE otherwise. Or a function of
 *                   the record's config returning one. Never measured, since the layout places sub-nodes
 *                   before anything is measured
 *   unavailable   - optional ({host, records}) => reason string, or null when it can be added to this host.
 *                   records are the host's existing sub-nodes. The window shows the reason and disables Add
 *   defaultConfig - the settings a new one starts from; plain JSON, since records are saved as-is later. Or a
 *                   function of {hostId, comparisonPair, serverNodesById} returning them
 *   incomplete    - optional (config) => what the settings still need, as a sentence, or null once they are
 *                   complete. The window shows it and disables Add meanwhile
 *   resizable     - optional (record) => whether the user can drag its size. A resized record keeps its size
 *                   on the record (`size`), which the layout reads in place of the kind's
 *   ConfigForm    - optional ({value, onChange, hostId}) settings form the window shows before adding one
 *   Gallery       - optional ({hostId, onAdd, paged}) picker the window shows in place of ConfigForm and Add, for
 *                   a kind chosen from ready-made options; onAdd(config) adds one straight away, and returns its id.
 *                   A kind without one is previewed in the window instead - its Body, drawn for the host
 *   galleryPaged  - true for a kind whose gallery has the window to itself, a card a page, for plots with a lot
 *                   to show
 *   addable       - false for a kind made only elsewhere, which the window does not offer
 *   action        - optional, the button in its header: {label, busyLabel, title, run(record, context),
 *                   blockedReason?(record, context)} - see supportActions.js. An error plot's repairs; a plot
 *                   the compare window can show opens there
 *   Badge         - ({record}) the tiny picture of it its host shows while it is hidden - see supportGlyphs.jsx
 *   summary       - optional (record) => one line naming this one, for its badge's hover
 *   Body          - ({record, host, size}) what the sub-node draws; host is the real node it belongs to, as the
 *                   server sent it, so a kind can show anything the node carries; size is what it is drawn at
 */
import {QualityMetricsBody} from "./QualityMetricsSupport.jsx";
import {WrangleDiffBody} from "./WrangleDiffSupport.jsx";
import {wrangleDiffUnavailable} from "./wrangleDiffRules.js";
import {ErrorPlotBody, ErrorPlotGallery} from "./ErrorPlotSupport.jsx";
import {CompareBody} from "./CompareSupport.jsx";
import {COMPARE_DEFAULTS, COMPARE_SIZE, compareSummary} from "./compareView.js";
import {SparklineBody, SparklineGallery} from "./SparklineSupport.jsx";
import {DriftBody, DriftGallery} from "./DriftSupport.jsx";
import {errorPlotRepairBlocked, openCompare, openDrift, startErrorPlotRepair} from "./supportActions.js";
import {
    CompareGlyph, DriftGlyph, ErrorPlotGlyph, QualityMetricsGlyph, SparklineGlyph, WrangleDiffGlyph,
} from "./supportGlyphs.jsx";
import {ERROR_TYPES} from "../../store/errorColors.js";
import {nodeName} from "../../utils/comparison.js";

const DEFAULT_SUPPORT_SIZE = {width: 120, height: 44};

const OPEN_ACTION = {label: "Open ↗", busyLabel: "Opening…"};

const PLOT_LABELS = {histogram: "Histogram", heatmap: "Heatmap"};

function errorPlotSummary(record) {
    const {plot, columns = []} = record.config ?? {};
    const plotLabel = PLOT_LABELS[plot] ?? plot;
    return `${plotLabel} · ${columns.join(" × ")}`;
}

function sparklineSummary(record) {
    const {dimension, nodes = []} = record.config ?? {};
    let name = ERROR_TYPES[dimension] ?? dimension;
    if (dimension === "drift") {
        name = "Drift from root";
    }

    if (nodes.length < 2) return `${name} · no source picked yet`;
    const first = nodeName(nodes[0]);
    const last = nodeName(nodes[nodes.length - 1]);
    return `${name} · ${first} → ${last}`;
}

// A compare sub-node's badge names its comparison, once Save has given it one
function compareRecordSummary(record) {
    const spec = record.config?.spec;
    if (!spec) return "A comparison of two nodes";
    return compareSummary(spec);
}

// A sparkline runs along a branch into its host, so the root - with nothing above it - has none to show
function sparklineUnavailable({host}) {
    if (!host || host.data?.parent === "root") return "The root has no branch leading into it to plot along.";
    return null;
}

export const SUPPORT_NODE_TYPES = {
    qualityMetrics: {
        id: "qualityMetrics",
        label: "Quality metrics",
        description: "The node's error rate for each error type, and its rows and columns.",
        anchor: "side",
        side: "auto",
        size: {width: 160, height: 82},
        defaultConfig: {},
        Badge: QualityMetricsGlyph,
        Body: QualityMetricsBody,
    },
    wrangleDiff: {
        id: "wrangleDiff",
        label: "Wrangle diff",
        description: "Beside the edge into this node: what its wrangle changed, drawn over the parent's state.",
        anchor: "edge",
        size: {width: 210, height: 198},
        unavailable: wrangleDiffUnavailable,
        defaultConfig: {},
        Badge: WrangleDiffGlyph,
        summary: (record) => `On the edge into ${nodeName(record.hostId)}`,
        Body: WrangleDiffBody,
    },
    errorPlot: {
        id: "errorPlot",
        label: "Error plot",
        description: "One of this node's error plots - a histogram or a heatmap of the selected attributes - kept beside it. Repair on it brushes and repairs right there.",
        anchor: "side",
        side: "auto",
        size: {width: 230, height: 250},
        resizable: () => true,
        defaultConfig: {plot: "histogram", columns: []},
        Gallery: ErrorPlotGallery,
        Badge: ErrorPlotGlyph,
        summary: errorPlotSummary,
        Body: ErrorPlotBody,
        action: {
            label: "Repair",
            busyLabel: "Opening…",
            title: "Brush this plot to select rows and repair them - this node becomes the current one",
            run: startErrorPlotRepair,
            blockedReason: errorPlotRepairBlocked,
        },
    },
    drift: {
        id: "drift",
        label: "Drift plot",
        description: "This node's drift from root for one column: a ridgeline for a numeric column, a Sankey for a categorical one.",
        anchor: "side",
        side: "auto",
        // Room for the compare window's whole drift plot - the plot, its zoom strip, the hover note and the legend
        size: {width: 440, height: 500},
        resizable: () => true,
        defaultConfig: {column: ""},
        Gallery: DriftGallery,
        galleryPaged: true,
        Badge: DriftGlyph,
        summary: (record) => `Drift from root · ${record.config?.column ?? ""}`,
        Body: DriftBody,
        action: {
            ...OPEN_ACTION,
            title: "Open in the plot analysis view: this node against root, with the compare window's options",
            run: openDrift,
        },
    },
    qualitySparkline: {
        id: "qualitySparkline",
        label: "Sparkline",
        description: "These track the downstream effects of a wrangle by error type. Add the error type you want to track, then click the edge in the graph where its branch starts.",
        anchor: "side",
        side: "auto",
        size: {width: 240, height: 130},
        resizable: () => true,
        unavailable: sparklineUnavailable,
        defaultConfig: {},
        Gallery: SparklineGallery,
        Badge: SparklineGlyph,
        summary: sparklineSummary,
        Body: SparklineBody,
    },
    compare: {
        id: "compare",
        label: "Compare",
        description: "A comparison of two nodes, kept beside each by Save in the compare window.",
        anchor: "side",
        side: "auto",
        size: COMPARE_SIZE,
        resizable: () => true,
        // Only Save in the compare window makes these
        addable: false,
        defaultConfig: COMPARE_DEFAULTS,
        Badge: CompareGlyph,
        summary: compareRecordSummary,
        Body: CompareBody,
        action: {
            ...OPEN_ACTION,
            title: "Open in the plot analysis view",
            run: openCompare,
        },
    },
};

export const SUPPORT_NODE_TYPE_LIST = Object.values(SUPPORT_NODE_TYPES);

// A record whose kind has since been removed from the registry still draws, as a bare sub-node
export const getSupportType = (kind) => SUPPORT_NODE_TYPES[kind] ?? null;

// The size one sub-node is drawn at: what the user resized it to, else its kind's - which can follow its settings
export const recordSizeOf = (record) => {
    if (record.size) return record.size;

    const kindSize = getSupportType(record.kind)?.size;
    let size = kindSize;
    if (typeof kindSize === "function") {
        size = kindSize(record.config ?? {});
    }
    return size ?? DEFAULT_SUPPORT_SIZE;
};

// Where a record's sub-node attaches: "side" or "edge"
export const anchorOf = (record) => getSupportType(record.kind)?.anchor ?? "side";

// A host node's columns, in the order its metrics list them
export function hostColumns(host) {
    const columns = host?.data?.metrics?.columns ?? {};
    return Object.keys(columns);
}
