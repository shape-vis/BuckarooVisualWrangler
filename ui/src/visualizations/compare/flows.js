// compare/flows.js
// The drift view of a categorical column: a Sankey of where root's rows went in each node - into the same
// category, into another, or out of the table. Laid out by flowLayout; drawn here, magnified to the slice the
// minimap beside it chooses.

import * as d3 from "d3";
import {
    FLOW_COLORS, flowKind, isStub, markedFlow, nodeBarColor, ribbonOpacity, ribbonPath, ribbonPoint, zoomFlows,
} from "../flowLayout.js";
import {FLOW_SIDES, OTHER_LABEL, REMOVED_LABEL, flowCategories, flowSides} from "../../utils/comparison.js";
import {formatDrift} from "../../utils/drift.js";
import {escapeHtml} from "../../utils/html.js";
import {clamp} from "../../utils/visCommon.jsx";
import {formatCount} from "../binnedPlot.js";
import {MARGIN, drawEmpty, titleChip} from "./frames.js";
import {roleName} from "./tooltip.js";
import {drawAnnotationBubble, formatShare} from "./driftCommon.js";

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

/* Where the Sankey sits in a canvas this tall, so the minimap beside it lines up */
export function flowsFrame(height) {
    return {top: MARGIN.top, height: Math.max(10, height - MARGIN.top - MARGIN.bottom), total: height};
}

/* The categories the Sankey draws: the ones the server sent, less any the reader has hidden. A hidden
   category keeps no band and takes no room; the ribbons that reached it are cut short instead. */
export function shownCategories(data, hidden) {
    return flowCategories(data).filter((label) => !hidden.includes(label));
}

/* What the catch-all band holds, for its tooltip: the biggest categories folded into it with their rows, and
   a count of the rest. It is the one band that stands for several categories, so this is the only way to see
   what is inside it short of taking one back out. */
function otherTooltip(other) {
    const listed = other.categories.slice(0, OTHER_LISTED);
    const rest = other.categories.length - listed.length + other.more;
    let restNote = "";
    if (rest > 0) restNote = `<br>and ${formatCount(rest)} more`;
    return `<strong>${OTHER_LABEL}</strong> · ${formatCount(other.rows)} rows in `
        + `${formatCount(other.categories.length + other.more)} categories<br>`
        + listed.map((row) => `${escapeHtml(row.category)} · ${formatCount(row.rows)}`).join("<br>")
        + restNote;
}

// Along a ribbon from its middle outward, the order its annotation looks for a point still in sight
const RIBBON_STEPS = d3.range(11).flatMap((k) => (k ? [0.5 - k * 0.05, 0.5 + k * 0.05] : [0.5]));

/* A ribbon's tooltip: how many rows went from one category to the other, and what share of root's that is */
function ribbonTooltip(r, side, where, ctx) {
    const gone = [r.source, r.target].filter((label) => where(label) === "hidden");
    // A hidden source draws no band, so there is no total to take a share of
    const out = side.sources.get(r.source)?.rows;
    const base = escapeHtml(ctx.labels.base);
    let html = `<strong>${escapeHtml(r.source)} → ${escapeHtml(r.target)}</strong><br>`
        + `${formatCount(r.rows)} rows from ${base} into ${escapeHtml(ctx.labels[side.id])}`;
    if (out) html += ` · ${formatShare(r.rows / out)} of ${base}'s ${escapeHtml(r.source)}`;
    if (gone.length) html += `<br>${escapeHtml(gone.join(" and "))} hidden — add back from Categories`;
    return html;
}

/* One side's ribbons, from root's edge at x0 out to its own column at x1 - leftward for A. A ribbon cut short
   because its other category is hidden is drawn as a stub - see ribbonPath. */
function drawRibbons(g, side, {x0, x1, where, clip}, ctx) {
    const paths = g.append("g").attr("clip-path", clip)
        .selectAll("path").data(side.placed).join("path")
        .attr("class", (r) => `compare-mark ${isStub(r) ? "compare-flow-stub" : ""}`)
        .attr("d", (r) => ribbonPath(r, x0, x1))
        .attr("fill", (r) => FLOW_COLORS[flowKind(r)])
        .attr("fill-opacity", ribbonOpacity);
    ctx.tooltip.attach(paths, (r) => ribbonTooltip(r, side, where, ctx));
}

