// ComparisonPlot.jsx
// Draws two nodes' data against each other for the compare modal. The data arrives from
// /api/pgraph/compare already binned on axes both states share - see app/pgraph/compare.py - so every
// view here can put the two on the same scales.

import {useCallback, useEffect, useId, useMemo, useRef, useState} from "react";
import * as d3 from "d3";
import RidgelineBrush, {RIDGE_HEADROOM, STRIP_CHROME} from "./RidgelineBrush.jsx";
import SankeyMinimap from "./SankeyMinimap.jsx";
import {FLOW_COLORS, flowKind, isStub, layoutFlows, markedFlow, panRange, ribbonPath, ribbonPoint, zoomFlows} from "./flowLayout.js";
import {createHybridScales} from "../utils/visCommon.jsx";
import {ERROR_DIMENSIONS, errorColors} from "../store/errorColors.js";
import {
    FLOW_SIDES, MEASURES, OTHER_LABEL, REMOVED_LABEL, ROLE_COLORS, ROLE_NAMES,
    flowCategories, flowSides, measureOf, nodeName,
} from "../utils/comparison.js";
import {NULL_FLAG_TITLE, formatDrift} from "../utils/drift.js";

/* A difference is colored by what it means. Rows gained or lost are neither good nor bad, so they get
   a neutral pair; errors going down is an improvement, and gets the attribute panel's green. */
const DIFFERENCE_COLORS = {
    rows: {fewer: "#7c4dff", more: "#e8710a"},
    errors: {fewer: "#1a7f37", more: "#c1121f"},
};

// A tile that exists but measures zero - distinct from the white of no data at all
const NEUTRAL = "#eef0f2";

const MARGIN = {top: 34, right: 18, bottom: 72, left: 76};
const PANEL_GAP = 28;
const TOOLTIP_GAP = 12;
// Below this the canvas is mid-resize or collapsed, and there is nothing useful to lay out
const MIN_CANVAS = 120;

const formatCount = d3.format(",");
const formatDelta = (value) => (value > 0 ? `+${formatCount(value)}` : formatCount(value));
const formatValue = (value) => (Math.abs(value) >= 1e4 ? d3.format(".3~s")(value) : d3.format(".4~g")(value));

// Category labels are the user's data, and tooltips are set as html
function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => (
        {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character]
    ));
}

const differenceColors = (measure) => (measure === "items" ? DIFFERENCE_COLORS.rows : DIFFERENCE_COLORS.errors);

/* Darker means more of the measure. Zero gets NEUTRAL rather than the ramp's pale end, so a tile whose
   rows carry no flags still reads as occupied. */
function sequentialColor(measure, peak) {
    const ramp = measure === "items" ? (t) => d3.interpolateBlues(0.15 + 0.85 * t)
        : measure === "errors" ? (t) => d3.interpolateOrRd(0.15 + 0.85 * t)
            : (t) => d3.interpolateRgb("#f3f3f3", errorColors(measure))(0.2 + 0.8 * t);
    return (value) => (value > 0 ? ramp(Math.min(1, value / peak)) : NEUTRAL);
}

function divergingColor(measure, extent) {
    const {fewer, more} = differenceColors(measure);
    return (delta) => (delta === 0
        ? NEUTRAL
        : d3.interpolateRgb(NEUTRAL, delta > 0 ? more : fewer)(0.25 + 0.75 * Math.min(1, Math.abs(delta) / extent)));
}

// ── Tooltip ──────────────────────────────────────────────────────────────────

/* The modal sits above the app's shared #tooltip, so the plot keeps its own. It is placed within the
   canvas, and flips away from whichever edge it would run off. */
function makeTooltip(element, container) {
    const place = (event) => {
        const bounds = container.getBoundingClientRect();
        const x = event.clientX - bounds.left;
        const y = event.clientY - bounds.top;
        const {offsetWidth: width, offsetHeight: height} = element;
        const left = x + TOOLTIP_GAP + width > bounds.width ? x - TOOLTIP_GAP - width : x + TOOLTIP_GAP;
        const top = y + TOOLTIP_GAP + height > bounds.height ? y - TOOLTIP_GAP - height : y + TOOLTIP_GAP;
        element.style.left = `${Math.max(0, left)}px`;
        element.style.top = `${Math.max(0, top)}px`;
    };
    const hide = () => {
        element.style.display = "none";
    };

    return {
        hide,
        // For content that follows the pointer, as a crosshair's does, rather than one mark's fixed text
        show(event, html) {
            element.innerHTML = html;
            element.style.display = "block";
            place(event);
        },
        attach(selection, html) {
            selection
                .on("mouseover", (event, d) => {
                    element.innerHTML = html(d);
                    element.style.display = "block";
                    place(event);
                    d3.select(event.currentTarget).classed("compare-mark--hover", true);
                })
                .on("mousemove", place)
                .on("mouseout", (event) => {
                    hide();
                    d3.select(event.currentTarget).classed("compare-mark--hover", false);
                });
        },
    };
}

const swatch = (color) => `<span class="compare-tooltip-swatch" style="background:${color}"></span>`;

function countLine(role, ctx, count) {
    const flags = ERROR_DIMENSIONS
        .filter((type) => count?.[type])
        .map((type) => `${formatCount(count[type])} ${MEASURES[type].noun}`);
    return `${swatch(ROLE_COLORS[role])}${ROLE_NAMES[role]} ${escapeHtml(ctx.labels[role])}: `
        + `<strong>${formatCount(count?.items ?? 0)}</strong> rows${flags.length ? ` (${flags.join(", ")})` : ""}`;
}

function countsTooltip(title, datum, ctx) {
    return `<strong>${escapeHtml(title)}</strong><br>`
        + `${countLine("a", ctx, datum.a)}<br>${countLine("b", ctx, datum.b)}`;
}

function differenceTooltip(title, datum, ctx) {
    const before = measureOf(datum.a, ctx.measure);
    const after = measureOf(datum.b, ctx.measure);
    return `<strong>${escapeHtml(title)}</strong><br>`
        + `${MEASURES[ctx.measure].label}: ${formatCount(before)} → ${formatCount(after)} `
        + `(<strong>${formatDelta(after - before)}</strong>)<br>`
        + `${countLine("a", ctx, datum.a)}<br>${countLine("b", ctx, datum.b)}`;
}

// ── Scales and geometry ──────────────────────────────────────────────────────

/* The shared hybrid scale, fed the shape the backend sends for binned axes: numeric bin edges, then
   categorical labels. */
function binScale(scale, size, direction) {
    const numeric = scale.numeric ?? [];
    const categorical = scale.categorical ?? [];
    const numericDomain = numeric.length ? [numeric[0].x0, numeric[numeric.length - 1].x1] : null;
    return createHybridScales(size, numeric, categorical, numericDomain,
        categorical.length ? categorical : null, direction);
}

function spanX(xScale, scale, datum) {
    if (datum.xType === "numeric") {
        const {x0, x1} = scale.numeric[datum.xBin];
        return {x: xScale.apply(x0, "numeric"), w: xScale.numericalBandwidth(x0, x1)};
    }
    return {x: xScale.apply(datum.xBin, "categorical"), w: xScale.categoricalBandwidth()};
}

// The vertical scale runs bottom to top, so a numeric bin's top edge is its x1
function spanY(yScale, scale, datum) {
    if (datum.yType === "numeric") {
        const {x0, x1} = scale.numeric[datum.yBin];
        return {y: yScale.apply(x1, "numeric"), h: yScale.numericalBandwidth(x1, x0)};
    }
    return {y: yScale.apply(datum.yBin, "categorical"), h: yScale.categoricalBandwidth()};
}

function binLabel(scale, type, bin) {
    if (type !== "numeric") return String(bin);
    const {x0, x1} = scale.numeric[bin];
    return `${formatValue(x0)} – ${formatValue(x1)}`;
}

const tileLabel = (data, tile) => `${data.x}: ${binLabel(data.scaleX, tile.xType, tile.xBin)} · `
    + `${data.y}: ${binLabel(data.scaleY, tile.yType, tile.yBin)}`;

// ── Frames ───────────────────────────────────────────────────────────────────

