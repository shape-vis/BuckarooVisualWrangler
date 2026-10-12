/**
 * Every kind of supporting sub-node the graph can hang beside a node, by id.
 *
 * A kind is everything the rest of the app needs to know about it, so adding one is a new file and an
 * entry here - the graph, the layout and the modal read kinds only through this registry:
 *
 *   id            - the key below, and what a sub-node's record stores as `kind`
 *   label         - its name in the modal and on the sub-node
 *   description   - one line in the modal saying what it is for
 *   anchor        - "side" (default): beside its host node, left or right
 *                   "edge": beside the edge leading into its host, which in a tree is the host's one
 *                   incoming wrangle - so the record still belongs to the host node
 *   side          - for a side kind: "left", "right", or "auto" to balance the host's two sides
 *   size          - optional {width, height} it is drawn at; DEFAULT_SUPPORT_SIZE otherwise. Or a function of
 *                   the record's config returning one. Never measured, since the layout places sub-nodes
 *                   before anything is measured
 *   unavailable   - optional ({host, records}) => reason string, or null when it can be added to this host.
 *                   records are the host's existing sub-nodes. The modal shows the reason and disables Add
 *   defaultConfig - the settings a new one starts from; plain JSON, since records are saved as-is later. Or a
 *                   function of {hostId, comparisonPair, serverNodesById} returning them
 *   incomplete    - optional (config) => what the settings still need, as a sentence, or null once they are
 *                   complete. The modal shows it and disables Add meanwhile
 *   resizable     - optional (record) => whether the user can drag its size. A resized record keeps its size
 *                   on the record (`size`), which the layout reads in place of the kind's
 *   ConfigForm    - optional ({value, onChange, hostId}) settings form the modal shows before adding one
 *   Gallery       - optional ({hostId, onAdd}) picker the modal shows in place of ConfigForm and Add, for a
 *                   kind chosen from ready-made options; onAdd(config) adds one straight away
 *   addable       - false for a kind made only elsewhere, which the modal does not offer
 *   open          - optional (record, context) => opens its plot in the Plots view, from the Open in its header;
 *                   see supportOpen.js. Error plots go to the standard plot view, every other plot to the
 *                   plot analysis view (the compare window)
 *   openTitle     - what that Open says it does
 *   canOpen       - optional ({record, host}) => whether there is anything to open for this one
 *   Body          - ({record, host}) what the sub-node draws; host is the real node it belongs to, as the
 *                   server sent it, so a kind can show anything the node carries
 */
import {QualityMetricsBody} from "./QualityMetricsSupport.jsx";
import {WrangleDiffBody} from "./WrangleDiffSupport.jsx";
import {wrangleDiffUnavailable} from "./wrangleDiffRules.js";
import {ErrorPlotBody, ErrorPlotGallery} from "./ErrorPlotSupport.jsx";
import {CompareBody} from "./CompareSupport.jsx";
import {COMPARE_DEFAULTS, COMPARE_SIZE} from "./compareView.js";
import {SparklineBody} from "./SparklineSupport.jsx";
import {DriftBody, DriftGallery} from "./DriftSupport.jsx";
import {openCompare, openDrift, openErrorPlot} from "./supportOpen.js";

export const DEFAULT_SUPPORT_SIZE = {width: 120, height: 44};

export const SUPPORT_NODE_TYPES = {
    qualityMetrics: {
        id: "qualityMetrics",
        label: "Quality metrics",
        description: "The node's error rate for each error type, and its rows and columns.",
        anchor: "side",
        side: "auto",
        size: {width: 160, height: 82},
        defaultConfig: {},
        ConfigForm: null,
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
        ConfigForm: null,
        Body: WrangleDiffBody,
    },
    errorPlot: {
        id: "errorPlot",
        label: "Error plot",
        description: "One of this node's error plots - a histogram or a heatmap of the selected attributes - kept beside it.",
        anchor: "side",
        side: "auto",
        size: {width: 230, height: 250},
        resizable: () => true,
        defaultConfig: {plot: "histogram", columns: []},
        Gallery: ErrorPlotGallery,
        Body: ErrorPlotBody,
        open: openErrorPlot,
        openTitle: "Open in the standard plot view to brush and wrangle it - this node becomes the current one",
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
        Body: DriftBody,
        open: openDrift,
        openTitle: "Open in the plot analysis view: this node against root, with the compare window's options",
    },
    qualitySparkline: {
        id: "qualitySparkline",
        label: "Quality sparkline",
        description: "One quality dimension along a branch, dragged here from the Quality panel.",
        anchor: "side",
        side: "auto",
        size: {width: 240, height: 120},
        resizable: () => true,
        // Only dragging a Quality panel card onto the node makes these
        addable: false,
        defaultConfig: {},
        ConfigForm: null,
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
        ConfigForm: null,
        Body: CompareBody,
        open: openCompare,
        openTitle: "Open in the plot analysis view",
    },
};

export const SUPPORT_NODE_TYPE_LIST = Object.values(SUPPORT_NODE_TYPES);

// A record whose kind has since been removed from the registry still draws, as a bare sub-node
export const getSupportType = (kind) => SUPPORT_NODE_TYPES[kind] ?? null;

// The size one sub-node is drawn at: what the user resized it to, else its kind's - which can follow its settings
export const recordSizeOf = (record) => {
    if (record.size) return record.size;
    const size = getSupportType(record.kind)?.size;
    return (typeof size === "function" ? size(record.config ?? {}) : size) ?? DEFAULT_SUPPORT_SIZE;
};

// Where a record's sub-node attaches: "side" or "edge"
export const anchorOf = (record) => getSupportType(record.kind)?.anchor ?? "side";
