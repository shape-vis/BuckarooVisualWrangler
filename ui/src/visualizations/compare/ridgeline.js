// compare/ridgeline.js
// The drift view of a numeric column: each node's shape against root's, one row each, with a crosshair that
// reads every curve's share at a value.

import * as d3 from "d3";
import {RIDGE_HEADROOM} from "../RidgelineBrush.jsx";
import {ROLE_COLORS} from "../../utils/comparison.js";
import {formatDrift} from "../../utils/drift.js";
import {escapeHtml} from "../../utils/html.js";
import {clamp} from "../../utils/visCommon.jsx";
import {formatValue} from "../binnedPlot.js";
import {MARGIN, axisLabels, drawEmpty, layoutPanels} from "./frames.js";
import {swatch} from "./tooltip.js";
import {drawAnnotationBubble, formatShare} from "./driftCommon.js";

// Room at the right of a ridgeline for each row's drift
const DRIFT_GUTTER = 72;
// The gap between the ridgeline's rows, as a share of a row - root's row below is sized to match one
export const RIDGE_PADDING = 0.12;
/* Where a curve is under this share of root's peak, it is too thin to divide by: out in the empty tails every
   curve is near zero, and a ratio of two near-zeros is noise */
const THIN_SHARE = 0.005;

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
    const shared = clamp(d3.min(busy, (i) => gap[i] / root[i]) ?? 0, 0, 1);
    return d3.maxIndex(gap, (value, i) => Math.abs(value - shared * root[i]));
}

/* The column's shape in selection A and selection B: one row each on a shared axis, with root's own row
   in the strip beneath, which is also the zoom control. Every curve is smoothed with the bandwidth fitted on
   root, and root is drawn dashed over every row - where the dashed line vanishes under the fill, nothing
   moved. The rows share one vertical scale too, so a node that lost rows draws a smaller curve rather than a
   renormalised one.

   ctx.range zooms the plot to part of the column, chosen on the strip beneath it. The vertical scale then
   fits the tallest curve inside the window rather than the column's, which is what makes a change in a thin
   tail visible - both rows still share it, so they stay comparable. */
export function drawRidgeline(svg, data, ctx) {
    const density = data.a.density ?? data.b.density;
    if (!density) return drawEmpty(svg, ctx, "This column has too few distinct values to draw its shape");

    const rows = ctx.roles.map((role) => ({
        key: role, label: ctx.labels[role], curve: data[role].density?.node, color: ROLE_COLORS[role],
        drift: data[role].distortion?.value,
    }));

    const [{g, w, h}] = layoutPanels(svg, ctx.width - DRIFT_GUTTER, ctx.height, 1);
    const grid = density.grid;
    const [lo, hi] = ctx.range ?? [grid[0], grid[grid.length - 1]];
    const x = d3.scaleLinear().domain([lo, hi]).range([0, w]);
    const band = d3.scaleBand().domain(rows.map((row) => row.key)).range([0, h]).paddingInner(RIDGE_PADDING);

    // The grid points inside the window, and one either side so each curve runs to the window's edges
    const firstVisible = Math.max(0, d3.bisectLeft(grid, lo) - 1);
    const pastLastVisible = Math.min(grid.length, d3.bisectRight(grid, hi) + 1);
    const visible = d3.range(firstVisible, pastLastVisible);
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
        rowGroup.append("text").attr("class", "compare-ridge-drift")
            .attr("x", w + 10).attr("y", middle).attr("dominant-baseline", "middle").text(formatDrift(row.drift));

        /* Each row's annotation is about its own node, at full scale. The spot is found on the whole curve,
           zoomed or not; when the window leaves it out, the bubble is pinned to the edge of the row nearest it,
           pointing off the plot. The arrow meets whichever curve is higher there - root's dashed line where
           rows were removed, the node's own where values were filled in. */
        if (row.curve) {
            const spot = mostChanged(density.root, row.curve);
            const at = grid[spot];
            const bubble = {bounds: {left: 0, right: w, top: band(row.key), bottom: floor}};
            if (at >= lo && at <= hi) {
                bubble.ax = x(at);
                bubble.ay = floor - rise(Math.max(row.curve[spot], density.root[spot]));
                bubble.aside = null;
            } else {
                const offLeft = at < lo;
                const side = offLeft ? "left" : "right";
                bubble.ax = offLeft ? 0 : w;
                bubble.ay = middle;
                bubble.aside = `(That spot, near ${formatValue(at)}, is ${side} of the range shown.)`;
            }
            drawAnnotationBubble(rowGroup, bubble, row.key, data[row.key], ctx);
        }
    });

    g.append("text").attr("class", "compare-axis-label").attr("x", w + 10).attr("y", -14).text("drift");
    g.append("g").attr("class", "compare-axis").attr("transform", `translate(0, ${h})`)
        .call(d3.axisBottom(x).ticks(6).tickFormat(d3.format(".3~s"))).selectAll("text").attr("class", "bottom-axis-text");
    let xLabel = data.x;
    if (ctx.range) xLabel = `${data.x} · zoomed to ${formatValue(lo)} – ${formatValue(hi)}`;
    axisLabels(g, w, h, xLabel, null);

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
            const after = bisect(grid, x0, 1);
            let nearer = after;
            if (after >= grid.length || x0 - grid[after - 1] < grid[after] - x0) nearer = after - 1;
            const i = clamp(nearer, first, last);
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
            const left = clamp(cx - width / 2, 0, w - width);
            labelBox.attr("x", left).attr("width", width);
            labelText.attr("x", left + width / 2);

            ctx.tooltip.show(event, ridgeShares({
                i, rootPeak, root: density.root,
                curveA: rows.find((row) => row.key === "a")?.curve ?? null,
                curveB: rows.find((row) => row.key === "b")?.curve ?? null,
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
export function ridgelineFrame(width) {
    return {left: MARGIN.left, width: Math.max(10, width - DRIFT_GUTTER - MARGIN.left - MARGIN.right), total: width};
}

/* What the overview strip draws for a drift result: the whole column's curves, and the spots the bubbles
   point at. Null for anything the ridgeline does not draw. */
export function ridgelineOverview(data) {
    const density = data?.kind === "drift" ? (data.a.density ?? data.b.density) : null;
    if (!density) return null;
    // A single node's result carries it as both sides; only one of them is drawn
    const curves = {a: data.single ? null : data.a.density?.node ?? null, b: data.b.density?.node ?? null};
    const spots = {
        a: curves.a && mostChanged(density.root, curves.a),
        b: curves.b && mostChanged(density.root, curves.b),
    };
    return {density, curves, spots};
}