/* Split the canvas into side-by-side plot areas, each with room for its own axes. */
function layoutPanels(svg, width, height, count) {
    const slot = (width - PANEL_GAP * (count - 1)) / count;
    return d3.range(count).map((i) => ({
        g: svg.append("g").attr("transform", `translate(${i * (slot + PANEL_GAP) + MARGIN.left}, ${MARGIN.top})`),
        w: Math.max(10, slot - MARGIN.left - MARGIN.right),
        h: Math.max(10, height - MARGIN.top - MARGIN.bottom),
    }));
}

// Draws one colored chip and its label, returning where the next one can start
function titleChip(title, x, role, text) {
    title.append("rect")
        .attr("x", x).attr("y", -9).attr("width", 10).attr("height", 10).attr("rx", 2)
        .attr("fill", ROLE_COLORS[role]);
    const label = title.append("text").attr("x", x + 16).text(text);
    return x + 16 + label.node().getComputedTextLength() + 18;
}

function panelTitle(g, role, ctx) {
    const title = g.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -14)");
    titleChip(title, 0, role, `${ROLE_NAMES[role]} · ${ctx.labels[role]}`);
}

function pairTitle(g, ctx) {
    const title = g.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -14)");
    const next = titleChip(title, 0, "a", `${ROLE_NAMES.a} · ${ctx.labels.a}`);
    titleChip(title, next, "b", `${ROLE_NAMES.b} · ${ctx.labels.b}`);
}

/* createHybridScales draws its x axis at y = size, which assumes a square plot. These panels are not
   square, so the axis goes into a group shifted by the difference, landing it on the panel's floor. */
function drawXAxis(g, xScale, w, h) {
    xScale.draw(g.append("g").attr("class", "compare-axis").attr("transform", `translate(0, ${h - w})`));
}

function drawYAxis(g, yScale) {
    yScale.draw(g.append("g").attr("class", "compare-axis"));
}

function drawCountAxis(g, y, format = formatCount) {
    g.append("g").attr("class", "compare-axis")
        .call(d3.axisLeft(y).ticks(5).tickFormat(format))
        .selectAll("text").attr("class", "left-axis-text");
}

function axisLabels(g, w, h, xLabel, yLabel) {
    g.append("text").attr("class", "compare-axis-label")
        .attr("x", w / 2).attr("y", h + MARGIN.bottom - 10).attr("text-anchor", "middle")
        .text(xLabel);
    if (yLabel) {
        g.append("text").attr("class", "compare-axis-label")
            .attr("transform", `translate(${14 - MARGIN.left}, ${h / 2}) rotate(-90)`)
            .attr("text-anchor", "middle")
            .text(yLabel);
    }
}

// ── Histograms ───────────────────────────────────────────────────────────────

/* One bar's stack: error flags from the top down, clean rows beneath - the main histograms' order. */
function stackSegments(count) {
    const segments = [];
    let top = count.items;
    ERROR_DIMENSIONS.forEach((type) => {
        const value = count[type] ?? 0;
        if (!value) return;
        segments.push({type, top, bottom: Math.max(0, top - value)});
        top -= value;
    });
    if (top > 0) segments.push({type: "none", top, bottom: 0});
    return segments;
}

function drawHistogramSide(svg, data, ctx) {
    // One y domain for both panels, or bars of equal height would not be equal counts
    const peak = d3.max(data.bins, (bin) => Math.max(bin.a.items, bin.b.items)) || 1;

    layoutPanels(svg, ctx.width, ctx.height, 2).forEach(({g, w, h}, i) => {
        const role = i === 0 ? "a" : "b";
        const xScale = binScale(data.scaleX, w, "horizontal");
        const y = d3.scaleLinear().domain([0, peak]).nice().range([h, 0]);

        const segments = data.bins.flatMap((bin) => stackSegments(bin[role]).map((segment) => ({...segment, bin})));
        const bars = g.append("g").selectAll("rect").data(segments).join("rect")
            .attr("class", "compare-mark")
            .attr("x", (d) => spanX(xScale, data.scaleX, d.bin).x)
            .attr("width", (d) => Math.max(0, spanX(xScale, data.scaleX, d.bin).w - 1))
            .attr("y", (d) => y(d.top))
            .attr("height", (d) => Math.max(0, y(d.bottom) - y(d.top)))
            .attr("fill", (d) => errorColors(d.type))
            .attr("stroke", "white")
            .attr("stroke-width", 0.5);
        ctx.tooltip.attach(bars, (d) => countsTooltip(binLabel(data.scaleX, d.bin.xType, d.bin.xBin), d.bin, ctx));

        drawXAxis(g, xScale, w, h);
        drawCountAxis(g, y);
        panelTitle(g, role, ctx);
        axisLabels(g, w, h, data.x, i === 0 ? "Rows" : null);
    });
}

function drawHistogramOverlay(svg, data, ctx) {
    const [{g, w, h}] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const peak = d3.max(data.bins, (bin) => Math.max(bin.a.items, bin.b.items)) || 1;
    const y = d3.scaleLinear().domain([0, peak]).nice().range([h, 0]);

    // Each bin is split down the middle: selection A's bar on the left, selection B's on the right
    const bars = data.bins.flatMap((bin) => [{bin, role: "a"}, {bin, role: "b"}]);
    const marks = g.append("g").selectAll("rect").data(bars).join("rect")
        .attr("class", "compare-mark")
        .attr("x", (d) => {
            const span = spanX(xScale, data.scaleX, d.bin);
            return span.x + (d.role === "a" ? 1 : span.w / 2);
        })
        .attr("width", (d) => Math.max(0, spanX(xScale, data.scaleX, d.bin).w / 2 - 1))
        .attr("y", (d) => y(d.bin[d.role].items))
        .attr("height", (d) => Math.max(0, h - y(d.bin[d.role].items)))
        .attr("fill", (d) => ROLE_COLORS[d.role])
        .attr("fill-opacity", 0.85);
    ctx.tooltip.attach(marks, (d) => countsTooltip(binLabel(data.scaleX, d.bin.xType, d.bin.xBin), d.bin, ctx));

    drawXAxis(g, xScale, w, h);
    drawCountAxis(g, y);
    pairTitle(g, ctx);
    axisLabels(g, w, h, data.x, "Rows");
}

function drawHistogramDifference(svg, data, ctx) {
    const [{g, w, h}] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const deltas = data.bins.map((bin) => ({
        bin,
        delta: measureOf(bin.b, ctx.measure) - measureOf(bin.a, ctx.measure),
    }));
    // Symmetric about zero, so a gain and a loss of the same size are bars of the same length
    const extent = d3.max(deltas, (d) => Math.abs(d.delta)) || 1;
    const y = d3.scaleLinear().domain([-extent, extent]).nice().range([h, 0]);
    const {fewer, more} = differenceColors(ctx.measure);

    g.append("g").selectAll("rect").data(deltas.filter((d) => d.delta !== 0)).join("rect")
        .attr("x", (d) => spanX(xScale, data.scaleX, d.bin).x)
        .attr("width", (d) => Math.max(0, spanX(xScale, data.scaleX, d.bin).w - 1))
        .attr("y", (d) => y(Math.max(0, d.delta)))
        .attr("height", (d) => Math.abs(y(d.delta) - y(0)))
        .attr("fill", (d) => (d.delta > 0 ? more : fewer));
    g.append("line").attr("class", "compare-zero").attr("x1", 0).attr("x2", w).attr("y1", y(0)).attr("y2", y(0));

    // Full-height hit areas, so a bin that did not change can still be hovered for its numbers
    const hits = g.append("g").selectAll("rect").data(deltas).join("rect")
        .attr("class", "compare-hit")
        .attr("x", (d) => spanX(xScale, data.scaleX, d.bin).x)
        .attr("width", (d) => Math.max(0, spanX(xScale, data.scaleX, d.bin).w))
        .attr("y", 0)
        .attr("height", h);
    ctx.tooltip.attach(hits, (d) => differenceTooltip(binLabel(data.scaleX, d.bin.xType, d.bin.xBin), d.bin, ctx));

    drawXAxis(g, xScale, w, h);
    drawCountAxis(g, y, formatDelta);
    pairTitle(g, ctx);
    axisLabels(g, w, h, data.x, `Change in ${MEASURES[ctx.measure].noun}`);
}

// ── Heatmaps ─────────────────────────────────────────────────────────────────

