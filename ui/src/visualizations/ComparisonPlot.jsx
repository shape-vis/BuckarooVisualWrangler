// ComparisonPlot.jsx
// Draws two nodes' data against each other for the compare modal. The data arrives from
// /api/pgraph/compare already binned on axes both states share - see app/pgraph/compare.py - so every
// view here can put the two on the same scales.

import {useCallback, useEffect, useId, useMemo, useRef, useState} from "react";
import * as d3 from "d3";
import RidgelineBrush, {RIDGE_HEADROOM, STRIP_CHROME} from "./RidgelineBrush.jsx";
import SankeyBrush from "./SankeyBrush.jsx";
import {createHybridScales} from "../utils/visCommon.jsx";
import {ERROR_DIMENSIONS, errorColors} from "../store/errorColors.js";
import {
    FLOW_PANELS, MEASURES, OTHER_LABEL, REMOVED_LABEL, ROLE_COLORS, ROLE_NAMES,
    flowCategories, flowSides, measureOf,
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

// Rows that stayed in their category, were recoded into another, or were deleted
const FLOW_COLORS = {stayed: "#94a3b8", recoded: "#f59e0b", removed: "#4b5563"};
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
// Room kept for the removed sink under a Sankey's window, however little of it the window shows
const REMOVED_ROOM = 14;
// How far a ribbon to a hidden category runs before it stops, as a share of its full span
const STUB = 0.5;
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
    let html = "";
    if (curveA) html += line(`${swatch(ROLE_COLORS.a)}${escapeHtml(labels.a)} · <strong>${share(curveA[i], root[i])}</strong> of root`);
    if (curveB) html += line(`${swatch(ROLE_COLORS.b)}${escapeHtml(labels.b)} · <strong>${share(curveB[i], root[i])}</strong> of root`);
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

/* Where the Sankeys' panels sit in a canvas this tall, so the strip beside them lines up */
function flowsFrame(height) {
    return {top: MARGIN.top, height: Math.max(10, height - MARGIN.top - MARGIN.bottom), total: height};
}

/* What the strip beside the Sankeys draws for a drift result: every category, a bar per Sankey for the share
   of that category's rows it moved, and the category each annotation bubble points from. Null for anything
   the Sankeys do not draw. */
function flowsOverview(data, hidden) {
    if (data?.kind !== "drift") return null;
    const sides = flowSides(data);
    if (!FLOW_PANELS.some((panel) => sides[panel.id]?.flows)) return null;
    const categories = shownCategories(data, hidden);
    if (!categories.length) return null;

    const series = [];
    const spots = [];
    FLOW_PANELS.forEach((panel) => {
        const flows = sides[panel.id]?.flows;
        if (!flows) return;
        series.push({
            id: panel.id,
            color: panel.color,
            shares: categories.map((label) => {
                const out = flows.flows.filter((flow) => flow.source === label);
                const rows = d3.sum(out, (flow) => flow.rows);
                return rows ? d3.sum(out.filter((flow) => flow.target !== label), (flow) => flow.rows) / rows : 0;
            }),
        });
        // Only the panels with an annotation have a spot worth pinning
        const spot = panel.role ? categories.indexOf(markedFlow(flows)?.source) : -1;
        if (spot >= 0) spots.push({id: panel.id, color: panel.color, index: spot});
    });
    return {categories, series, spots};
}

/* The categories the Sankeys draw: the ones the server sent, less any the reader has hidden. A hidden
   category keeps no band and takes no room; the ribbons that reached it are cut short instead. */
function shownCategories(data, hidden) {
    return flowCategories(data).filter((label) => !hidden.includes(label));
}

/* The flow a panel's annotation points at: the biggest that actually moved - recoded or removed - or failing
   that the biggest of all, so a column where nothing moved can still say so */
function markedFlow(flows) {
    const moved = flows.flows.filter((flow) => flow.target !== flow.source);
    return d3.greatest(moved.length ? moved : flows.flows, (flow) => flow.rows);
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

/* A point along a ribbon's centre line, t running from its source (0) to its target (1) */
function ribbonPoint(ribbon, x0, x1, t) {
    const middle = (x0 + x1) / 2;
    const [ya, yb] = [ribbon.ya + ribbon.thickness / 2, ribbon.yb + ribbon.thickness / 2];
    const [a, b, c, d] = [(1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3];
    return [a * x0 + (b + c) * middle + d * x1, (a + b) * ya + (c + d) * yb];
}

// Along a ribbon from its middle outward, the order its annotation looks for a point still in sight
const RIBBON_STEPS = d3.range(11).flatMap((k) => (k ? [0.5 - k * 0.05, 0.5 + k * 0.05] : [0.5]));

/* One Sankey: the earlier state's categories on the left, the later state's on the right, and the deleted
   rows' sink under them. Ribbons are always square-root width: at true width a category holding a handful of
   rows is a hairline, and these columns usually hold most of their mass in one category. The trade is that a
   ribbon's width no longer reads as its count, so every node carries its count as a label.

   The plot is one tall stack of categories, each a band holding its node on both sides, so a category that
   kept its rows is a level ribbon. window picks the bands that fill the panel; the rest sit above and below
   it out of sight, and a ribbon to one of them runs off the edge toward it. The sink is not a band. It stays
   under the window whatever the window holds, and takes the ribbons from the categories shown.

   Returns where the panel's annotation should point - at markedFlow's ribbon, or the nearest part of it the
   window keeps - and, when the window leaves part of that ribbon out, a sentence saying where. */
function drawSankey(g, flows, categories, window, w, h, ctx) {
    const widthOf = Math.sqrt;
    const LABEL = Math.min(120, w * 0.3);
    const NODE = 10;
    const PAD = 6;

    const [first, last] = window ?? [0, categories.length];
    const position = new Map(categories.map((label, i) => [label, i]));
    /* Where a category is, if it is not in sight: hidden outright, or above or below the window. The sink is
       always in sight, and a label with no position at all was hidden. */
    const where = (label) => {
        if (label === REMOVED_LABEL) return null;
        const at = position.get(label);
        if (at === undefined) return "hidden";
        return at < first ? "above" : at >= last ? "below" : null;
    };
    const inWindow = (label) => !where(label);

    const ribbons = flows.flows.map((flow) => ({...flow, size: widthOf(flow.rows)}));
    const sum = (key, label, value) => d3.sum(ribbons.filter((ribbon) => ribbon[key] === label), (ribbon) => ribbon[value]);
    const bands = categories.map((label) => {
        const left = sum("source", label, "size");
        const right = sum("target", label, "size");
        return {label, left, right, size: Math.max(left, right)};
    });

    const pinned = flows.targets.includes(REMOVED_LABEL);
    const sunk = ribbons.filter((ribbon) => ribbon.target === REMOVED_LABEL && inWindow(ribbon.source));
    const sinkSize = d3.sum(sunk, (ribbon) => ribbon.size);

    /* The scale that fills the panel with the window's bands and the sink, a gap between each. A sink the
       window sends few rows to still gets room for its label. */
    const shown = bands.filter((band) => inWindow(band.label) && band.size > 0);
    const shownSize = d3.sum(shown, (band) => band.size);
    const gaps = PAD * (Math.max(0, shown.length - 1) + (pinned ? 1 : 0));
    let scale = Math.max(0, (h - gaps) / ((shownSize + sinkSize) || 1));
    if (pinned && sinkSize * scale < REMOVED_ROOM) scale = Math.max(0, (h - gaps - REMOVED_ROOM) / (shownSize || 1));
    const sinkTop = h - (pinned ? Math.max(sinkSize * scale, REMOVED_ROOM) : 0);

    /* The window's bands start at the panel's top. Those after it start below the panel's floor, so ribbons to
       them leave through the bottom; those before it stack upward from above its top. */
    const place = (band, top) => Object.assign(band, {y0: top, y1: top + band.size * scale});
    let below = 0;
    for (let i = first; i < bands.length; i += 1) {
        if (i === last) below = h + PAD;
        place(bands[i], below);
        if (bands[i].size) below = bands[i].y1 + PAD;
    }
    let above = -PAD;
    for (let i = first - 1; i >= 0; i -= 1) {
        place(bands[i], above - bands[i].size * scale);
        if (bands[i].size) above = bands[i].y0 - PAD;
    }

    // Each side's node sits in the middle of its band
    const node = (band, side, key) => {
        const top = band.y0 + (band.size - band[side]) * scale / 2;
        return {label: band.label, y0: top, y1: top + band[side] * scale, rows: sum(key, band.label, "rows")};
    };
    const sources = new Map(bands.filter((band) => band.left).map((band) => [band.label, node(band, "left", "source")]));
    const targets = new Map(bands.filter((band) => band.right).map((band) => [band.label, node(band, "right", "target")]));
    if (pinned) {
        targets.set(REMOVED_LABEL, {
            label: REMOVED_LABEL, y0: sinkTop, y1: sinkTop + sinkSize * scale,
            rows: d3.sum(sunk, (ribbon) => ribbon.rows), total: sum("target", REMOVED_LABEL, "rows"),
        });
    }
    const x0 = LABEL + NODE;
    const x1 = w - LABEL - NODE;

    /* Ribbons leave each source in target order and arrive at each target in source order, which keeps
       them from crossing more than the flows themselves require. A ribbon whose category was hidden keeps
       only the end that is still drawn - ya or yb is null, and it is cut short there. A ribbon to the sink
       from a category out of the window has nowhere in it to land, and is left out. */
    const order = new Map([...new Set([...categories, ...flows.sources, ...flows.targets, REMOVED_LABEL])]
        .map((label, i) => [label, i]));
    const leftCursor = new Map([...sources].map(([label, n]) => [label, n.y0]));
    const rightCursor = new Map([...targets].map(([label, n]) => [label, n.y0]));
    const placed = ribbons
        .filter((ribbon) => ribbon.target !== REMOVED_LABEL || inWindow(ribbon.source))
        // Neither end still drawn leaves nothing to hang a ribbon from
        .filter((ribbon) => sources.has(ribbon.source) || targets.has(ribbon.target))
        .sort((a, b) => (order.get(a.source) - order.get(b.source)) || (order.get(a.target) - order.get(b.target)))
        .map((ribbon) => {
            const thickness = ribbon.size * scale;
            const ya = leftCursor.get(ribbon.source);
            const yb = rightCursor.get(ribbon.target);
            if (ya !== undefined) leftCursor.set(ribbon.source, ya + thickness);
            if (yb !== undefined) rightCursor.set(ribbon.target, yb + thickness);
            return {...ribbon, thickness, ya: ya ?? null, yb: yb ?? null};
        });

    // The ribbons into the bands out of sight would otherwise draw over the title and the numbers beneath
    g.append("clipPath").attr("id", ctx.clipId).append("rect").attr("width", w).attr("height", h);

    const middle = (x0 + x1) / 2;
    /* A ribbon with both ends drawn runs the full span. One whose other end was hidden is a stub: it leaves
       the end that remains, runs part of the way and stops, so a reader can see that rows went somewhere
       without the category being in the picture. */
    const path = (r) => {
        if (r.ya === null) {
            const from = x1 - STUB * (x1 - x0);
            return `M${from},${r.yb} H${x1} V${r.yb + r.thickness} H${from} Z`;
        }
        if (r.yb === null) {
            const to = x0 + STUB * (x1 - x0);
            return `M${x0},${r.ya} H${to} V${r.ya + r.thickness} H${x0} Z`;
        }
        return `M${x0},${r.ya} C${middle},${r.ya} ${middle},${r.yb} ${x1},${r.yb} `
            + `L${x1},${r.yb + r.thickness} C${middle},${r.yb + r.thickness} ${middle},${r.ya + r.thickness} ${x0},${r.ya + r.thickness} Z`;
    };
    const cut = (r) => r.ya === null || r.yb === null;
    const kindOf = (r) => (r.target === REMOVED_LABEL ? "removed" : r.target === r.source ? "stayed" : "recoded");

    const paths = g.append("g").attr("clip-path", `url(#${ctx.clipId})`)
        .selectAll("path").data(placed).join("path")
        .attr("class", (r) => `compare-mark ${cut(r) ? "compare-flow-stub" : ""}`)
        .attr("d", path)
        .attr("fill", (r) => FLOW_COLORS[kindOf(r)])
        .attr("fill-opacity", (r) => (cut(r) ? 0.3 : kindOf(r) === "stayed" ? 0.35 : 0.7));
    ctx.tooltip.attach(paths, (r) => {
        const gone = [r.source, r.target].filter((label) => where(label) === "hidden");
        // A hidden source draws no band, so there is no total to take a share of
        const out = sources.get(r.source)?.rows;
        return `<strong>${escapeHtml(r.source)} → ${escapeHtml(r.target)}</strong><br>`
            + `${formatCount(r.rows)} rows${out ? ` · ${formatShare(r.rows / out)} of ${escapeHtml(r.source)}` : ""}`
            + (gone.length ? `<br>${escapeHtml(gone.join(" and "))} hidden — add back from Categories` : "");
    });

    /* Only the nodes in the window are drawn; the rest are out of sight. A category's bar is what the reader
       clicks to pick it out, on either side, and Delete then hides it - the modal owns both, so the click
       only reports which category it was. The sink is not a category and is not selectable. */
    const drawColumn = (nodes, x, anchor, labelX) => {
        const group = g.append("g");
        [...nodes.values()].filter((n) => inWindow(n.label)).forEach((n) => {
            const removed = n.label === REMOVED_LABEL;
            const item = group.append("g").datum(n);
            const bar = item.append("rect").attr("x", x).attr("y", n.y0).attr("width", NODE)
                .attr("height", Math.max(1, n.y1 - n.y0))
                .attr("fill", removed ? FLOW_COLORS.removed : "#475569");
            if (!removed) {
                bar.attr("class", `compare-flow-node ${ctx.selected === n.label ? "compare-flow-node--selected" : ""}`)
                    .on("click", (event) => {
                        // The canvas clears the selection, so a click that makes one must stop there
                        event.stopPropagation();
                        ctx.onSelect?.(ctx.selected === n.label ? null : n.label);
                    })
                    .append("title").text(`${n.label} — click to select, then press Delete to hide it`);
            }
            const text = item.append("text").attr("class", "compare-flow-label")
                .attr("x", labelX).attr("y", (n.y0 + n.y1) / 2).attr("text-anchor", anchor).attr("dominant-baseline", "middle")
                .classed("compare-flow-label--removed", removed);
            text.append("tspan").text(n.label.length > 16 ? `${n.label.slice(0, 16)}…` : n.label)
                .append("title").text(n.label);
            text.append("tspan").attr("class", "compare-flow-count").text(` ${formatCount(n.rows)}`);

            // The sink counts only the rows it takes from the window, so it says when there are more
            if (removed && n.total > n.rows) {
                ctx.tooltip.attach(item, () => `<strong>${REMOVED_LABEL}</strong><br>`
                    + `${formatCount(n.rows)} rows from the categories shown · ${formatCount(n.total)} removed in all`);
            }
            // The catch-all is the one band that stands for other categories, so it names them on hover
            if (n.label === OTHER_LABEL && flows.other) {
                ctx.tooltip.attach(item, () => otherTooltip(flows.other));
            }
        });
    };
    drawColumn(sources, x0 - NODE, "end", x0 - NODE - 6);
    drawColumn(targets, x1, "start", x1 + NODE + 6);

    const marked = markedFlow(flows);
    if (!marked) return null;
    const off = [...new Set([marked.source, marked.target])]
        .map((label) => [label, where(label)])
        .filter(([, side]) => side);
    const aside = off.length
        ? `(${off.map(([label, side]) => (side === "hidden"
            ? `${label} is hidden`
            : `${label} is ${side} the categories shown`)).join(" and ")}.)`
        : null;

    /* The middle of the ribbon, or the nearest part of it still in sight. A ribbon wholly out of sight - or
       one to the sink from out of the window, which is not drawn - gets the edge it lies beyond. */
    const ribbon = placed.find((r) => r.source === marked.source && r.target === marked.target);
    const inSight = ribbon && RIBBON_STEPS.map((t) => ribbonPoint(ribbon, x0, x1, t)).find(([, y]) => y >= 0 && y <= h);
    if (inSight) return {ax: inSight[0], ay: inSight[1], aside};
    const beyond = ribbon ? ribbonPoint(ribbon, x0, x1, 0.5)[1] < 0 : where(marked.source) === "above";
    return {ax: middle, ay: beyond ? 0 : h, aside};
}

/* A flows panel's title, on two lines: whose rows the panel follows on the first, what they are followed
   against on the second. Three panels side by side leave no room for one long line. The pair's chips name
   both nodes, since neither of them is root. */
function flowPanelTitle(g, panel, side, ctx) {
    const title = g.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -26)");
    const against = (text) => g.append("text").attr("class", "compare-panel-subtitle").attr("y", -10).text(text);

    if (panel.id === "pair") {
        const next = titleChip(title, 0, "a", `${ctx.labels.a} →`);
        titleChip(title, next - 8, "b", ctx.labels.b);
        against("the step between them");
        return;
    }
    const next = titleChip(title, 0, panel.role, `${ROLE_NAMES[panel.role]} · ${ctx.labels[panel.role]}`);
    if (side.null?.flagged) {
        title.append("text").attr("x", next - 12).attr("fill", FLAG_COLOR).text("▲")
            .append("title").text(NULL_FLAG_TITLE);
    }
    against(`vs root · drift ${formatDrift(side.distortion?.value)}`);
}

// What each panel prints under its plot: churn always, and the rows the pair's later node holds on its own
function flowFooter(panel, side, ctx) {
    const numbers = `churn ${formatShare(side.flows.churn)} of rows · TVD ${formatDrift(side.distortion?.value)}`;
    return panel.id === "pair" && side.added
        ? `${numbers} · ${formatCount(side.added)} rows only in ${ctx.labels.b}`
        : numbers;
}

/* Where the rows went in this column: into the same category, into another, or out of the table. Three
   Sankeys share the categories and the window - each node against root, and the step between the two nodes
   in the middle, which is the one the wrangles between them actually made.

   This is churn's picture rather than TVD's - rows swapping between two categories are ribbons here while
   leaving the shares, and so the drift number, unchanged - so both numbers sit beneath each one.
   ctx.range is the window of categories the strip beside the plot shows, or null for all of them. */
function drawFlows(svg, data, ctx) {
    const categories = shownCategories(data, ctx.hidden);
    if (!categories.length) {
        return drawEmpty(svg, ctx, "Every category is hidden — bring some back from the Categories list");
    }
    const sides = flowSides(data);
    const panels = FLOW_PANELS.filter((panel) => sides[panel.id]?.flows);

    layoutPanels(svg, ctx.width, ctx.height, panels.length).forEach(({g, w, h}, i) => {
        const panel = panels[i];
        const side = sides[panel.id];
        flowPanelTitle(g, panel, side, ctx);

        const anchor = drawSankey(g, side.flows, categories, ctx.range, w, h,
            {...ctx, clipId: `${ctx.clipId}-${panel.id}`});
        // Only the panels drawn against root carry an annotation; the pair has none to show
        if (anchor && panel.role) {
            drawAnnotationBubble(g, {...anchor, bounds: {left: 0, right: w, top: 0, bottom: h}}, panel.role, side, ctx);
        }

        g.append("text").attr("class", "compare-axis-label")
            .attr("x", w / 2).attr("y", h + 28).attr("text-anchor", "middle")
            .text(flowFooter(panel, side, ctx));
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
        return [
            {label: "Root", style: {background: ROOT_COLOR}},
            ...["a", "b"].map((role) => ({label: roleLabel(role), style: {background: ROLE_COLORS[role]}})),
            {
                label: "Root's shape, dashed on every row", shape: "line",
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
 *  - data: a /api/pgraph/compare response, or null while there is none to show
 *  - view: "side" | "overlay" | "difference", or for drift "ridgeline" | "flows" -
 *    which the kind supports is the modal's call
 *  - measure: a MEASURES key, read by difference views and heatmaps
 *  - labelA, labelB: short names for selection A and selection B
 *  - hidden: the Sankeys' categories the reader has taken out of the view, by name
 *  - onHide: called with a category when its bar is selected and Delete pressed
 */
export default function ComparisonPlot({data, view, measure, labelA, labelB, hidden = [], onHide}) {
    const canvasRef = useRef(null);
    const svgRef = useRef(null);
    const tooltipRef = useRef(null);
    const [size, setSize] = useState({width: 0, height: 0});
    // What the hovered annotation bubble says, shown under the plot rather than over it
    const [note, setNote] = useState(null);

    /* The part of the column a zoomed ridgeline shows, stamped with the column and nodes it was chosen for.
       Another column or node pair reads it as unzoomed, so a stale zoom lapses without an effect to reset it. */
    const zoomKey = data?.kind === "drift" ? `${data.x}|${data.a.node}|${data.b.node}` : null;
    const [zoom, setZoom] = useState({key: null, range: null});
    const range = zoom.key === zoomKey ? zoom.range : null;
    // The brush reports on every move, often the same range; only a new one is worth a redraw
    const zoomTo = useCallback((next) => setZoom((previous) => (
        previous.key === zoomKey && String(previous.range) === String(next) ? previous : {key: zoomKey, range: next}
    )), [zoomKey]);

    // Ids are unique per page, and useId's own characters are not all safe in a url(#...) reference
    const clipId = `compare-ridge-clip${useId().replace(/[^\w-]/g, "")}`;
    const overview = useMemo(() => ridgelineOverview(data), [data]);
    const flowsView = useMemo(() => flowsOverview(data, hidden), [data, hidden]);

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
                ...size, measure, tooltip, range, clipId, showNote: setNote,
                hidden, selected, onSelect: setSelected,
                labels: {a: labelA, b: labelB},
            });
        }

        return () => {
            tooltip.hide();
            setNote(null);
            svg.selectAll("*").remove();
        };
    }, [data, view, measure, labelA, labelB, size, stale, range, clipId, hidden, selected, setSelected]);

    return (
        <div className="compare-plot-frame">
            <div ref={bodyRef} className="compare-plot-body">
                <div className="compare-plot-stage">
                    {/* A click that misses a category's bar clears the selection */}
                    <div ref={canvasRef} className="compare-plot-canvas" onClick={() => setSelected(null)}>
                        <svg ref={svgRef} width={size.width} height={size.height}/>
                        <div ref={tooltipRef} className="compare-tooltip"/>
                    </div>
                    {view === "flows" && flowsView && !stale && size.height >= MIN_CANVAS && (
                        // Keyed like the ridgeline's strip, so a new pair starts with no window rather than the last one
                        <SankeyBrush
                            key={zoomKey}
                            categories={flowsView.categories}
                            series={flowsView.series}
                            spots={flowsView.spots}
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
                                ? "Hover a bubble for what changed where it points. Click a category's bar to select it."
                                : "Hover a bubble for what changed where it points, or the curves for each node's share at that value."}
                        </span>
                    )}
                </div>
            )}
            {data && (
                <div className="compare-legend">
                    {legendItems(data.kind, view, measure, {a: labelA, b: labelB}).map((item) => (
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
