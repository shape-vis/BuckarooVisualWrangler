// comparisonSpec.js
// The comparison object: everything the compare panel shows, as one plain record of settings. The panel
// opens from one and reports one, and a compare sub-node keeps one in its config. Settings only: opening one
// fetches its plot again.

export const SPEC_VERSION = 1;

const DEFAULTS = {
    version: SPEC_VERSION,
    anchor: null,
    a: null,
    b: null,
    kind: "histogram",
    // Empty until the panel picks the most changed attribute for itself
    x: "",
    y: null,
    view: "side",
    measure: "items",
    reference: "root",
    hidden: [],
    kept: null,
    rankBy: "error",
    errorDelta: "ab",
    zoom: null,
};

/* A folded run stands in for its last node - the state the run arrives at, and whose metrics it
   already reports - so that is the table it is compared as. */
export function tableOf(node, id) {
    return node?.type === "collapsedNode" ? node.data.tail : id;
}

/**
 * A new comparison of the two nodes paired in the graph, pinned to selection B - the current node.
 * @param pair {a, b} node ids as PGraphContext's comparisonPair names them, folded runs included
 * @param nodesById the graph's drawn nodes, by id
 */
export function specFromPair(pair, nodesById) {
    const a = tableOf(nodesById[pair.a], pair.a);
    const b = tableOf(nodesById[pair.b], pair.b);
    return { ...DEFAULTS, a, b, anchor: b };
}

/** A record as stored or sent, with anything it leaves out filled in from the defaults. */
export function normalizeSpec(spec) {
    const filled = { ...DEFAULTS, ...spec };
    return {
        ...filled,
        anchor: filled.anchor ?? filled.b,
        hidden: Array.isArray(filled.hidden) ? filled.hidden : [],
        kept: Array.isArray(filled.kept) ? filled.kept : null,
        zoom: Array.isArray(filled.zoom) && filled.zoom.length === 2 ? filled.zoom : null,
    };
}

// Everything but the id is a setting. A fixed order, so a record the server sent back compares equal to the panel's
const SETTINGS_KEYS = Object.keys(DEFAULTS).filter((key) => key !== "id");

/** A record's settings as one string - equal for two records that show the same thing. */
export function settingsOf(spec) {
    return JSON.stringify(SETTINGS_KEYS.map((key) => spec[key] ?? null));
}

/** The record a settingsOf string was made from, less its id. */
export function specFromSettings(settings) {
    const values = JSON.parse(settings);
    return Object.fromEntries(SETTINGS_KEYS.map((key, i) => [key, values[i]]));
}

/**
 * What a zoomed drift plot's zoom belongs to. A zoom chosen for another column, pair or reference means
 * nothing here, so the plot reads one stamped with any other key as no zoom at all.
 */
export function driftZoomKey({ x, a, b, base }) {
    return `${x}|${a}|${b}|${base ?? ""}`;
}