function drawTiles(g, data, xScale, yScale, tiles) {
    return g.append("g").selectAll("rect").data(tiles).join("rect")
        .attr("class", "compare-mark")
        .attr("x", (tile) => spanX(xScale, data.scaleX, tile).x)
        .attr("width", (tile) => Math.max(0, spanX(xScale, data.scaleX, tile).w))
        .attr("y", (tile) => spanY(yScale, data.scaleY, tile).y)
        .attr("height", (tile) => Math.max(0, spanY(yScale, data.scaleY, tile).h))
        .attr("stroke", "white")
        .attr("stroke-width", 1);
}

function drawHeatmapSide(svg, data, ctx) {
    // One color scale for both panels, so equal shades are equal counts
    const peak = d3.max(data.tiles, (tile) => Math.max(
        measureOf(tile.a, ctx.measure), measureOf(tile.b, ctx.measure))) || 1;
    const fill = sequentialColor(ctx.measure, peak);

    layoutPanels(svg, ctx.width, ctx.height, 2).forEach(({g, w, h}, i) => {
        const role = i === 0 ? "a" : "b";
        const xScale = binScale(data.scaleX, w, "horizontal");
        const yScale = binScale(data.scaleY, h, "vertical");

        const tiles = drawTiles(g, data, xScale, yScale, data.tiles.filter((tile) => tile[role].items > 0))
            .attr("fill", (tile) => fill(measureOf(tile[role], ctx.measure)));
        ctx.tooltip.attach(tiles, (tile) => countsTooltip(tileLabel(data, tile), tile, ctx));

        drawXAxis(g, xScale, w, h);
        drawYAxis(g, yScale);
        panelTitle(g, role, ctx);
        axisLabels(g, w, h, data.x, data.y);
    });
}

function drawHeatmapDifference(svg, data, ctx) {
    const [{g, w, h}] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const yScale = binScale(data.scaleY, h, "vertical");
    const delta = (tile) => measureOf(tile.b, ctx.measure) - measureOf(tile.a, ctx.measure);
    const extent = d3.max(data.tiles, (tile) => Math.abs(delta(tile))) || 1;
    const fill = divergingColor(ctx.measure, extent);

    const tiles = drawTiles(g, data, xScale, yScale, data.tiles).attr("fill", (tile) => fill(delta(tile)));
    ctx.tooltip.attach(tiles, (tile) => differenceTooltip(tileLabel(data, tile), tile, ctx));

    drawXAxis(g, xScale, w, h);
    drawYAxis(g, yScale);
    pairTitle(g, ctx);
    axisLabels(g, w, h, data.x, data.y);
}

// ── Drift ────────────────────────────────────────────────────────────────────
// Each node against root, from /api/pgraph/drift_detail - see app/pgraph/distortion.py. Drift is a cost,
// not an error, so none of these views colors it good or bad: red is kept for the null test's flag.
// The modal can measure from the two selections' common ancestor instead, so the reference is named by
// ctx.labels.base wherever the reader sees it; "root" in the code below means whichever state that is.

const ROOT_COLOR = "#8c939d";
const FLAG_COLOR = "#d1242f";
// Room at the right of a ridgeline for each row's drift
const DRIFT_GUTTER = 72;
// The gap between the ridgeline's rows, as a share of a row - root's row below is sized to match one
const RIDGE_PADDING = 0.12;
// The gap between the canvas and the strip under it, as .compare-plot-body sets it
const BODY_GAP = 8;
// Root's row never shrinks below this, however small the modal
const MIN_STRIP_CURVE = 40;
/* Where a curve is under this share of root's peak, it is too thin to divide by: out in the empty tails every
   curve is near zero, and a ratio of two near-zeros is noise */
const THIN_SHARE = 0.005;
// Root's box in the middle of the flows, which carries each category's name and root's count
const ROOT_BOX = 140;
// Room beside each node's column for its counts, and its removed sink's label
const COUNT_ROOM = 96;
// A node's category bars
const FLOW_NODE = 10;
// A label is kept this far inside the visible part of its band, so a category cut by the plot's edge is named
const LABEL_INSET = 7;
// How many of the catch-all's categories its tooltip names before summing up the rest
const OTHER_LISTED = 12;

// Which kind of column each drift view draws, so a result for the last column is never drawn as the next
const DRIFT_VIEW_KINDS = {ridgeline: "numeric", flows: "categorical"};

const formatShare = d3.format(".1%");

// The annotation bubble's radius, and how far it sits from the spot it points at
const BUBBLE_R = 11;
const BUBBLE_REACH = 34;

/* Where a node's rows changed most - the grid index its annotation bubble points at.

   A node's curve is kept at its share of root's rows rather than rescaled, so root's curve minus the node's
   is the smoothed shape of the rows removed - and, below zero, of the values filled in. Its peak is where
   most rows changed. Rescaling the two to one total first would ask where the shape changed instead, and
   that lands on the peak whenever rows leave a thin tail: the bulk lifts a little, and a little on the
   tallest part of the curve outweighs the whole tail.

   Thinning the whole column shared - rows lost to a step on another column, say - is taken out first, or
   it would win at the peak every time. It is the smallest share any well-populated part of the column
   lost. A node that changed nothing points at its own peak. */
function mostChanged(root, curve) {
    const peak = d3.max(root) || 1;
    const gap = curve.map((value, i) => root[i] - value);
    if (d3.max(gap, (value) => Math.abs(value)) < 1e-9 * peak) return d3.maxIndex(curve);

    const busy = d3.range(root.length).filter((i) => root[i] >= 0.01 * peak);
    const shared = Math.min(Math.max(d3.min(busy, (i) => gap[i] / root[i]) ?? 0, 0), 1);
    return d3.maxIndex(gap, (value, i) => Math.abs(value - shared * root[i]));
}

/* A thought bubble pinned beside the place a node's data actually moved, with an arrow to that place. The
   annotation used to be a paragraph under the plot, which left the reader to work out which part of the
   picture it described; hovering the bubble puts it next to that part instead. aside is appended to the
   sentences - a zoomed ridgeline uses it to say the spot is outside the range shown. */
function drawAnnotationBubble(g, {ax, ay, bounds, aside}, role, side, ctx) {
    const sentences = side?.annotation?.sentences ?? [];
    if (!sentences.length) return;

    const color = ROLE_COLORS[role];
    // Up and to the right of the spot, but never outside the panel it belongs to
    const bx = Math.min(Math.max(ax + BUBBLE_REACH, bounds.left + BUBBLE_R), bounds.right - BUBBLE_R);
    const by = Math.min(Math.max(ay - BUBBLE_REACH, bounds.top + BUBBLE_R), bounds.bottom - BUBBLE_R);
    const at = (t) => [bx + (ax - bx) * t, by + (ay - by) * t];
    const angle = Math.atan2(ay - by, ax - bx);
    const back = [ax - Math.cos(angle) * 9, ay - Math.sin(angle) * 9];
    const corner = (turn) => [back[0] + Math.cos(angle + turn) * 4.5, back[1] + Math.sin(angle + turn) * 4.5];

    const group = g.append("g").attr("class", "compare-bubble");
    group.append("line")
        .attr("x1", at(0.62)[0]).attr("y1", at(0.62)[1]).attr("x2", back[0]).attr("y2", back[1])
        .attr("stroke", color).attr("stroke-width", 1.4);
    group.append("polygon")
        .attr("points", [[ax, ay], corner(Math.PI / 2), corner(-Math.PI / 2)].map((point) => point.join(",")).join(" "))
        .attr("fill", color);
    // The two puffs that make it a thought bubble rather than a speech balloon
    [[0.26, 4], [0.46, 2.5]].forEach(([t, r]) => {
        const [px, py] = at(t);
        group.append("circle").attr("cx", px).attr("cy", py).attr("r", r)
            .attr("fill", "#ffffff").attr("stroke", color).attr("stroke-width", 1.2);
    });
    group.append("circle").attr("cx", bx).attr("cy", by).attr("r", BUBBLE_R)
        .attr("fill", "#ffffff").attr("stroke", color).attr("stroke-width", 1.6);
    group.append("text").attr("class", "compare-bubble-mark")
        .attr("x", bx).attr("y", by).attr("text-anchor", "middle").attr("dominant-baseline", "central")
        .attr("fill", color).text("i");

    /* The sentences go to the readout under the plot rather than to a tooltip over it: they run to a few
       lines, and a floating panel would cover the very spot the bubble is pointing at. */
    group
        .on("mouseover", () => {
            group.classed("compare-bubble--hover", true);
            ctx.showNote?.({role, label: ctx.labels[role], text: [...sentences, aside].filter(Boolean).join(" ")});
        })
        .on("mouseout", () => {
            group.classed("compare-bubble--hover", false);
            ctx.showNote?.(null);
        });
}

