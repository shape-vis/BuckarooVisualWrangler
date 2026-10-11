// WrangleDiffChart.jsx
// What one wrangle did to the data, small enough to hang beside the edge that made it: the parent's state
// against the node's, binned on axes both share by /api/pgraph/compare - see app/pgraph/compare.py.
//
// One column draws as the repair preview's histogram - the node's bars stacked by error type - with the
// parent's bars outlined behind them. Rows the wrangle took away are the hatched red gap up to the outline;
// rows it added are the green part of a bar above it. Two columns draw as a heatmap whose tiles are coloured
// by how their row count changed.

import {useEffect, useId, useRef, useState} from "react";
import * as d3 from "d3";
import {getNodeComparison} from "../utils/serverCalls.jsx";
import {createHybridScales, showTooltip, moveTooltip, hideTooltip} from "../utils/visCommon.jsx";
import {ERROR_DIMENSIONS, errorColors} from "../store/errorColors.js";
import "../styles/WrangleDiffChart.css";

// The chart's own coordinates; the svg scales to whatever width its frame gives it
const VIEW = {width: 190, height: 150};
const MARGIN = {top: 6, right: 6, bottom: 34, left: 30};
const PLOT = {width: VIEW.width - MARGIN.left - MARGIN.right, height: VIEW.height - MARGIN.top - MARGIN.bottom};

/* Lost and gained. The error types already use a solid red for anomalies, so lost rows are hatched, and sit
   where the node has no bar at all - they cannot be read as a flag. */
const LOST = "#c1121f";
const GAINED = "#1a7f37";
const OUTLINE = "#6b7280";
// A tile that exists on either side but did not change
const UNCHANGED = "#eef0f2";

const formatCount = d3.format(",");
const formatDelta = (value) => (value > 0 ? `+${formatCount(value)}` : formatCount(value));
const formatValue = (value) => (Math.abs(value) >= 1e4 ? d3.format(".3~s")(value) : d3.format(".4~g")(value));

// Bin labels are the user's data, and the shared tooltip is set as html
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character]));

// ── Scales ───────────────────────────────────────────────────────────────────

// The shared hybrid scale, fed the backend's binned axis: numeric bin edges, then categorical labels
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

/* createHybridScales draws its x axis at y = size, which assumes a square plot. This one is wider than it is
   tall, so the axis goes into a group shifted by the difference, landing it on the plot's floor. */
function drawXAxis(g, xScale) {
    xScale.draw(g.append("g").attr("transform", `translate(0, ${PLOT.height - PLOT.width})`));
}

// ── Tooltips ─────────────────────────────────────────────────────────────────

function changeTooltip(title, before, after) {
    return `<strong>${escapeHtml(title)}</strong><br>`
        + `Rows: ${formatCount(before)} → ${formatCount(after)} (<strong>${formatDelta(after - before)}</strong>)`;
}

function attachTooltip(selection, html) {
    selection
        .on("mouseenter", (event, d) => showTooltip(html(d), event))
        .on("mousemove", (event) => moveTooltip(event))
        .on("mouseleave", () => hideTooltip());
}

// ── Histogram ────────────────────────────────────────────────────────────────

/* One bar's stack: error flags from the top down, clean rows beneath - the preview's and main histograms' order */
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

function drawHistogram(g, data, hatchId) {
    const xScale = binScale(data.scaleX, PLOT.width, "horizontal");
    const peak = d3.max(data.bins, (bin) => Math.max(bin.a.items, bin.b.items)) || 1;
    const y = d3.scaleLinear().domain([0, peak]).nice().range([PLOT.height, 0]);
    const x = (bin) => spanX(xScale, data.scaleX, bin).x;
    const width = (bin) => Math.max(0, spanX(xScale, data.scaleX, bin).w - 1);

    // The node's bars, as the repair preview draws them
    const segments = data.bins.flatMap((bin) => stackSegments(bin.b).map((segment) => ({...segment, bin})));
    g.append("g").selectAll("rect").data(segments).join("rect")
        .attr("x", (d) => x(d.bin))
        .attr("width", (d) => width(d.bin))
        .attr("y", (d) => y(d.top))
        .attr("height", (d) => Math.max(0, y(d.bottom) - y(d.top)))
        .attr("fill", (d) => errorColors(d.type))
        .attr("stroke", "white")
        .attr("stroke-width", 0.5);

    // Rows lost: the gap between the node's bar and the parent's
    const lost = data.bins.filter((bin) => bin.a.items > bin.b.items);
    g.append("g").selectAll("rect").data(lost).join("rect")
        .attr("x", x)
        .attr("width", width)
        .attr("y", (bin) => y(bin.a.items))
        .attr("height", (bin) => Math.max(0, y(bin.b.items) - y(bin.a.items)))
        .attr("fill", `url(#${hatchId})`)
        .attr("stroke", LOST)
        .attr("stroke-width", 0.75);

    // Rows gained: the part of the node's bar standing above the parent's
    const gained = data.bins.filter((bin) => bin.b.items > bin.a.items);
    g.append("g").selectAll("rect").data(gained).join("rect")
        .attr("x", x)
        .attr("width", width)
        .attr("y", (bin) => y(bin.b.items))
        .attr("height", (bin) => Math.max(0, y(bin.a.items) - y(bin.b.items)))
        .attr("fill", GAINED)
        .attr("fill-opacity", 0.45)
        .attr("stroke", GAINED)
        .attr("stroke-width", 0.75);

    // The parent's bars, outlined over everything so the before is always readable
    g.append("g").selectAll("rect").data(data.bins.filter((bin) => bin.a.items > 0)).join("rect")
        .attr("x", x)
        .attr("width", width)
        .attr("y", (bin) => y(bin.a.items))
        .attr("height", (bin) => Math.max(0, PLOT.height - y(bin.a.items)))
        .attr("fill", "none")
        .attr("stroke", OUTLINE)
        .attr("stroke-width", 0.75)
        .attr("stroke-dasharray", "2 1.5");

    // Full-height hit areas, so every bin can be hovered for its numbers
    const hits = g.append("g").selectAll("rect").data(data.bins).join("rect")
        .attr("class", "wrangle-diff-hit")
        .attr("x", x)
        .attr("width", (bin) => Math.max(0, spanX(xScale, data.scaleX, bin).w))
        .attr("y", 0)
        .attr("height", PLOT.height);
    attachTooltip(hits, (bin) => changeTooltip(
        `${data.x}: ${binLabel(data.scaleX, bin.xType, bin.xBin)}`, bin.a.items, bin.b.items));

    drawXAxis(g, xScale);
    g.append("g").call(d3.axisLeft(y).ticks(3).tickFormat(d3.format(".2s")));
}

