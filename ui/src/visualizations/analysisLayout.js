// analysisLayout.js
// Where the provenance graph's nodes sit in analysis mode: every node plotted on drift from root (x) against
// its error rate (y), with each node joined to its parent so a branch reads as a path walking out from root.
// Whether a wrangle bought fewer errors at the cost of more drift shows as the direction of its step - and
// since error runs from 0 at the bottom, a wrangle that cut errors steps down.
//
// Plain geometry and text, kept apart from React Flow: the graph lays its own nodes out from these.

import * as d3 from "d3";
import { ERROR_DIMENSIONS, ERROR_TYPES } from "../store/errorColors.js";
import { describeWrangle, nodeName } from "../utils/comparison.js";
import { formatDrift } from "../utils/drift.js";
import { asPercent } from "../utils/visCommon.jsx";

// The error axis can be the total or any one error type. Drift has no per-type breakdown, so x never changes.
export const ANALYSIS_METRICS = ["total", ...ERROR_DIMENSIONS];
export const METRIC_LABELS = { total: "Total", missing: "Missing", mismatch: "Mismatch", anomaly: "Anomaly", incomplete: "Incomplete" };
export const metricTitle = (metric) => (metric === "total" ? "Total error" : ERROR_TYPES[metric]);

// A dot node's box - its label hangs outside it, so this is the whole of what React Flow measures
export const DOT = 14;
// What a card measures before React Flow has measured it
export const CARD = { width: 200, height: 100 };

/* The axes' strips along the canvas's left and bottom edges, wide and tall enough for a tick label and the
   axis title beside it. The plot is fitted inside them, with a margin, so nothing sits under an axis - and
   under the graph's toolbar at the top. */
export const AXIS_BOTTOM = 40;
const FIT = { top: 72, right: 28, bottom: AXIS_BOTTOM + 20, gap: 20 };

/* The y axis's strip is as wide as its labels need: a column for the rotated title, then the longest tick
   label, then the tick. Error rates can be tiny - "0.00055%" - and a strip sized for "0.10%" would run the
   labels into the title. AXIS_LEFT is the narrowest it gets. */
export const AXIS_LEFT = 66;
export const AXIS_TITLE_ROOM = 22;
export const AXIS_TICK = 5;
export const AXIS_LABEL_GAP = 3;
const SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";
const TICK_FONT = `11px ${SANS}`;
export const TITLE_FONT = `600 12px ${SANS}`;

let measurer = null;
// How wide a piece of text draws in a font - the tick labels' by default
export function textWidth(text, font = TICK_FONT) {
    measurer ??= document.createElement("canvas").getContext("2d");
    measurer.font = font;
    return measurer.measureText(text).width;
}

// Percentages to as many places as a step of this size between them needs
function percentFormat(step) {
    const digits = Math.max(0, d3.precisionFixed(step * 100));
    return (value) => `${(value * 100).toFixed(digits)}%`;
}

// Plain numbers to as many places as a step of this size between them needs
function fixedFormat(step) {
    const digits = Math.max(0, d3.precisionFixed(step));
    return d3.format(`.${digits}f`);
}

/* Ticks between two values, labelled at the precision their spacing needs - as percentages for an error rate,
   as plain numbers for drift. Neither goes below zero, so no tick does either. Shared by the plot's axes and
   the detail inset's, so the two always label a value the same way. */
export function spacedTicks(lo, hi, count, asPercentage) {
    const values = d3.ticks(lo, hi, count).filter((value) => value >= 0);
    const step = values.length > 1 ? values[1] - values[0] : hi - lo;
    const format = asPercentage ? percentFormat(step) : fixedFormat(step);
    return values.map((value) => ({ value, label: format(value) }));
}

/* The error axis's ticks between two rates. Shared by the axes and by the strip's width, so the width is always
   worked out from the labels actually drawn. */
export const errorTicks = (lo, hi, count) => spacedTicks(lo, hi, count, true);

// How many error ticks a canvas this tall gets - one per 70px or so
export const errorTickCount = (height) => Math.max(2, Math.round((height - AXIS_BOTTOM) / 70));