/* The column's shape in selection A and selection B: one row each on a shared axis, with root's own row
   in the strip beneath, which is also the zoom control. Every curve is smoothed with the bandwidth fitted on
   root, and root is drawn dashed over every row - where the dashed line vanishes under the fill, nothing
   moved. The rows share one vertical scale too, so a node that lost rows draws a smaller curve rather than a
   renormalised one.

   ctx.range zooms the plot to part of the column, chosen on the strip beneath it. The vertical scale then
   fits the tallest curve inside the window rather than the column's, which is what makes a change in a thin
   tail visible - both rows still share it, so they stay comparable. */
function drawRidgeline(svg, data, ctx) {
    const density = data.a.density ?? data.b.density;
    if (!density) return drawEmpty(svg, ctx, "This column has too few distinct values to draw its shape");

    const rows = [
        {
            key: "a", label: ctx.labels.a, curve: data.a.density?.node, color: ROLE_COLORS.a,
            drift: data.a.distortion?.value, flag: data.a.null
        },
        {
            key: "b", label: ctx.labels.b, curve: data.b.density?.node, color: ROLE_COLORS.b,
            drift: data.b.distortion?.value, flag: data.b.null
        },
    ];

    const [{g, w, h}] = layoutPanels(svg, ctx.width - DRIFT_GUTTER, ctx.height, 1);
    const grid = density.grid;
    const [lo, hi] = ctx.range ?? [grid[0], grid[grid.length - 1]];
    const x = d3.scaleLinear().domain([lo, hi]).range([0, w]);
    const band = d3.scaleBand().domain(rows.map((row) => row.key)).range([0, h]).paddingInner(RIDGE_PADDING);

    // The grid points inside the window, and one either side so each curve runs to the window's edges
    const visible = d3.range(Math.max(0, d3.bisectLeft(grid, lo) - 1), Math.min(grid.length, d3.bisectRight(grid, hi) + 1));
    // Root is still drawn full size on every row, so it has a say in the scale though it has no row
    const curves = [density.root, ...rows.map((row) => row.curve).filter(Boolean)];
    const peak = d3.max(curves.flatMap((curve) => visible.map((i) => curve[i]))) || 1;
    const rise = (value) => (value / peak) * band.bandwidth() * RIDGE_HEADROOM;

    // The points either side of the window would otherwise draw into the margins
    const clip = `url(#${ctx.clipId})`;
    g.append("clipPath").attr("id", ctx.clipId).append("rect").attr("width", w).attr("height", h);

    /* The hover surface, as the visx areas demo builds it: a transparent bar over the plot takes the pointer.
       It goes in first, under the rows, whose curves let the pointer through to it - so the annotation bubbles,
       drawn with the rows, stay on top and keep their own hover. */
    const hover = g.append("rect").attr("class", "compare-ridge-hover").attr("width", w).attr("height", h);

    /* Each row sits on a faint wash of its own node's colour, under everything else. Zoomed in, the curves run
       flat and the lines crowd, and a row can hold no fill at all - the wash still shows where it ends. */
    rows.forEach((row) => {
        g.insert("rect", ".compare-ridge-hover").attr("class", "compare-ridge-band")
            .attr("y", band(row.key)).attr("width", w).attr("height", band.bandwidth())
            .attr("fill", row.color);
    });

    rows.forEach((row) => {
        const floor = band(row.key) + band.bandwidth();
        const middle = floor - band.bandwidth() / 2;
        const rowGroup = g.append("g").attr("class", "compare-ridge-row");

        rowGroup.append("line").attr("class", "compare-ridge-floor").attr("x1", 0).attr("x2", w).attr("y1", floor).attr("y2", floor);

        // The row's own node, filled
        if (row.curve) {
            rowGroup.append("path").datum(visible)
                .attr("d", d3.area().x((i) => x(grid[i])).y0(floor).y1((i) => floor - rise(row.curve[i])))
                .attr("clip-path", clip)
                .attr("fill", row.color).attr("fill-opacity", 0.5)
                .attr("stroke", row.color).attr("stroke-width", 1.2);
        }
        // Root's dashed line over it, so it is never lost under the fill
        rowGroup.append("path").datum(visible)
            .attr("d", d3.line().x((i) => x(grid[i])).y((i) => floor - rise(density.root[i])))
            .attr("clip-path", clip)
            .attr("class", "compare-ridge-root");

        rowGroup.append("text").attr("class", "compare-ridge-label")
            .attr("x", -8).attr("y", middle).attr("text-anchor", "end").attr("dominant-baseline", "middle")
            .attr("fill", row.color).text(row.label);
        const drift = rowGroup.append("text").attr("class", "compare-ridge-drift")
            .attr("x", w + 10).attr("y", middle).attr("dominant-baseline", "middle").text(formatDrift(row.drift));
        if (row.flag?.flagged) drift.append("tspan").attr("fill", FLAG_COLOR).text(" ▲").append("title").text(NULL_FLAG_TITLE);

        /* Each row's annotation is about its own node, at full scale. The spot is found on the whole curve,
           zoomed or not; when the window leaves it out, the bubble is pinned to the edge of the row nearest it,
           pointing off the plot. The arrow meets whichever curve is higher there - root's dashed line where
           rows were removed, the node's own where values were filled in. */
        if (row.curve) {
            const spot = mostChanged(density.root, row.curve);
            const at = grid[spot];
            const shown = at >= lo && at <= hi;
            drawAnnotationBubble(rowGroup, {
                ax: shown ? x(at) : (at < lo ? 0 : w),
                ay: shown ? floor - rise(Math.max(row.curve[spot], density.root[spot])) : middle,
                bounds: {left: 0, right: w, top: band(row.key), bottom: floor},
                aside: shown ? null : `(That spot, near ${formatValue(at)}, is ${at < lo ? "left" : "right"} of the range shown.)`,
            }, row.key, data[row.key], ctx);
        }
    });

    g.append("text").attr("class", "compare-axis-label").attr("x", w + 10).attr("y", -14).text("drift");
    g.append("g").attr("class", "compare-axis").attr("transform", `translate(0, ${h})`)
        .call(d3.axisBottom(x).ticks(6).tickFormat(d3.format(".3~s"))).selectAll("text").attr("class", "bottom-axis-text");
    axisLabels(g, w, h, ctx.range ? `${data.x} · zoomed to ${formatValue(lo)} – ${formatValue(hi)}` : data.x, null);

    drawRidgeCrosshair(g, hover, {rows, density, x, band, rise, w, h, lo, hi}, ctx);
}

/* The crosshair over the ridgeline, piece for piece as the visx areas demo builds its own: the pointer's x is
   turned back into a value and snapped by a bisector to the nearest grid point; a dashed line runs down both
   rows there; each row's own curve gets the demo's shadowed circle, and root's full-size dash a small hollow
   one; the value sits in a label pinned to the axis, and the shares at it in the tooltip beside the pointer.
   It is drawn last, over the curves, and never takes the pointer itself. */
