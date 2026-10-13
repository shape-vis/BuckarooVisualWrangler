// ComparisonPlot.jsx
// Draws two nodes' data against each other for the compare panel. The data arrives from
// /api/pgraph/compare already binned on axes both states share - see app/db_utils/compare_sql.py - so every
// view here can put the two on the same scales. The views themselves are in compare/.

import {useCallback, useEffect, useId, useMemo, useRef, useState} from "react";
import * as d3 from "d3";
import RidgelineBrush, {STRIP_CHROME} from "./RidgelineBrush.jsx";
import SankeyMinimap from "./SankeyMinimap.jsx";
import {FLOW_COLORS, layoutFlows, panRange} from "./flowLayout.js";
import {NEUTRAL_FILL} from "./binnedPlot.js";
import {
    differenceColors, drawHeatmapDifference, drawHeatmapSide, drawHistogramDifference, drawHistogramOverlay,
    drawHistogramSide, sequentialColor,
} from "./compare/binnedViews.js";
import {RIDGE_PADDING, drawRidgeline, ridgelineFrame, ridgelineOverview} from "./compare/ridgeline.js";
import {drawFlows, flowsFrame, shownCategories} from "./compare/flows.js";
import {DRIFT_BASE_COLOR} from "./compare/driftCommon.js";
import {MARGIN, drawEmpty} from "./compare/frames.js";
import {makeTooltip, roleName} from "./compare/tooltip.js";
import {wheelPixels} from "../utils/visCommon.jsx";
import {domSafeId} from "../utils/html.js";
import {ERROR_DIMENSIONS, errorColors} from "../store/errorColors.js";
import {FLOW_SIDES, MEASURES, ROLE_COLORS, flowSides, nodeName} from "../utils/comparison.js";
import {driftZoomKey} from "../utils/comparisonSpec.js";
import {useHostWindow} from "../store/HostWindowContext.jsx";

// Below this the canvas is mid-resize or collapsed, and there is nothing useful to lay out
const MIN_CANVAS = 120;

// Which kind of column each drift view draws, so a result for the last column is never drawn as the next
const DRIFT_VIEW_KINDS = {ridgeline: "numeric", flows: "categorical"};

// The gap between the canvas and the strip under it, as .compare-plot-body sets it
const BODY_GAP = 8;
// Root's row never shrinks below this, however small the panel
const MIN_STRIP_CURVE = 40;

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

// ── Legend ───────────────────────────────────────────────────────────────────

function legendItems(kind, view, measure, labels, roles) {
    const ctx = {roles, labels};

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
            {label: base, style: {background: DRIFT_BASE_COLOR}},
            ...roles.map((role) => ({label: roleName(role, ctx), style: {background: ROLE_COLORS[role]}})),
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
        if (measure !== "items") items.push({label: "Rows, none flagged", style: {background: NEUTRAL_FILL}});
        return items;
    }

    if (kind === "histogram" && view === "overlay") {
        return ["a", "b"].map((role) => ({label: roleName(role, ctx), style: {background: ROLE_COLORS[role]}}));
    }

    return errorItems;
}

const FLOWS_HINT = "Hover a bubble for what changed where it points. Click a category to select it, or scroll to move when zoomed.";
const RIDGELINE_HINT = "Hover a bubble for what changed where it points, or the curves for each node's share at that value.";

/* The line under a drift plot: the category picked out for hiding, what the hovered bubble says, or a hint */
function CompareNote({selected, note, roles, view}) {
    if (selected) {
        return (
            <>
                <span className="compare-note-role">{selected}</span>
                selected — press Delete to hide it. It stays in the Categories list to bring back.
            </>
        );
    }
    if (note) {
        // Named from the label the bubble reported, which is the one its plot was drawn with
        const noteCtx = {roles, labels: {[note.role]: note.label}};
        return (
            <>
                <span className="compare-note-role" style={{color: ROLE_COLORS[note.role]}}>
                    {roleName(note.role, noteCtx)}
                </span>
                {note.text}
            </>
        );
    }
    return <span className="compare-note-hint">{view === "flows" ? FLOWS_HINT : RIDGELINE_HINT}</span>;
}

// The sides a result draws: both selections, or just the one node a single-node result is about
const BOTH_ROLES = ["a", "b"];
const SINGLE_ROLES = ["b"];

/**
 * The compare panel's plot.
 *
 * Props:
 *  - data: a /api/pgraph/compare response, or null while there is none to show. A drift result carries base,
 *    the common ancestor its views are measured from, or null for root
 *  - view: "side" | "overlay" | "difference", or for drift "ridgeline" | "flows" -
 *    which the kind supports is the panel's call
 *  - measure: a MEASURES key, read by difference views and heatmaps
 *  - labelA, labelB: short names for selection A and selection B
 *  - hidden: the Sankey's categories the reader has taken out of the view, by name
 *  - onHide: called with a category when its bar is selected and Delete pressed
 *  - zoom: {key, range} - how far a drift plot is zoomed, and the driftZoomKey it was zoomed for
 *  - onZoom: called with the next {key, range}, or with an updater taking the last
 *  - compact: just the plot, without the zoom strip, the note or the legend - for a preview too small for them
 *
 * A result with single set is about one node, carried as both sides; only selection B's side is drawn.
 */