// The y axis strip's width for these ticks
export function axisLeftFor(ticks) {
    const widest = d3.max(ticks, (tick) => textWidth(tick.label)) ?? 0;
    return Math.max(AXIS_LEFT, Math.ceil(AXIS_TITLE_ROOM + widest + AXIS_LABEL_GAP + AXIS_TICK + 6));
}

// The camera's padding around the plot: clear of the axes on the left and bottom, and of the toolbar above
export const plotFitPadding = (axisLeft) => ({
    top: `${FIT.top}px`, right: `${FIT.right}px`, bottom: `${FIT.bottom}px`, left: `${axisLeft + FIT.gap}px`,
});

/* The plot is sized from the canvas it is drawn on, as a chart fills its frame, so that fitting it lands on a
   set zoom: the dots at their own size, so they and their labels read the same in any pane, and the cards a
   little under theirs. A node sits centred on its point, so the plot keeps half a node's margin around it -
   a card on the plot's edge would otherwise hang out under an axis. */
const FIT_ZOOM = { simple: 1, full: 0.8 };
const MARGIN = { simple: { x: DOT, y: DOT }, full: { x: CARD.width / 2 + 10, y: CARD.height / 2 + 10 } };
// Before the canvas has been measured
const FALLBACK_CANVAS = { width: 900, height: 600 };

/* One colour per top-level branch - the subtree under each of root's children - so the paths stay
   distinguishable where they cross. Kept clear of the comparison roles' blue and Persian plum and of the error
   types' colours. */
const BRANCH_COLORS = ["#8c6bb1", "#e08214", "#00838f", "#c2185b", "#8d6e63", "#5c6bc0", "#9e9d24"];
export const ROOT_COLOR = "#4b5563";

/* A supporting sub-node describes its host rather than being a state of the table, so it has no point of its
   own, and its position is relative to its host besides. Hidden on the plot for now. */
// Its boundary goes with it
const isSupportNode = (node) => node.type === "supportNode" || node.type === "supportGroup";

// Everything else is plotted - a staged candidate included, which carries its own error and drift
export const isPlotted = (node) => !isSupportNode(node);

// A folded run stands for its last node - the state it arrives at - and already carries that node's numbers
export const tableOf = (node) => (node.type === "collapsedNode" ? node.data?.tail : node.id);
export const driftOf = (node) => node.data?.distortion?.overall ?? 0;
export const errorOf = (node, metric) => node.data?.metrics?.totals?.[metric] ?? 0;

// A node's short label on the plot: its name, or a folded run's first and last node
export function plotLabel(node) {
    if (node.type !== "collapsedNode") return nodeName(node.id);
    return `${nodeName(node.data.head)}…${nodeName(node.data.tail)}`;
}

/* Whether a node's point falls inside a region of the plot, {x: [from, to], y: [from, to]} in drift and in the
   error the y axis shows - edges included */
export function isInRegion(node, region, metric) {
    const drift = driftOf(node);
    const error = errorOf(node, metric);
    return drift >= region.x[0] && drift <= region.x[1] && error >= region.y[0] && error <= region.y[1];
}

/* The plot's scales, from the nodes it shows. Both axes start at zero: root has no drift by definition, and an
   error rate has a real floor. */
export function analysisScales(nodes, metric, style, canvas) {
    const plotted = nodes.filter(isPlotted);
    const { width: canvasWidth, height: canvasHeight } = canvas?.width && canvas?.height ? canvas : FALLBACK_CANVAS;
    const maxDrift = d3.max(plotted, driftOf) || 0;
    const maxError = d3.max(plotted, (node) => errorOf(node, metric)) || 0;
    const x = d3.scaleLinear().domain([0, maxDrift > 0 ? maxDrift * 1.08 : 1]).nice();
    const y = d3.scaleLinear().domain([0, maxError > 0 ? maxError * 1.08 : 0.01]).nice();

    // The y axis strip is sized from the labels it will draw, and the plot fitted beside it
    const axisLeft = axisLeftFor(errorTicks(...y.domain(), errorTickCount(canvasHeight)));
    const margin = MARGIN[style];
    const width = Math.max(120, (canvasWidth - axisLeft - FIT.gap - FIT.right) / FIT_ZOOM[style] - 2 * margin.x);
    const height = Math.max(90, (canvasHeight - FIT.top - FIT.bottom) / FIT_ZOOM[style] - 2 * margin.y);
    return {
        width,
        height,
        axisLeft,
        // What the camera fits: the plot and its margin
        bounds: { x: -margin.x, y: -margin.y, width: width + 2 * margin.x, height: height + 2 * margin.y },
        x: x.range([0, width]),
        y: y.range([height, 0]),
    };
}