function drawRidgeCrosshair(g, hover, {rows, density, x, band, rise, w, h, lo, hi}, ctx) {
    const grid = density.grid;
    const bisect = d3.bisector((value) => value).left;
    // Only grid points inside the window can be snapped to, so the crosshair never leaves the plot
    const first = d3.bisectLeft(grid, lo);
    const last = Math.max(first, d3.bisectRight(grid, hi) - 1);
    const rootPeak = d3.max(density.root) || 1;

    const crosshair = g.append("g").attr("class", "compare-ridge-crosshair").attr("display", "none");
    const line = crosshair.append("line").attr("y1", 0).attr("y2", h);
    const marks = rows.filter((row) => row.curve).map((row) => {
        const floor = band(row.key) + band.bandwidth();
        const root = crosshair.append("circle").attr("class", "compare-ridge-crosshair-root").attr("r", 3);
        const shadow = crosshair.append("circle").attr("class", "compare-ridge-crosshair-shadow").attr("r", 4);
        const dot = crosshair.append("circle").attr("class", "compare-ridge-crosshair-dot").attr("r", 4)
            .attr("fill", row.color);
        return {row, floor, root, shadow, dot};
    });
    const label = crosshair.append("g").attr("transform", `translate(0, ${h})`);
    const labelBox = label.append("rect").attr("class", "compare-ridge-crosshair-box").attr("y", 2).attr("height", 18).attr("rx", 4);
    const labelText = label.append("text").attr("class", "compare-ridge-crosshair-value")
        .attr("y", 11).attr("text-anchor", "middle").attr("dominant-baseline", "middle");

    hover
        .on("pointermove", (event) => {
            // The nearer of the two grid points either side of the pointer, as the demo picks its data point
            const x0 = x.invert(d3.pointer(event, g.node())[0]);
            const index = bisect(grid, x0, 1);
            const nearer = index >= grid.length || x0 - grid[index - 1] < grid[index] - x0 ? index - 1 : index;
            const i = Math.min(Math.max(nearer, first), last);
            const cx = x(grid[i]);

            crosshair.attr("display", null);
            line.attr("x1", cx).attr("x2", cx);
            marks.forEach(({row, floor, root, shadow, dot}) => {
                const cy = floor - rise(row.curve[i]);
                root.attr("cx", cx).attr("cy", floor - rise(density.root[i]));
                shadow.attr("cx", cx).attr("cy", cy + 1);
                dot.attr("cx", cx).attr("cy", cy);
            });
            labelText.attr("x", cx).text(formatValue(grid[i]));
            const width = labelText.node().getComputedTextLength() + 12;
            // Centred on the line, as the demo's date is, but kept inside the plot's width
            const left = Math.min(Math.max(cx - width / 2, 0), w - width);
            labelBox.attr("x", left).attr("width", width);
            labelText.attr("x", left + width / 2);

            ctx.tooltip.show(event, ridgeShares({
                i, rootPeak, root: density.root,
                curveA: rows.find((row) => row.key === "a").curve,
                curveB: rows.find((row) => row.key === "b").curve,
                labels: ctx.labels,
            }));
        })
        .on("pointerleave", () => {
            crosshair.attr("display", "none");
            ctx.tooltip.hide();
        });
}

/* The tooltip beside the crosshair: each node's density as a share of root's there, and each node's as a share
   of the other's. The curves are kept at their share of root's rows, so "61% of root" reads as having 61% as
   many rows as root near this value. A share whose denominator is too thin to divide by shows as a dash. */
function ridgeShares({i, rootPeak, root, curveA, curveB, labels}) {
    const share = (part, whole) => (whole >= THIN_SHARE * rootPeak ? formatShare(part / whole) : "—");
    const line = (html) => `${html}<br>`;
    const base = escapeHtml(labels.base);
    let html = "";
    if (curveA) html += line(`${swatch(ROLE_COLORS.a)}${escapeHtml(labels.a)} · <strong>${share(curveA[i], root[i])}</strong> of ${base}`);
    if (curveB) html += line(`${swatch(ROLE_COLORS.b)}${escapeHtml(labels.b)} · <strong>${share(curveB[i], root[i])}</strong> of ${base}`);
    if (curveA && curveB) {
        html += line(`${escapeHtml(labels.b)} · <strong>${share(curveB[i], curveA[i])}</strong> of ${escapeHtml(labels.a)}`);
        html += `${escapeHtml(labels.a)} · <strong>${share(curveA[i], curveB[i])}</strong> of ${escapeHtml(labels.b)}`;
    }
    return html.replace(/<br>$/, "");
}

/* Where the ridgeline's panel sits in a canvas this wide - the same panel layoutPanels gives drawRidgeline,
   so the overview strip beneath lines up with it exactly */
function ridgelineFrame(width) {
    return {left: MARGIN.left, width: Math.max(10, width - DRIFT_GUTTER - MARGIN.left - MARGIN.right), total: width};
}

/* How tall root's curves stand in the strip, so root's row matches each ridgeline row above it. The strip and the
   canvas share the body's height T. The canvas takes what the strip leaves, less its margins, and splits that
   between two rows and the gap between them, so a row is k·h with k = (1 − p) / (2 − p). With the strip's
   curve c set equal to a row:
       c = k·(T − gap − margins − chrome − c)   →   c = k·(T − gap − margins − chrome) / (1 + k) */
function ridgelineCurve(bodyHeight) {
    const k = (1 - RIDGE_PADDING) / (2 - RIDGE_PADDING);
    const room = bodyHeight - BODY_GAP - MARGIN.top - MARGIN.bottom - STRIP_CHROME;
    return Math.max(MIN_STRIP_CURVE, (k * room) / (1 + k));
}

/* What the overview strip draws for a drift result: the whole column's curves, and the spots the bubbles
   point at. Null for anything the ridgeline does not draw. */
function ridgelineOverview(data) {
    const density = data?.kind === "drift" ? (data.a.density ?? data.b.density) : null;
    if (!density) return null;
    const curves = {a: data.a.density?.node ?? null, b: data.b.density?.node ?? null};
    const spots = {
        a: curves.a && mostChanged(density.root, curves.a),
        b: curves.b && mostChanged(density.root, curves.b),
    };
    return {density, curves, spots};
}

/* Where the Sankey sits in a canvas this tall, so the minimap beside it lines up */
function flowsFrame(height) {
    return {top: MARGIN.top, height: Math.max(10, height - MARGIN.top - MARGIN.bottom), total: height};
}

/* The categories the Sankey draws: the ones the server sent, less any the reader has hidden. A hidden
   category keeps no band and takes no room; the ribbons that reached it are cut short instead. */
function shownCategories(data, hidden) {
    return flowCategories(data).filter((label) => !hidden.includes(label));
}

/* What the catch-all band holds, for its tooltip: the biggest categories folded into it with their rows, and
   a count of the rest. It is the one band that stands for several categories, so this is the only way to see
   what is inside it short of taking one back out. */
function otherTooltip(other) {
    const listed = other.categories.slice(0, OTHER_LISTED);
    const rest = other.categories.length - listed.length + other.more;
    return `<strong>${OTHER_LABEL}</strong> · ${formatCount(other.rows)} rows in `
        + `${formatCount(other.categories.length + other.more)} categories<br>`
        + listed.map((row) => `${escapeHtml(row.category)} · ${formatCount(row.rows)}`).join("<br>")
        + (rest > 0 ? `<br>and ${formatCount(rest)} more` : "");
}

// Along a ribbon from its middle outward, the order its annotation looks for a point still in sight
const RIBBON_STEPS = d3.range(11).flatMap((k) => (k ? [0.5 - k * 0.05, 0.5 + k * 0.05] : [0.5]));

/* One side's ribbons, from root's edge at x0 out to its own column at x1 - leftward for A. A ribbon cut short
   because its other category is hidden is drawn as a stub - see ribbonPath. */
function drawRibbons(g, side, {x0, x1, where, clip}, ctx) {
    const paths = g.append("g").attr("clip-path", clip)
        .selectAll("path").data(side.placed).join("path")
        .attr("class", (r) => `compare-mark ${isStub(r) ? "compare-flow-stub" : ""}`)
        .attr("d", (r) => ribbonPath(r, x0, x1))
        .attr("fill", (r) => FLOW_COLORS[flowKind(r)])
        .attr("fill-opacity", (r) => (isStub(r) ? 0.3 : flowKind(r) === "stayed" ? 0.35 : 0.7));
    ctx.tooltip.attach(paths, (r) => {
        const gone = [r.source, r.target].filter((label) => where(label) === "hidden");
        // A hidden source draws no band, so there is no total to take a share of
        const out = side.sources.get(r.source)?.rows;
        return `<strong>${escapeHtml(r.source)} → ${escapeHtml(r.target)}</strong><br>`
            + `${formatCount(r.rows)} rows from ${escapeHtml(ctx.labels.base)} into ${escapeHtml(ctx.labels[side.id])}`
            + (out ? ` · ${formatShare(r.rows / out)} of ${escapeHtml(ctx.labels.base)}'s ${escapeHtml(r.source)}` : "")
            + (gone.length ? `<br>${escapeHtml(gone.join(" and "))} hidden — add back from Categories` : "");
    });
}

/* A category's bar or box is what the reader clicks to pick it out, in any of the three columns, and Delete
   then hides it - the modal owns both, so the click only reports which category it was */
