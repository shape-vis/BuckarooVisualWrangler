// WrangleDiffChart.jsx
// What one wrangle did to the data, small enough to hang beside the edge that made it: the parent's state
// against the node's, binned on axes both share by /api/pgraph/compare - see app/db_utils/compare_sql.py.
//
// One column draws as the repair preview's histogram - the node's bars stacked by error type - with the
// parent's bars outlined behind them. Rows the wrangle took away are the hatched red gap up to the outline;
// rows it added are the green part of a bar above it. Two columns draw as a heatmap whose tiles are coloured
// by how their row count changed.

import {useEffect, useId, useRef, useState} from "react";
import * as d3 from "d3";
import {getNodeComparison} from "../utils/serverCalls.jsx";
import {showTooltip, moveTooltip, hideTooltip} from "../utils/visCommon.jsx";
import {domSafeId, escapeHtml} from "../utils/html.js";
import {errorColors} from "../store/errorColors.js";
import {
    GREEN, RED,
    binLabel, binScale, divergingFill, drawXAxisOnFloor, formatCount, formatDelta, spanX, spanY, stackSegments,
} from "./binnedPlot.js";
import "../styles/WrangleDiffChart.css";

// The chart's own coordinates; the svg scales to whatever width its frame gives it
const VIEW = {width: 190, height: 150};
const MARGIN = {top: 6, right: 6, bottom: 34, left: 30};
const PLOT = {width: VIEW.width - MARGIN.left - MARGIN.right, height: VIEW.height - MARGIN.top - MARGIN.bottom};

/* Lost and gained. The error types already use a solid red for anomalies, so lost rows are hatched, and sit
   where the node has no bar at all - they cannot be read as a flag. */
const LOST = RED;
const GAINED = GREEN;
const OUTLINE = "#6b7280";
// A heatmap tile's change starts this far toward its colour, so a small change still reads
const CHANGE_FLOOR = 0.3;

// ── Axes ─────────────────────────────────────────────────────────────────────

// This plot is wider than it is tall, so its x axis is moved down onto its floor
function drawXAxis(g, xScale) {
    drawXAxisOnFloor(g.append("g"), xScale, PLOT.width, PLOT.height);
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

// A tile's title in its tooltip: its bin on each axis
function tileTitle(data, tile) {
    const xPart = `${data.x}: ${binLabel(data.scaleX, tile.xType, tile.xBin)}`;
    const yPart = `${data.y}: ${binLabel(data.scaleY, tile.yType, tile.yBin)}`;
    return `${xPart} · ${yPart}`;
}

function drawHeatmap(g, data) {
    const xScale = binScale(data.scaleX, PLOT.width, "horizontal");
    const yScale = binScale(data.scaleY, PLOT.height, "vertical");
    const delta = (tile) => tile.b.items - tile.a.items;
    const extent = d3.max(data.tiles, (tile) => Math.abs(delta(tile))) || 1;
    const fill = (tile) => divergingFill(delta(tile), extent, {fewer: LOST, more: GAINED, floor: CHANGE_FLOOR});

    const tiles = g.append("g").selectAll("rect").data(data.tiles).join("rect")
        .attr("x", (tile) => spanX(xScale, data.scaleX, tile).x)
        .attr("width", (tile) => Math.max(0, spanX(xScale, data.scaleX, tile).w))
        .attr("y", (tile) => spanY(yScale, data.scaleY, tile).y)
        .attr("height", (tile) => Math.max(0, spanY(yScale, data.scaleY, tile).h))
        .attr("fill", fill)
        .attr("stroke", "white")
        .attr("stroke-width", 0.5);
    attachTooltip(tiles, (tile) => changeTooltip(tileTitle(data, tile), tile.a.items, tile.b.items));

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
    const hatchId = `wrangle-diff-lost-${domSafeId(useId())}`;
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
            .then((response) => {
                if (response?.success) {
                    setReply({request, status: "ready", data: response});
                } else {
                    setReply({request, status: "error", data: response?.error ?? "Could not compare the two states"});
                }
            })
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