/* Where each plotted node goes: React Flow places a node by its top-left corner, so it is moved back by half
   its size to sit centred on its point. */
export function analysisPositions(nodes, scales, metric, style) {
    const positions = new Map();
    nodes.filter(isPlotted).forEach((node) => {
        const width = style === "simple" ? DOT : node.measured?.width ?? CARD.width;
        const height = style === "simple" ? DOT : node.measured?.height ?? CARD.height;
        positions.set(node.id, {
            x: scales.x(driftOf(node)) - width / 2,
            y: scales.y(errorOf(node, metric)) - height / 2,
        });
    });
    return positions;
}

/* Each drawn node's colour: its top-level branch's, or grey for root. The branch is found by walking up the
   real graph, so a node whose parent is folded into a run still finds it. Branches are coloured in the order
   their first node was made, which their ids sort by, so the colours are stable. */
export function branchColors(nodes, serverNodesById) {
    const byId = serverNodesById ?? {};
    const branchOf = (id) => {
        let current = id;
        for (let guard = 0; guard < 1000; guard += 1) {
            const parent = byId[current]?.data?.parent;
            if (!parent || parent === "root" || !byId[parent]) return null;
            if (byId[parent].data?.parent === "root") return current;
            current = parent;
        }
        return null;
    };

    const branches = new Map(nodes.filter(isPlotted).map((node) => [node.id, branchOf(tableOf(node))]));
    const order = [...new Set([...branches.values()].filter(Boolean))].sort();

    const colors = new Map();
    for (const [id, branch] of branches) {
        if (branch == null) {
            colors.set(id, ROOT_COLOR);
        } else {
            colors.set(id, BRANCH_COLORS[order.indexOf(branch) % BRANCH_COLORS.length]);
        }
    }
    return colors;
}

// The line a node's hover adds for its part in the comparison, if it has one
const ROLE_NOTES = {
    current: "<br/><em>current node (selection B)</em>",
    "selection-a": "<br/><em>selection A</em>",
};

/* A node's hover text in analysis mode: its numbers on both axes, how big it is, and where it stands.
   role is "current" or "selection-a"; dominator names the node that beats it outright, if any. */
export function analysisTooltip(node, metric, { role, dominator }) {
    let name;
    let wrangle = null;
    if (node.type === "collapsedNode") {
        name = `${nodeName(node.data.head)} … ${nodeName(node.data.tail)} (${node.data.run?.length} steps)`;
    } else {
        name = nodeName(node.id);
        wrangle = describeWrangle(node.data?.wrangle);
    }

    let heading = `<strong>${name}</strong>`;
    if (wrangle) heading += ` · ${wrangle}`;

    let errorName = "error";
    if (metric !== "total") errorName = METRIC_LABELS[metric].toLowerCase();

    const rows = node.data?.metrics?.row_count?.toLocaleString() ?? "—";
    const roleNote = ROLE_NOTES[role] ?? "";

    let beaten = "";
    if (dominator) {
        beaten = `<br/><em>dominated by ${nodeName(dominator)}: no worse on error or drift, and better on at least one</em>`;
    }

    return heading
        + `<br/>${errorName}: ${asPercent(errorOf(node, metric))}`
        + `<br/>drift: ${formatDrift(driftOf(node))}`
        + `<br/>rows: ${rows}`
        + roleNote + beaten
        + "<br/><span class='analysis-hint'>double-click to go here · shift-click for selection A</span>";
}