function pickable(rect, label, title, ctx) {
    rect.classed("compare-flow-node", true)
        .classed("compare-flow-node--selected", ctx.selected === label)
        .on("click", (event) => {
            // The canvas clears the selection, so a click that makes one must stop there
            event.stopPropagation();
            ctx.onSelect?.(ctx.selected === label ? null : label);
        })
        .append("title").text(`${title} — click to select, then press Delete to hide it`);
}

/* Where a node's label goes: the middle of its band, or of the part of it still in sight when the plot's edge
   cuts it, so a category scrolled half out of view is still named */
function labelY(n, h) {
    const top = Math.max(n.y0, 0);
    const bottom = Math.min(n.y1, h);
    if (bottom - top < 2 * LABEL_INSET) return (top + bottom) / 2;
    return Math.min(Math.max((n.y0 + n.y1) / 2, top + LABEL_INSET), bottom - LABEL_INSET);
}

/* A node's own column, out at the edge: a bar per category it holds, and its sink. Root's column names the
   category on the same band, so a bar here carries only its count. Only the nodes in sight are drawn. */
function drawNodeColumn(g, side, {bar, anchor, labelX, inView, width, h}, ctx) {
    const group = g.append("g");
    [...side.targets.values()].filter(inView).forEach((n) => {
        const removed = n.label === REMOVED_LABEL;
        const item = group.append("g");
        const rect = item.append("rect").attr("x", bar).attr("y", n.y0).attr("width", FLOW_NODE)
            .attr("height", Math.max(1, n.y1 - n.y0))
            .attr("fill", removed ? FLOW_COLORS.removed : "#475569");
        if (!removed) pickable(rect, n.label, `${n.label}: ${formatCount(n.rows)} rows in ${ctx.labels[side.id]}`, ctx);

        const text = item.append("text").attr("class", "compare-flow-label")
            .attr("x", labelX).attr("y", labelY(n, h)).attr("text-anchor", anchor).attr("dominant-baseline", "middle");
        if (removed) {
            text.classed("compare-flow-label--removed", true).append("tspan").text(REMOVED_LABEL);
            text.append("tspan").attr("class", "compare-flow-count").text(` ${formatCount(n.rows)}`);
            // Too long for the room beside the column, so the count goes under the name instead
            const box = text.node().getBBox();
            if (box.x < 0 || box.x + box.width > width) {
                text.selectAll("tspan").remove();
                text.append("tspan").attr("x", labelX).attr("dy", "-0.6em").text(REMOVED_LABEL);
                text.append("tspan").attr("class", "compare-flow-count").attr("x", labelX).attr("dy", "1.2em")
                    .text(formatCount(n.rows));
            }
            // The sink counts only the rows it takes from the categories shown, so it says when there are more
            if (n.total > n.rows) {
                ctx.tooltip.attach(item, () => `<strong>${REMOVED_LABEL}</strong><br>`
                    + `${formatCount(n.rows)} rows from the categories shown · ${formatCount(n.total)} removed in all`);
            }
        } else {
            text.text(formatCount(n.rows));
        }
        // The catch-all is the one band that stands for other categories, so it names them on hover
        if (n.label === OTHER_LABEL && side.flows.other) {
            ctx.tooltip.attach(item, () => otherTooltip(side.flows.other));
        }
    });
}

/* Root's column in the middle: a box per category root holds, with the category's name and root's count in
   it. The name goes here once rather than in all three columns, since a band is the same category across the
   whole plot. A category only the nodes hold - a recode into a new value - has no box, but still has its name
   on its band. */
function drawRootColumn(g, layout, {left, width, h}, ctx) {
    const group = g.append("g");
    const other = layout.sides.find((side) => side.flows.other)?.flows.other;
    layout.bands.filter((band) => band.size > 0 && layout.inView(band)).forEach((band) => {
        const root = layout.roots.get(band.label);
        const item = group.append("g");
        if (root) {
            const box = item.append("rect").attr("class", "compare-flow-root")
                .attr("x", left).attr("y", root.y0).attr("width", width).attr("height", Math.max(1, root.y1 - root.y0));
            pickable(box, band.label, `${band.label}: ${formatCount(root.rows)} rows in ${ctx.labels.base}`, ctx);
        }

        // As much of the name as the box has room for beside the count - about 6.5px a character
        const count = root ? ` ${formatCount(root.rows)}` : "";
        const fits = Math.max(3, Math.floor((width - 14) / 6.5) - count.length);
        const at = root ?? band;
        const text = item.append("text").attr("class", "compare-flow-label compare-flow-root-label")
            .attr("x", left + width / 2).attr("y", labelY(at, h))
            .attr("text-anchor", "middle").attr("dominant-baseline", "middle")
            .classed("compare-flow-label--new", !root);
        text.append("tspan").text(band.label.length > fits ? `${band.label.slice(0, fits)}…` : band.label);
        if (count) text.append("tspan").attr("class", "compare-flow-count").text(count);

        if (band.label === OTHER_LABEL && other) ctx.tooltip.attach(item, () => otherTooltip(other));
    });
}

/* Where a side's annotation should point - at markedFlow's ribbon, or the nearest part of it in sight - and,
   when part of that ribbon is out of sight, a sentence saying where */
function flowAnchor(side, {x0, x1}, where, h) {
    const marked = markedFlow(side.flows);
    if (!marked) return null;
    const off = [...new Set([marked.source, marked.target])]
        .map((label) => [label, where(label)])
        .filter(([, place]) => place);
    const aside = off.length
        ? `(${off.map(([label, place]) => (place === "hidden"
            ? `${label} is hidden`
            : `${label} is ${place} the categories shown`)).join(" and ")}.)`
        : null;

    /* The middle of the ribbon, or the nearest part of it still in sight. A ribbon wholly out of sight - or one
       to the sink from a hidden category, which is not drawn - gets the edge it lies beyond. */
    const ribbon = side.placed.find((r) => r.source === marked.source && r.target === marked.target);
    const inSight = ribbon && RIBBON_STEPS.map((t) => ribbonPoint(ribbon, x0, x1, t)).find(([, y]) => y >= 0 && y <= h);
    if (inSight) return {ax: inSight[0], ay: inSight[1], aside};
    const beyond = ribbon ? ribbonPoint(ribbon, x0, x1, 0.5)[1] < 0 : where(marked.source) === "above";
    return {ax: (x0 + x1) / 2, ay: beyond ? 0 : h, aside};
}

/* A side's title over its half, on two lines: whose rows the half follows, and that node's drift from root.
   B's is set against the right edge, mirroring A's on the left. compact keeps to the node's name and its drift,
   for a canvas too narrow for the full titles. */
function flowSideTitle(g, side, detail, {align}, w, ctx, compact) {
    const header = g.append("g");
    const title = header.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -26)");
    const name = compact ? ctx.labels[side.id] : `${ROLE_NAMES[side.id]} · ${ctx.labels[side.id]}`;
    const next = titleChip(title, 0, side.id, name);
    if (detail?.null?.flagged) {
        title.append("text").attr("x", next - 12).attr("fill", FLAG_COLOR).text("▲")
            .append("title").text(NULL_FLAG_TITLE);
    }
    header.append("text").attr("class", "compare-panel-subtitle").attr("y", -10)
        .text(`${compact ? "" : `vs ${ctx.labels.base} · `}drift ${formatDrift(detail?.distortion?.value)}`);
    if (align === "end") header.attr("transform", `translate(${w - header.node().getBBox().width}, 0)`);
    return header;
}

/* Where the rows went in this column, from root out to each selected node: into the same category, into
   another, or out of the table. Root sits in the middle with the category names; selection A's flows run out
   to the left and selection B's to the right, so each half is one node's change from root, and the two share
   root's categories and the window.

   This is churn's picture rather than TVD's - rows swapping between two categories are ribbons here while
   leaving the shares, and so the drift number, unchanged - so both numbers sit beneath each half.
   ctx.world is the whole Sankey laid out unzoomed, and ctx.range the slice of it the minimap beside the plot
   shows - [f0, f1] as shares of its height - or null for all of it. */
