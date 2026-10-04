// flowLayout.js
// The Flows view's Sankey as geometry: where every category, node, sink and ribbon sits. Laid out once at the
// unzoomed scale - the "world" - and then drawn twice: magnified to a slice of it in the plot, and whole and
// narrow in the minimap beside it. Kept apart from both so neither has to import the other.

import * as d3 from "d3";
import { FLOW_SIDES, REMOVED_LABEL, flowSides } from "../utils/comparison.js";

// Rows that stayed in their category, were recoded into another, or were deleted
export const FLOW_COLORS = {stayed: "#94a3b8", recoded: "#f59e0b", removed: "#4b5563"};
// The gap between one category's band and the next, at the unzoomed scale
export const FLOW_PAD = 6;
// Room kept for a removed sink, however few rows it takes, so its label still fits
export const REMOVED_ROOM = 14;
// How far a ribbon to a hidden category runs before it stops, as a share of its full span
export const STUB = 0.5;

/* What a ribbon shows, which sets its colour */
export const flowKind = (r) => (r.target === REMOVED_LABEL ? "removed" : r.target === r.source ? "stayed" : "recoded");

/* A ribbon cut short because one of its categories is hidden */
export const isStub = (r) => r.ya === null || r.yb === null;

/* The flow a side's annotation points at: the biggest that actually moved - recoded or removed - or failing
   that the biggest of all, so a column where nothing moved can still say so */
export function markedFlow(flows) {
    const moved = flows.flows.filter((flow) => flow.target !== flow.source);
    return d3.greatest(moved.length ? moved : flows.flows, (flow) => flow.rows);
}

/* The Sankey's world: root's categories in the middle, each one's rows flowing out to the left into selection A
   and out to the right into selection B, and each side's deleted rows into a sink in the middle of its own
   column. Ribbons are always square-root width: at true width a category holding a handful of rows is a
   hairline, and these columns usually hold most of their mass in one category. The trade is that a ribbon's
   width no longer reads as its count, so every node carries its count as a label.

   The plot is one tall stack of categories, each a band running across all three columns, so a category keeps
   one row from A through root to B, and one that kept its rows is a level ribbon on both sides. Each column's
   stack is centred in its band - root's box is as tall as the bigger of its two sides. Everything fits in h, the
   plot's height when nothing is zoomed; zoomFlows magnifies part of it.

   :param categories: the categories shown, in order - the ones the reader has hidden left out
   :return: {bands, roots, sides} - roots maps a category to root's box, and each side drawn carries its
            sources (root's edge of its ribbons), its targets (its own column, the sink among them) and its
            placed ribbons */