// ── Heatmap ──────────────────────────────────────────────────────────────────

function drawHeatmap(g, data) {
    const xScale = binScale(data.scaleX, PLOT.width, "horizontal");
    const yScale = binScale(data.scaleY, PLOT.height, "vertical");
    const delta = (tile) => tile.b.items - tile.a.items;
    const extent = d3.max(data.tiles, (tile) => Math.abs(delta(tile))) || 1;
    // Stronger for a bigger change, from a visible floor so a small change still reads
    const fill = (tile) => (delta(tile) === 0
        ? UNCHANGED
        : d3.interpolateRgb(UNCHANGED, delta(tile) > 0 ? GAINED : LOST)(0.3 + 0.7 * Math.min(1, Math.abs(delta(tile)) / extent)));

    const tiles = g.append("g").selectAll("rect").data(data.tiles).join("rect")
        .attr("x", (tile) => spanX(xScale, data.scaleX, tile).x)
        .attr("width", (tile) => Math.max(0, spanX(xScale, data.scaleX, tile).w))
        .attr("y", (tile) => spanY(yScale, data.scaleY, tile).y)
        .attr("height", (tile) => Math.max(0, spanY(yScale, data.scaleY, tile).h))
        .attr("fill", fill)
        .attr("stroke", "white")
        .attr("stroke-width", 0.5);
    attachTooltip(tiles, (tile) => changeTooltip(
        `${data.x}: ${binLabel(data.scaleX, tile.xType, tile.xBin)} · ${data.y}: ${binLabel(data.scaleY, tile.yType, tile.yBin)}`,
        tile.a.items, tile.b.items));

    drawXAxis(g, xScale);
    yScale.draw(g.append("g"));
}

// ── Component ────────────────────────────────────────────────────────────────

/**
 * @param parent  - the parent node's table: the state before the wrangle
 * @param node    - the node's table: the state after it
 * @param columns - the column(s) the wrangle acted on; one draws a histogram, two a heatmap
 */
export default function WrangleDiffChart({parent, node, columns}) {
    const svgRef = useRef(null);
    const hatchId = `wrangle-diff-lost-${useId().replace(/:/g, "")}`;
    const [x, y] = columns;
    const kind = y ? "heatmap" : "histogram";

    /* Each reply is filed under the request it answers, so a chart asked for something new is loading until
       that reply arrives - without resetting anything when the question changes. */
    const request = [parent, node, kind, x, y ?? ""].join("|");
    const [reply, setReply] = useState({request: null, status: null, data: null});
    const result = reply.request === request ? reply : {status: "loading", data: null};

    useEffect(() => {
        const controller = new AbortController();
        getNodeComparison({a: parent, b: node, kind, x, y}, controller.signal)
            .then((response) => setReply(response?.success
                ? {request, status: "ready", data: response}
                : {request, status: "error", data: response?.error ?? "Could not compare the two states"}))
            .catch((error) => {
                if (error.name !== "AbortError") setReply({request, status: "error", data: error.message});
            });
        return () => controller.abort();
    }, [request, parent, node, kind, x, y]);

    useEffect(() => {
        if (reply.request !== request || reply.status !== "ready" || !svgRef.current) return;
        const svg = d3.select(svgRef.current);
        svg.selectAll("*").remove();

        // Rows lost are hatched, so they cannot be mistaken for the anomaly flag's solid red
        svg.append("defs").append("pattern")
            .attr("id", hatchId).attr("patternUnits", "userSpaceOnUse")
            .attr("width", 3).attr("height", 3).attr("patternTransform", "rotate(45)")
            .append("line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 3)
            .attr("stroke", LOST).attr("stroke-width", 1.2);

        const g = svg.append("g").attr("transform", `translate(${MARGIN.left}, ${MARGIN.top})`);
        if (reply.data.kind === "heatmap") drawHeatmap(g, reply.data);
        else drawHistogram(g, reply.data, hatchId);
    }, [reply, request, hatchId]);

    if (result.status === "loading") return <div className="wrangle-diff-message">Loading…</div>;
    if (result.status === "error") return <div className="wrangle-diff-message wrangle-diff-message--error">{result.data}</div>;

    return (
        <svg
            ref={svgRef}
            className="wrangle-diff-chart"
            viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
            onMouseLeave={hideTooltip}
        />
    );
}