function drawFlows(svg, data, ctx) {
    const categories = shownCategories(data, ctx.hidden);
    if (!categories.length) {
        return drawEmpty(svg, ctx, "Every category is hidden — bring some back from the Categories list");
    }

    // One panel across the canvas's full width: the outer columns' counts take the room an axis would
    const w = ctx.width;
    const h = Math.max(10, ctx.height - MARGIN.top - MARGIN.bottom);
    const g = svg.append("g").attr("transform", `translate(0, ${MARGIN.top})`);

    // Never under enough for the removed sink's name, which a narrow canvas stacks over its count
    const room = Math.max(64, Math.min(COUNT_ROOM, w * 0.14));
    const rootWidth = Math.min(ROOT_BOX, w * 0.22);
    const rootLeft = (w - rootWidth) / 2;
    const rootRight = rootLeft + rootWidth;
    // Each side runs from root's edge (x0) out to its own column (x1), and its bubble keeps to its own half
    const frames = {
        a: {x0: rootLeft, x1: room + FLOW_NODE, bar: room, anchor: "end", labelX: room - 6, align: "start",
            bounds: {left: 0, right: rootLeft}},
        b: {x0: rootRight, x1: w - room - FLOW_NODE, bar: w - room - FLOW_NODE, anchor: "start", labelX: w - room + 6,
            align: "end", bounds: {left: rootRight, right: w}},
    };

    const layout = zoomFlows(ctx.world, ctx.range, h);
    const detail = flowSides(data);
    // Zoomed in, the ribbons and columns out of sight would otherwise draw over the titles and the numbers beneath
    g.append("clipPath").attr("id", ctx.clipId).append("rect").attr("width", w).attr("height", h);
    const clip = `url(#${ctx.clipId})`;

    const rootHeader = g.append("g");
    rootHeader.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -26)")
        .append("text").attr("x", w / 2).attr("text-anchor", "middle").text(ctx.labels.base);
    const rootSubtitle = rootHeader.append("text").attr("class", "compare-panel-subtitle")
        .attr("x", w / 2).attr("y", -10).attr("text-anchor", "middle")
        .text(data.base ? "common ancestor" : "original upload");

    /* Three titles share the line over the plot. Where the canvas is too narrow for them, each side drops to its
       node's name and root to its own, rather than running into one another. */
    const titles = (compact) => FLOW_SIDES.map((side) => flowSideTitle(g, side, detail[side.id], frames[side.id], w, ctx, compact));
    const headers = titles(false);
    const [boxA, boxRoot, boxB] = [headers[0], rootHeader, headers[1]].map((one) => one.node().getBoundingClientRect());
    if (boxA.right + 8 > boxRoot.left || boxRoot.right + 8 > boxB.left) {
        headers.forEach((one) => one.remove());
        rootSubtitle.remove();
        titles(true);
    }

    // Back to front: ribbons, then the columns over their ends, then the bubbles over everything
    FLOW_SIDES.forEach((side) => {
        const frame = frames[side.id];
        const drawn = layout.sides.find((one) => one.id === side.id);
        const middle = (frame.x0 + frame.x1) / 2;
        if (!drawn) {
            g.append("text").attr("class", "compare-axis-label")
                .attr("x", middle).attr("y", h / 2).attr("text-anchor", "middle")
                .text(`${data.x} was dropped on the way to ${ctx.labels[side.id]}`);
            return;
        }
        drawRibbons(g, drawn, {...frame, where: layout.where, clip}, ctx);

        // A narrow half takes its two numbers on two lines, and shorter, so the two footers stay apart
        const churn = `churn ${formatShare(drawn.flows.churn)}`;
        const tvd = `TVD ${formatDrift(detail[side.id].distortion?.value)}`;
        const footer = g.append("text").attr("class", "compare-axis-label")
            .attr("x", middle).attr("y", h + 28).attr("text-anchor", "middle");
        if (Math.abs(frame.x0 - frame.x1) >= 200) {
            footer.text(`${churn} of rows · ${tvd}`);
        } else {
            footer.append("tspan").attr("x", middle).text(churn);
            footer.append("tspan").attr("x", middle).attr("dy", "1.2em").text(tvd);
        }
    });
    const columns = g.append("g").attr("clip-path", clip);
    drawRootColumn(columns, layout, {left: rootLeft, width: rootWidth, h}, ctx);
    layout.sides.forEach((side) => drawNodeColumn(columns, side, {...frames[side.id], inView: layout.inView, width: w, h}, ctx));
    layout.sides.forEach((side) => {
        const frame = frames[side.id];
        const anchor = flowAnchor(side, frame, layout.where, h);
        if (anchor) {
            drawAnnotationBubble(g, {...anchor, bounds: {...frame.bounds, top: 0, bottom: h}}, side.id, detail[side.id], ctx);
        }
    });
}

const DRAWERS = {
    histogram: {side: drawHistogramSide, overlay: drawHistogramOverlay, difference: drawHistogramDifference},
    heatmap: {side: drawHeatmapSide, difference: drawHeatmapDifference},
    drift: {ridgeline: drawRidgeline, flows: drawFlows},
};

function isEmpty(data) {
    // A categorical column is drawn as its flows, a numeric one as its curves
    if (data.kind === "drift") {
        const drawable = (side) => (side?.kind === "categorical" ? side?.flows : side?.density);
        return !drawable(data.a) && !drawable(data.b);
    }
    const marks = data.kind === "histogram" ? data.bins : data.tiles;
    return !marks?.length;
}

function drawEmpty(svg, {width, height}, message = "Neither node has rows to plot for this selection") {
    svg.append("text").attr("class", "compare-empty")
        .attr("x", width / 2).attr("y", height / 2).attr("text-anchor", "middle")
        .text(message);
}

// ── Legend ───────────────────────────────────────────────────────────────────

function legendItems(kind, view, measure, labels) {
    const roleLabel = (role) => `${ROLE_NAMES[role]} · ${labels[role]}`;

    if (kind === "drift") {
        if (view === "flows") {
            return [
                {label: "Stayed in its category", style: {background: FLOW_COLORS.stayed}},
                {label: "Recoded into another", style: {background: FLOW_COLORS.recoded}},
                {label: "Row removed", style: {background: FLOW_COLORS.removed}},
            ];
        }
        // Named the way the plot names it, so a common ancestor reads as its node rather than as "Root"
        const base = labels.base === "root" ? "Root" : labels.base;
        return [
            {label: base, style: {background: ROOT_COLOR}},
            ...["a", "b"].map((role) => ({label: roleLabel(role), style: {background: ROLE_COLORS[role]}})),
            {
                label: `${base}'s shape, dashed on every row`, shape: "line",
                style: {background: "repeating-linear-gradient(to right, #1c1e21 0 4px, transparent 4px 7px)"}
            },
        ];
    }
    const errorItems = [
        ...ERROR_DIMENSIONS.map((type) => ({label: MEASURES[type].label, style: {background: errorColors(type)}})),
        {label: "No errors", style: {background: errorColors("none")}},
    ];

    if (view === "difference") {
        const {fewer, more} = differenceColors(measure);
        const noun = MEASURES[measure].noun;
        const [better, worse] = measure === "items" ? ["", ""] : [" (better)", " (worse)"];
        return [
            {label: `Fewer ${noun} in selection B${better}`, style: {background: fewer}},
            {label: `More ${noun} in selection B${worse}`, style: {background: more}},
        ];
    }

    if (kind === "heatmap") {
        const fill = sequentialColor(measure, 1);
        const items = [{
            label: `Darker tiles hold more ${MEASURES[measure].noun}`,
            shape: "ramp",
            style: {background: `linear-gradient(to right, ${fill(0.01)}, ${fill(1)})`},
        }];
        if (measure !== "items") items.push({label: "Rows, none flagged", style: {background: NEUTRAL}});
        return items;
    }

    if (kind === "histogram" && view === "overlay") {
        return ["a", "b"].map((role) => ({label: roleLabel(role), style: {background: ROLE_COLORS[role]}}));
    }

    return errorItems;
}

/**
 * The compare modal's plot.
 *
 * Props:
 *  - data: a /api/pgraph/compare response, or null while there is none to show. A drift result carries base,
 *    the common ancestor its views are measured from, or null for root
 *  - view: "side" | "overlay" | "difference", or for drift "ridgeline" | "flows" -
 *    which the kind supports is the modal's call
 *  - measure: a MEASURES key, read by difference views and heatmaps
 *  - labelA, labelB: short names for selection A and selection B
 *  - hidden: the Sankey's categories the reader has taken out of the view, by name
 *  - onHide: called with a category when its bar is selected and Delete pressed
 */