export function layoutFlows(data, categories, h) {
    const shown = new Set(categories);
    const sum = (ribbons, key, label, value) => d3.sum(ribbons.filter((ribbon) => ribbon[key] === label), (ribbon) => ribbon[value]);

    // A side whose node dropped the column has no flows, and leaves its half empty
    const detail = flowSides(data);
    const sides = FLOW_SIDES.filter((side) => detail[side.id]?.flows).map((side) => {
        const flows = detail[side.id].flows;
        const ribbons = flows.flows.map((flow) => ({...flow, size: Math.sqrt(flow.rows)}));
        // A hidden category has no band for its deletes to leave from, so the sink takes only the shown ones'
        const sunk = ribbons.filter((ribbon) => ribbon.target === REMOVED_LABEL && shown.has(ribbon.source));
        return {
            ...side, flows, ribbons, sunk,
            pinned: flows.targets.includes(REMOVED_LABEL),
            sinkSize: d3.sum(sunk, (ribbon) => ribbon.size),
            out: (label) => sum(ribbons, "source", label, "size"),
            into: (label) => sum(ribbons, "target", label, "size"),
        };
    });

    // A band is as tall as its tallest stack: either side's edge of root, or either node's own column
    const bands = categories.map((label) => ({
        label, size: d3.max(sides.flatMap((side) => [side.out(label), side.into(label)])) ?? 0,
    }));

    /* The scale that fills the plot with the bands and the bigger sink, a gap between each. A sink that takes few
       rows still gets room for its label. */
    const pinned = sides.some((side) => side.pinned);
    const sinkSize = d3.max(sides, (side) => side.sinkSize) ?? 0;
    const filled = bands.filter((band) => band.size > 0);
    const bandsSize = d3.sum(filled, (band) => band.size);
    const gaps = FLOW_PAD * (Math.max(0, filled.length - 1) + (pinned ? 1 : 0));
    let scale = Math.max(0, (h - gaps) / ((bandsSize + sinkSize) || 1));
    if (pinned && sinkSize * scale < REMOVED_ROOM) scale = Math.max(0, (h - gaps - REMOVED_ROOM) / (bandsSize || 1));

    /* The sinks are a row of their own, slotted in among the categories where its middle lands nearest the
       middle of the stack. Under the stack, every removal ribbon dived to the bottom and dragged the whole
       Sankey into a saddle; in the middle, the categories above send theirs down and those below send theirs
       up, so the removals fan in evenly and every kept category still runs level. */
    const sinkRow = pinned ? Math.max(sinkSize * scale, REMOVED_ROOM) : 0;
    let sinkAt = bands.length;
    if (pinned) {
        const total = d3.sum(filled, (band) => band.size * scale) + gaps + sinkRow;
        let nearest = Infinity;
        let cursor = 0;
        for (let i = 0; i <= bands.length; i += 1) {
            const off = Math.abs(cursor + sinkRow / 2 - total / 2);
            if (off < nearest) [nearest, sinkAt] = [off, i];
            if (i < bands.length && bands[i].size) cursor += bands[i].size * scale + FLOW_PAD;
        }
    }

    let top = 0;
    let sinkTop = null;
    bands.forEach((band, i) => {
        if (pinned && i === sinkAt) {
            sinkTop = top;
            top += sinkRow + FLOW_PAD;
        }
        Object.assign(band, {y0: top, y1: top + band.size * scale});
        if (band.size) top = band.y1 + FLOW_PAD;
    });
    if (pinned && sinkTop === null) sinkTop = top;

    // A stack this size, centred in its band
    const stack = (band, size, rows) => {
        const at = band.y0 + (band.size - size) * scale / 2;
        return {label: band.label, y0: at, y1: at + size * scale, rows};
    };

    // Both sides start from all of root's rows, so either counts a category's rows in root
    const roots = new Map();
    bands.forEach((band) => {
        const widest = d3.greatest(sides, (side) => side.out(band.label));
        const size = widest?.out(band.label);
        if (size) roots.set(band.label, stack(band, size, sum(widest.ribbons, "source", band.label, "rows")));
    });

    sides.forEach((side) => {
        side.sources = new Map();
        side.targets = new Map();
        bands.forEach((band) => {
            const out = side.out(band.label);
            const into = side.into(band.label);
            if (out) side.sources.set(band.label, stack(band, out, sum(side.ribbons, "source", band.label, "rows")));
            if (into) side.targets.set(band.label, stack(band, into, sum(side.ribbons, "target", band.label, "rows")));
        });
        // Each side's sink is centred in the row, as each column's stack is in its band
        if (side.pinned) {
            const at = sinkTop + (sinkRow - side.sinkSize * scale) / 2;
            side.targets.set(REMOVED_LABEL, {
                label: REMOVED_LABEL, y0: at, y1: at + side.sinkSize * scale,
                rows: d3.sum(side.sunk, (ribbon) => ribbon.rows), total: sum(side.ribbons, "target", REMOVED_LABEL, "rows"),
            });
        }
        side.placed = placeRibbons(side, categories, shown, scale, sinkAt);
    });

    return {bands, roots, sides};
}

/* Ribbons leave each of root's categories in target order and arrive at each target in source order, which
   keeps them from crossing more than the flows themselves require. The sink takes its row's place in that
   order, sinkAt among the categories, so a category above it sends its removals from the bottom of its stack
   and one below sends them from the top - each toward the sink, past none of its own ribbons. A ribbon whose
   category was hidden keeps only the end that is still drawn - ya or yb is null, and it is cut short there. A
   ribbon to the sink from a hidden category has nowhere to leave from, and is left out. */
function placeRibbons(side, categories, shown, scale, sinkAt) {
    const stacked = [...categories.slice(0, sinkAt), REMOVED_LABEL, ...categories.slice(sinkAt)];
    const order = new Map([...new Set([...stacked, ...side.flows.sources, ...side.flows.targets])]
        .map((label, i) => [label, i]));
    const fromCursor = new Map([...side.sources].map(([label, n]) => [label, n.y0]));
    const toCursor = new Map([...side.targets].map(([label, n]) => [label, n.y0]));
    return side.ribbons
        .filter((ribbon) => ribbon.target !== REMOVED_LABEL || shown.has(ribbon.source))
        // Neither end still drawn leaves nothing to hang a ribbon from
        .filter((ribbon) => side.sources.has(ribbon.source) || side.targets.has(ribbon.target))
        .sort((a, b) => (order.get(a.source) - order.get(b.source)) || (order.get(a.target) - order.get(b.target)))
        .map((ribbon) => {
            const thickness = ribbon.size * scale;
            const ya = fromCursor.get(ribbon.source);
            const yb = toCursor.get(ribbon.target);
            if (ya !== undefined) fromCursor.set(ribbon.source, ya + thickness);
            if (yb !== undefined) toCursor.set(ribbon.target, yb + thickness);
            return {...ribbon, thickness, ya: ya ?? null, yb: yb ?? null};
        });
}