export default function ComparisonPlot({data, view, measure, labelA, labelB, hidden = [], onHide, zoom, onZoom,
                                           compact = false}) {
    const roles = data?.single ? SINGLE_ROLES : BOTH_ROLES;
    const hostWindow = useHostWindow();
    const canvasRef = useRef(null);
    const svgRef = useRef(null);
    const tooltipRef = useRef(null);
    const [size, setSize] = useState({width: 0, height: 0});
    // What the hovered annotation bubble says, shown under the plot rather than over it
    const [note, setNote] = useState(null);

    /* The part of the column a zoomed ridgeline or Sankey shows, stamped with the column, nodes and reference it
       was chosen for. Another column, node pair or reference reads it as unzoomed, so a stale zoom lapses without an
       effect to reset it - a new reference refits the ridgeline's grid, so its old window means nothing. */
    const zoomKey = data?.kind === "drift"
        ? driftZoomKey({x: data.x, a: data.a.node, b: data.b.node, base: data.base})
        : null;
    const range = zoom?.key === zoomKey ? zoom.range : null;
    // The brush and the minimap report on every move, often the same range; only a new one is worth a redraw
    const zoomTo = useCallback((next) => onZoom?.((previous) => {
        const unchanged = previous.key === zoomKey && String(previous.range) === String(next);
        if (unchanged) return previous;
        return {key: zoomKey, range: next};
    }), [zoomKey, onZoom]);

    // Ids are unique per page, and useId's own characters are not all safe in a url(#...) reference
    const clipId = `compare-ridge-clip${domSafeId(useId())}`;
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
        hostWindow.document.addEventListener("keydown", onKeyDown);
        return () => hostWindow.document.removeEventListener("keydown", onKeyDown);
    }, [selected, onHide, setSelected, hostWindow]);
    // While the next column loads, the last one's drift result stays up - but only under a view for its kind
    const stale = data?.kind === "drift" && (data.a.kind ?? data.b.kind) !== DRIFT_VIEW_KINDS[view];

    /* The canvas takes whatever room the panel gives it, and the plot is laid out from that. The observers are
       the host window's: one from this page is only checked as this page renders, which a popped-out panel's
       window does not wait on. */
    useEffect(() => {
        const observer = new hostWindow.ResizeObserver(([entry]) => {
            setSize({width: entry.contentRect.width, height: entry.contentRect.height});
        });
        observer.observe(canvasRef.current);
        return () => observer.disconnect();
    }, [hostWindow]);

    /* The height the canvas and the ridgeline's strip share. It does not change as they split it, so the strip
       can be sized from it without the canvas's answer feeding back into the strip's - see ridgelineCurve. */
    const bodyRef = useRef(null);
    const [bodyHeight, setBodyHeight] = useState(0);
    useEffect(() => {
        const observer = new hostWindow.ResizeObserver(([entry]) => setBodyHeight(entry.contentRect.height));
        observer.observe(bodyRef.current);
        return () => observer.disconnect();
    }, [hostWindow]);

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
                labels: {a: labelA, b: labelB, base: labelBase}, roles,
            });
        }

        return () => {
            tooltip.hide();
            setNote(null);
            svg.selectAll("*").remove();
        };
    }, [data, view, measure, labelA, labelB, labelBase, size, stale, range, clipId, hidden, selected, setSelected, flowsWorld,
        roles]);

    /* Over a zoomed Sankey the wheel scrolls it, as it would a long page. Attached by hand, since React's own wheel
       handler is passive and could not keep the page from scrolling too. */
    useEffect(() => {
        const canvas = canvasRef.current;
        if (view !== "flows" || !range) return undefined;
        const onWheel = (event) => {
            const next = panRange(range, (wheelPixels(event) / flowsHeight) * (range[1] - range[0]));
            if (next === range) return;
            event.preventDefault();
            zoomTo(next);
        };
        canvas.addEventListener("wheel", onWheel, {passive: false});
        return () => canvas.removeEventListener("wheel", onWheel);
    }, [view, range, flowsHeight, zoomTo]);

    /* The zoom strip shares the body's height with the canvas and gives way to it: in a small box - a sub-node -
       it shows only while the canvas keeps the room it needs to draw, so the plot itself never goes missing. The
       body's height does not change as the two split it, so this cannot feed back into itself. */
    const stripCurve = ridgelineCurve(bodyHeight);
    const stripFits = bodyHeight - BODY_GAP - STRIP_CHROME - stripCurve >= MIN_CANVAS;
    // A canvas too small for even the plot says so, rather than staying blank
    const tooSmall = Boolean(data) && size.width > 0 && (size.width < MIN_CANVAS || size.height < MIN_CANVAS);

    return (
        <div className="compare-plot-frame">
            <div ref={bodyRef} className="compare-plot-body">
                <div className="compare-plot-stage">
                    {/* A click that misses a category clears the selection */}
                    <div ref={canvasRef} className="compare-plot-canvas" onClick={() => setSelected(null)}>
                        <svg ref={svgRef} width={size.width} height={size.height}/>
                        <div ref={tooltipRef} className="compare-tooltip"/>
                        {tooSmall && <div className="compare-plot-small">Make this larger to see the plot</div>}
                    </div>
                    {!compact && view === "flows" && flowsWorld && !stale && size.height >= MIN_CANVAS && (
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
                {!compact && view === "ridgeline" && overview && !stale && size.width >= MIN_CANVAS && stripFits && (
                    // Keyed on the column and nodes, so a new pair starts with a fresh brush rather than the last box
                    <RidgelineBrush
                        key={zoomKey}
                        {...overview}
                        frame={ridgelineFrame(size.width)}
                        rootColor={DRIFT_BASE_COLOR}
                        baseLabel={labelBase}
                        curve={stripCurve}
                        range={range}
                        onRange={zoomTo}
                    />
                )}
            </div>
            {!compact && data?.kind === "drift" && (
                <div className="compare-note" aria-live="polite">
                    <CompareNote selected={selected} note={note} roles={roles} view={view}/>
                </div>
            )}
            {!compact && data && (
                <div className="compare-legend">
                    {legendItems(data.kind, view, measure, {a: labelA, b: labelB, base: labelBase}, roles).map((item) => (
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