/* A category's bar or box is what the reader clicks to pick it out, in any of the three columns, and Delete
   then hides it - the panel owns both, so the click only reports which category it was */
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
    return clamp((n.y0 + n.y1) / 2, top + LABEL_INSET, bottom - LABEL_INSET);
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
            .attr("fill", nodeBarColor(n));
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
        let name = band.label;
        if (band.label.length > fits) name = `${band.label.slice(0, fits)}…`;
        text.append("tspan").text(name);
        if (count) text.append("tspan").attr("class", "compare-flow-count").text(count);

        if (band.label === OTHER_LABEL && other) ctx.tooltip.attach(item, () => otherTooltip(other));
    });
}

// Why a category of the marked ribbon cannot be seen: it is hidden, or scrolled above or below the window
function whereCategoryIs(label, place) {
    if (place === "hidden") return `${label} is hidden`;
    return `${label} is ${place} the categories shown`;
}

/* Where a side's annotation should point - at markedFlow's ribbon, or the nearest part of it in sight - and,
   when part of that ribbon is out of sight, a sentence saying where */
function flowAnchor(side, {x0, x1}, where, h) {
    const marked = markedFlow(side.flows);
    if (!marked) return null;
    const off = [...new Set([marked.source, marked.target])]
        .map((label) => [label, where(label)])
        .filter(([, place]) => place);
    let aside = null;
    if (off.length) {
        const reasons = off.map(([label, place]) => whereCategoryIs(label, place));
        aside = `(${reasons.join(" and ")}.)`;
    }

    /* The middle of the ribbon, or the nearest part of it still in sight. A ribbon wholly out of sight - or one
       to the sink from a hidden category, which is not drawn - gets the edge it lies beyond. */
    const ribbon = side.placed.find((r) => r.source === marked.source && r.target === marked.target);
    let inSight = null;
    if (ribbon) {
        const points = RIBBON_STEPS.map((t) => ribbonPoint(ribbon, x0, x1, t));
        inSight = points.find(([, y]) => y >= 0 && y <= h);
    }
    if (inSight) return {ax: inSight[0], ay: inSight[1], aside};

    let beyond;
    if (ribbon) beyond = ribbonPoint(ribbon, x0, x1, 0.5)[1] < 0;
    else beyond = where(marked.source) === "above";
    return {ax: (x0 + x1) / 2, ay: beyond ? 0 : h, aside};
}

/* A side's title over its half, on two lines: whose rows the half follows, and that node's drift from root.
   B's is set against the right edge, mirroring A's on the left. compact keeps to the node's name and its drift,
   for a canvas too narrow for the full titles. */
function flowSideTitle(g, side, detail, {align}, w, ctx, compact) {
    const header = g.append("g");
    const title = header.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -26)");
    const name = compact ? ctx.labels[side.id] : roleName(side.id, ctx);
    titleChip(title, 0, side.id, name);
    let subtitle = `drift ${formatDrift(detail?.distortion?.value)}`;
    if (!compact) subtitle = `vs ${ctx.labels.base} · ${subtitle}`;
    header.append("text").attr("class", "compare-panel-subtitle").attr("y", -10).text(subtitle);
    if (align === "end") header.attr("transform", `translate(${w - header.node().getBBox().width}, 0)`);
    return header;
}

/* Where everything sits across a canvas w wide: root's box in the middle, and each side running from root's
   edge (x0) out to its own column (x1), its bubble kept to its own half */
function flowFrames(w, sideCount) {
    // Never under enough for the removed sink's name, which a narrow canvas stacks over its count
    const room = Math.max(64, Math.min(COUNT_ROOM, w * 0.14));
    const rootWidth = Math.min(ROOT_BOX, w * 0.22);
    // A single node's flows run out to the right only, so root moves left to give them the room
    const rootLeft = sideCount > 1 ? (w - rootWidth) / 2 : Math.min(w * 0.25, room + FLOW_NODE);
    const rootRight = rootLeft + rootWidth;
    return {
        root: {left: rootLeft, width: rootWidth},
        a: {x0: rootLeft, x1: room + FLOW_NODE, bar: room, anchor: "end", labelX: room - 6, align: "start",
            bounds: {left: 0, right: rootLeft}},
        b: {x0: rootRight, x1: w - room - FLOW_NODE, bar: w - room - FLOW_NODE, anchor: "start", labelX: w - room + 6,
            align: "end", bounds: {left: rootRight, right: w}},
    };
}