export default function ComparisonPlot({data, view, measure, labelA, labelB, hidden = [], onHide}) {
    const canvasRef = useRef(null);
    const svgRef = useRef(null);
    const tooltipRef = useRef(null);
    const [size, setSize] = useState({width: 0, height: 0});
    // What the hovered annotation bubble says, shown under the plot rather than over it
    const [note, setNote] = useState(null);

    /* The part of the column a zoomed ridgeline or Sankey shows, stamped with the column, nodes and reference it
       was chosen for. Another column, node pair or reference reads it as unzoomed, so a stale zoom lapses without an
       effect to reset it - a new reference refits the ridgeline's grid, so its old window means nothing. */
    const zoomKey = data?.kind === "drift" ? `${data.x}|${data.a.node}|${data.b.node}|${data.base ?? ""}` : null;
    const [zoom, setZoom] = useState({key: null, range: null});
    const range = zoom.key === zoomKey ? zoom.range : null;
    // The brush and the minimap report on every move, often the same range; only a new one is worth a redraw
    const zoomTo = useCallback((next) => setZoom((previous) => (
        previous.key === zoomKey && String(previous.range) === String(next) ? previous : {key: zoomKey, range: next}
    )), [zoomKey]);

    // Ids are unique per page, and useId's own characters are not all safe in a url(#...) reference
    const clipId = `compare-ridge-clip${useId().replace(/[^\w-]/g, "")}`;
    const overview = useMemo(() => ridgelineOverview(data), [data]);
    // What the drift views measure from, read off the result so one still up while the next loads keeps its own
    const labelBase = data?.base ? nodeName(data.base) : "root";
    /* The whole Sankey laid out unzoomed, once: the plot draws a magnified slice of it and the minimap draws all of
       it, so the two always agree. Null for anything the Sankey does not draw. */
    const flowsHeight = flowsFrame(size.height).height;
    const flowsWorld = useMemo(() => {
        if (data?.kind !== "drift" || !FLOW_SIDES.some((side) => flowSides(data)[side.id]?.flows)) return null;
        const categories = shownCategories(data, hidden);
        return categories.length ? layoutFlows(data, categories, flowsHeight) : null;
    }, [data, hidden, flowsHeight]);

    /* The category whose bar was last clicked, waiting for Delete to hide it. It is stamped with the column
       and nodes it was picked in, so another column reads it as no selection at all and a stale name cannot
       be hidden by a later keystroke. */
    const [selection, setSelection] = useState({key: null, category: null});
    const selected = selection.key === zoomKey ? selection.category : null;
    const setSelected = useCallback((category) => setSelection({key: zoomKey, category}), [zoomKey]);
    useEffect(() => {
        if (!selected) return undefined;
        const onKeyDown = (event) => {
            if (event.key !== "Delete" && event.key !== "Backspace") return;
            event.preventDefault();
            onHide?.(selected);
            setSelected(null);
        };
        document.addEventListener("keydown", onKeyDown);
        return () => document.removeEventListener("keydown", onKeyDown);
    }, [selected, onHide, setSelected]);
    // While the next column loads, the last one's drift result stays up - but only under a view for its kind
    const stale = data?.kind === "drift" && (data.a.kind ?? data.b.kind) !== DRIFT_VIEW_KINDS[view];

    // The canvas takes whatever room the modal gives it, and the plot is laid out from that
    useEffect(() => {
        const observer = new ResizeObserver(([entry]) => {
            setSize({width: entry.contentRect.width, height: entry.contentRect.height});
        });
        observer.observe(canvasRef.current);
        return () => observer.disconnect();
    }, []);

    /* The height the canvas and the ridgeline's strip share. It does not change as they split it, so the strip
       can be sized from it without the canvas's answer feeding back into the strip's - see ridgelineCurve. */
    const bodyRef = useRef(null);
    const [bodyHeight, setBodyHeight] = useState(0);
    useEffect(() => {
        const observer = new ResizeObserver(([entry]) => setBodyHeight(entry.contentRect.height));
        observer.observe(bodyRef.current);
        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        const svg = d3.select(svgRef.current);
        const draw = data && DRAWERS[data.kind]?.[view];
        if (!draw || stale || size.width < MIN_CANVAS || size.height < MIN_CANVAS) return;

        const tooltip = makeTooltip(tooltipRef.current, canvasRef.current);
        if (isEmpty(data)) {
            drawEmpty(svg, size);
        } else {
            draw(svg, data, {
                ...size, measure, tooltip, range, clipId, showNote: setNote, world: flowsWorld,
                hidden, selected, onSelect: setSelected,
                labels: {a: labelA, b: labelB, base: labelBase},
            });
        }

        return () => {
            tooltip.hide();
            setNote(null);
            svg.selectAll("*").remove();
        };
    }, [data, view, measure, labelA, labelB, labelBase, size, stale, range, clipId, hidden, selected, setSelected, flowsWorld]);

    /* Over a zoomed Sankey the wheel scrolls it, as it would a long page. Attached by hand, since React's own wheel
       handler is passive and could not keep the page from scrolling too. */
    useEffect(() => {
        const canvas = canvasRef.current;
        if (view !== "flows" || !range) return undefined;
        const onWheel = (event) => {
            // Firefox can report lines rather than pixels
            const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : 1);
            const next = panRange(range, (pixels / flowsHeight) * (range[1] - range[0]));
            if (next === range) return;
            event.preventDefault();
            zoomTo(next);
        };
        canvas.addEventListener("wheel", onWheel, {passive: false});
        return () => canvas.removeEventListener("wheel", onWheel);
    }, [view, range, flowsHeight, zoomTo]);

    return (
        <div className="compare-plot-frame">
            <div ref={bodyRef} className="compare-plot-body">
                <div className="compare-plot-stage">
                    {/* A click that misses a category clears the selection */}
                    <div ref={canvasRef} className="compare-plot-canvas" onClick={() => setSelected(null)}>
                        <svg ref={svgRef} width={size.width} height={size.height}/>
                        <div ref={tooltipRef} className="compare-tooltip"/>
                    </div>
                    {view === "flows" && flowsWorld && !stale && size.height >= MIN_CANVAS && (
                        // Keyed like the ridgeline's strip, so a new pair starts unzoomed rather than where the last was
                        <SankeyMinimap
                            key={zoomKey}
                            world={flowsWorld}
                            frame={flowsFrame(size.height)}
                            range={range}
                            onRange={zoomTo}
                        />
                    )}
                </div>
                {view === "ridgeline" && overview && !stale && size.width >= MIN_CANVAS && (
                    // Keyed on the column and nodes, so a new pair starts with a fresh brush rather than the last box
                    <RidgelineBrush
                        key={zoomKey}
                        {...overview}
                        frame={ridgelineFrame(size.width)}
                        rootColor={ROOT_COLOR}
                        baseLabel={labelBase}
                        curve={ridgelineCurve(bodyHeight)}
                        range={range}
                        onRange={zoomTo}
                    />
                )}
            </div>
            {data?.kind === "drift" && (
                <div className="compare-note" aria-live="polite">
                    {selected ? (
                        <>
                            <span className="compare-note-role">{selected}</span>
                            selected — press Delete to hide it. It stays in the Categories list to bring back.
                        </>
                    ) : note ? (
                        <>
                            <span className="compare-note-role" style={{color: ROLE_COLORS[note.role]}}>
                                {ROLE_NAMES[note.role]} · {note.label}
                            </span>
                            {note.text}
                        </>
                    ) : (
                        <span className="compare-note-hint">
                            {view === "flows"
                                ? "Hover a bubble for what changed where it points. Click a category to select it, or scroll to move when zoomed."
                                : "Hover a bubble for what changed where it points, or the curves for each node's share at that value."}
                        </span>
                    )}
                </div>
            )}
            {data && (
                <div className="compare-legend">
                    {legendItems(data.kind, view, measure, {a: labelA, b: labelB, base: labelBase}).map((item) => (
                        <span key={item.label} className="compare-legend-item">
                            <span
                                className={`compare-legend-mark compare-legend-mark--${item.shape ?? "box"}`}
                                style={item.style}
                            />
                            {item.label}
                        </span>
                    ))}
                </div>
            )}
        </div>
    );
}
