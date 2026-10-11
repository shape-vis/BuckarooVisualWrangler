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
 *   Body          - ({record, host}) what the sub-node draws; host is the real node it belongs to, as the
 *                   server sent it, so a kind can show anything the node carries
 */
import {PlaceholderConfigForm, PlaceholderBody} from "./PlaceholderSupport.jsx";
import {QualityMetricsBody} from "./QualityMetricsSupport.jsx";
import {WrangleDiffBody} from "./WrangleDiffSupport.jsx";
import {wrangleDiffUnavailable} from "./wrangleDiffRules.js";
import {PlotViewBody, PlotViewConfigForm} from "./PlotViewSupport.jsx";
import {PREVIEW_SIZE, SINGLE_PLOT_SIZE, isSinglePlot, plotViewDefaults, plotViewIncomplete} from "./plotView.js";

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
    plotView: {
        id: "plotView",
        label: "Plot view",
        description: "A comparison plot kept beside the node: against another node or on its own, in full or narrowed to what you choose.",
        anchor: "side",
        side: "auto",
        // A single plot is drawn in full and starts larger; anything else is a preview that opens in the compare window
        size: (config) => (isSinglePlot(config) ? SINGLE_PLOT_SIZE : PREVIEW_SIZE),
        resizable: () => true,
        defaultConfig: plotViewDefaults,
        incomplete: plotViewIncomplete,
        ConfigForm: PlotViewConfigForm,
        Body: PlotViewBody,
    },
    placeholder: {
        id: "placeholder",
        label: "Placeholder",
        description: "A stand-in sub-node with a short note, until the real kinds are defined.",
        anchor: "side",
        side: "auto",
        defaultConfig: {note: ""},
        ConfigForm: PlaceholderConfigForm,
        Body: PlaceholderBody,
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