/* The camera over the world: a copy with every y mapped so the slice range names - [f0, f1], as shares of the
   world's height h - fills the plot, and every thickness magnified to match. The world itself is left alone,
   since the minimap draws it as it is. range null is the whole world, unmagnified.

   :return: {bands, roots, sides, where, inView} - where names a category out of sight ("hidden", "above" or
            "below"), and inView says whether a node shows any of itself in the plot */
export function zoomFlows(world, range, h) {
    const [f0, f1] = range ?? [0, 1];
    const k = 1 / (f1 - f0);
    const y = (value) => (value - f0 * h) * k;
    const node = (n) => ({...n, y0: y(n.y0), y1: y(n.y1)});
    const nodes = (map) => new Map([...map].map(([label, n]) => [label, node(n)]));

    const bands = world.bands.map(node);
    const sides = world.sides.map((side) => ({
        ...side,
        sources: nodes(side.sources),
        targets: nodes(side.targets),
        placed: side.placed.map((r) => ({
            ...r, thickness: r.thickness * k, ya: r.ya === null ? null : y(r.ya), yb: r.yb === null ? null : y(r.yb),
        })),
    }));

    const byLabel = new Map(bands.map((band) => [band.label, band]));
    // Both sinks share one row, so either says whether they are in sight
    const sink = sides.map((side) => side.targets.get(REMOVED_LABEL)).find(Boolean);
    const where = (label) => {
        const at = label === REMOVED_LABEL ? sink : byLabel.get(label);
        if (!at) return "hidden";
        return at.y1 <= 0 ? "above" : at.y0 >= h ? "below" : null;
    };
    const inView = (n) => n.y1 > 0 && n.y0 < h;
    return {bands, roots: nodes(world.roots), sides, where, inView};
}

/* A zoomed range moved by delta - a share of the world - and stopped at either end. The same range back means
   it could not move, so a wheel event can be left to the page. */
export function panRange(range, delta) {
    if (!range) return range;
    const span = range[1] - range[0];
    const start = Math.min(Math.max(range[0] + delta, 0), 1 - span);
    return start === range[0] ? range : [start, start + span];
}

/* A ribbon's outline, from root's edge at x0 out to a node's column at x1 - leftward for A, which the same path
   draws without change. One with both ends drawn runs the full span. One whose other end was hidden is a stub:
   it leaves the end that remains, runs part of the way and stops, so a reader can see that rows went somewhere
   without the category being in the picture. */
export function ribbonPath(r, x0, x1) {
    if (r.ya === null) {
        const from = x1 - STUB * (x1 - x0);
        return `M${from},${r.yb} H${x1} V${r.yb + r.thickness} H${from} Z`;
    }
    if (r.yb === null) {
        const to = x0 + STUB * (x1 - x0);
        return `M${x0},${r.ya} H${to} V${r.ya + r.thickness} H${x0} Z`;
    }
    const middle = (x0 + x1) / 2;
    return `M${x0},${r.ya} C${middle},${r.ya} ${middle},${r.yb} ${x1},${r.yb} `
        + `L${x1},${r.yb + r.thickness} C${middle},${r.yb + r.thickness} ${middle},${r.ya + r.thickness} ${x0},${r.ya + r.thickness} Z`;
}

/* A point along a ribbon's centre line, t running from root's end (0) to the node's (1). A stub has only its
   drawn end, so any t lands on the middle of what is left of it. */
export function ribbonPoint(r, x0, x1, t) {
    if (r.ya === null) return [x1 - STUB * (x1 - x0) / 2, r.yb + r.thickness / 2];
    if (r.yb === null) return [x0 + STUB * (x1 - x0) / 2, r.ya + r.thickness / 2];
    const middle = (x0 + x1) / 2;
    const [ya, yb] = [r.ya + r.thickness / 2, r.yb + r.thickness / 2];
    const [a, b, c, d] = [(1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3];
    return [a * x0 + (b + c) * middle + d * x1, (a + b) * ya + (c + d) * yb];
}