/* Three titles share the line over the plot: each side's, and root's between them. Where the canvas is too
   narrow for them, each side drops to its node's name and root to its own, rather than running into one
   another. */
function drawFlowTitles(g, {data, sides, frames, detail, w}, ctx) {
    const rootHeader = g.append("g");
    const rootMiddle = frames.root.left + frames.root.width / 2;
    rootHeader.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -26)")
        .append("text").attr("x", rootMiddle).attr("text-anchor", "middle").text(ctx.labels.base);
    const rootSubtitle = rootHeader.append("text").attr("class", "compare-panel-subtitle")
        .attr("x", rootMiddle).attr("y", -10).attr("text-anchor", "middle")
        .text(data.base ? "common ancestor" : "original upload");

    const titles = (compact) => sides.map((side) => flowSideTitle(g, side, detail[side.id], frames[side.id], w, ctx, compact));
    const headers = titles(false);
    // Left to right as they sit: selection A's title if there is one, root's, then selection B's
    let ordered = [rootHeader, headers[0]];
    if (sides.length > 1) ordered = [headers[0], rootHeader, headers[1]];
    const boxes = ordered.map((one) => one.node().getBoundingClientRect());
    const overlapping = boxes.some((box, i) => i > 0 && boxes[i - 1].right + 8 > box.left);
    if (overlapping) {
        headers.forEach((one) => one.remove());
        rootSubtitle.remove();
        titles(true);
    }
}

/* Where the rows went in this column, from root out to each selected node: into the same category, into
   another, or out of the table. Root sits in the middle with the category names; selection A's flows run out
   to the left and selection B's to the right, so each half is one node's change from root, and the two share
   root's categories and the window.

   This is churn's picture rather than TVD's - rows swapping between two categories are ribbons here while
   leaving the shares, and so the drift number, unchanged - so both numbers sit beneath each half.
   ctx.world is the whole Sankey laid out unzoomed, and ctx.range the slice of it the minimap beside the plot
   shows - [f0, f1] as shares of its height - or null for all of it. */
export function drawFlows(svg, data, ctx) {
    const categories = shownCategories(data, ctx.hidden);
    if (!categories.length) {
        return drawEmpty(svg, ctx, "Every category is hidden — bring some back from the Categories list");
    }

    // One panel across the canvas's full width: the outer columns' counts take the room an axis would
    const w = ctx.width;
    const h = Math.max(10, ctx.height - MARGIN.top - MARGIN.bottom);
    const g = svg.append("g").attr("transform", `translate(0, ${MARGIN.top})`);

    const sides = FLOW_SIDES.filter((side) => ctx.roles.includes(side.id));
    const frames = flowFrames(w, sides.length);

    const layout = zoomFlows(ctx.world, ctx.range, h);
    const detail = flowSides(data);
    // Zoomed in, the ribbons and columns out of sight would otherwise draw over the titles and the numbers beneath
    g.append("clipPath").attr("id", ctx.clipId).append("rect").attr("width", w).attr("height", h);
    const clip = `url(#${ctx.clipId})`;

    drawFlowTitles(g, {data, sides, frames, detail, w}, ctx);

    // Back to front: ribbons, then the columns over their ends, then the bubbles over everything
    sides.forEach((side) => {
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
    drawRootColumn(columns, layout, {left: frames.root.left, width: frames.root.width, h}, ctx);
    layout.sides.forEach((side) => drawNodeColumn(columns, side, {...frames[side.id], inView: layout.inView, width: w, h}, ctx));
    layout.sides.forEach((side) => {
        const frame = frames[side.id];
        const anchor = flowAnchor(side, frame, layout.where, h);
        if (anchor) {
            drawAnnotationBubble(g, {...anchor, bounds: {...frame.bounds, top: 0, bottom: h}}, side.id, detail[side.id], ctx);
        }
    });
}
