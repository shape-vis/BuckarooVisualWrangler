// AnalysisInset.jsx
// A detail inset on the graph's analysis plot, the way a map draws one: a box on the plot around nodes sitting on
// top of one another, two leader lines out to a panel, and in the panel that region drawn large, every node
// labelled. Small wrangles on a large table barely move a node, so whole branches can clump at one point; the
// inset is where they can be told apart. Nodes with the very same numbers would still coincide however large
// the region is drawn, so those are fanned out around their shared point, each on a line back to it.
//
// Drawn inside React Flow, as the axes are, so the box can follow the plot's pan and zoom.

import * as d3 from "d3";
import { useState } from "react";
import { useStore, useViewport } from "@xyflow/react";
import { AXIS_BOTTOM, AXIS_LEFT, ROOT_COLOR, analysisTooltip, driftOf, errorOf, isPlotted } from "./analysisLayout.js";
import { nodeName } from "../utils/comparison.js";
import { hideTooltip, moveTooltip, showTooltip } from "../utils/visCommon.jsx";

// The panel's frame, and inside it the plot's margins: room for the tick labels on the left and bottom
const HEADER = 28;
const PAD = { top: 16, right: 24, bottom: 30, left: 54 };
const DOT_R = 6;
// Dots nearer than this in the panel - touching, with their labels on top of one another - are fanned out
const SPREAD_REACH = 2 * DOT_R + 8;
// Room the graph's toolbar takes at the canvas's top right, which the panel keeps clear of
const TOOLBAR_ROOM = 112;
const MARGIN = 14;

const clamp = (value, lo, hi) => Math.min(Math.max(value, lo), Math.max(lo, hi));
const labelOf = (node) => (node.type === "collapsedNode"
    ? `${nodeName(node.data.head)}…${nodeName(node.data.tail)}`
    : nodeName(node.id));

/* Where the panel opens: across the canvas from the box, so the leader lines have room and the panel covers
   none of what it details. Kept off the axes, and off the toolbar at the top right. */
function placement(box, canvas, size, axisLeft) {
    const right = (box.left + box.right) / 2 < canvas.width / 2;
    const below = (box.top + box.bottom) / 2 < canvas.height / 2;
    return {
        left: right ? canvas.width - size.width - MARGIN : axisLeft + MARGIN,
        top: below ? canvas.height - AXIS_BOTTOM - size.height - MARGIN : (right ? TOOLBAR_ROOM : MARGIN),
    };
}

/* The two leader lines: the edges of the outline around both the box and the panel that run from one to the
   other - the lines a map draws, which never cross either box */
function leaderLines(box, panel) {
    const corners = (rect, tag) => [
        [rect.left, rect.top], [rect.right, rect.top], [rect.right, rect.bottom], [rect.left, rect.bottom],
    ].map((point) => Object.assign(point, { tag }));
    const hull = d3.polygonHull([...corners(box, "box"), ...corners(panel, "panel")]);
    if (!hull) return [];
    return hull.map((point, i) => [point, hull[(i + 1) % hull.length]]).filter(([a, b]) => a.tag !== b.tag);
}

/* Fan out dots that would sit on one another: those within reach of a group's first dot join it, and a group
   of more than one is spread on a ring around that point, each dot keeping a line back to where it belongs */
function spread(items) {
    const groups = [];
    items.forEach((item) => {
        const group = groups.find((one) => Math.hypot(one.x - item.x, one.y - item.y) < SPREAD_REACH);
        if (group) group.members.push(item);
        else groups.push({ x: item.x, y: item.y, members: [item] });
    });
    return groups.flatMap((group) => {
        if (group.members.length === 1) return [{ ...group.members[0], at: group.members[0], anchor: null }];
        const radius = 14 + 3 * group.members.length;
        return group.members.map((member, i) => {
            const angle = -Math.PI / 2 + (2 * Math.PI * i) / group.members.length;
            return {
                ...member,
                at: { x: group.x + radius * Math.cos(angle), y: group.y + radius * Math.sin(angle) },
                anchor: { x: group.x, y: group.y },
            };
        });
    });
}

/* The range the panel draws along one axis: the nodes' own spread with a margin, rather than the whole box,
   which can be mostly empty - fitting the nodes is what pulls them apart. Nodes level on an axis get a small
   range around their value, a share of the box's, so they sit mid-panel. */
function fitted(values, [boxLo, boxHi]) {
    const [lo, hi] = d3.extent(values);
    const margin = hi > lo ? (hi - lo) * 0.18 : Math.max((boxHi - boxLo) * 0.05, Math.abs(lo) * 0.001, 1e-9);
    return [lo - margin, hi + margin];
}

// Ticks across a short range, at the precision their spacing needs. Neither drift nor error goes below zero.
function ticksOf(scale, count, asPercent) {
    const [lo, hi] = scale.domain();
    const values = d3.ticks(lo, hi, count).filter((value) => value >= 0);
    const step = values.length > 1 ? values[1] - values[0] : hi - lo;
    const format = asPercent
        ? (value) => `${(value * 100).toFixed(Math.max(0, d3.precisionFixed(step * 100)))}%`
        : d3.format(`.${Math.max(0, d3.precisionFixed(step))}f`);
    return values.map((value) => ({ value, at: scale(value), label: format(value) }));
}

/**
 * Props:
 *  - region: {x: [from, to], y: [from, to]} - the part of the plot to detail, in drift and error
 *  - scales: {x, y} - the plot's scales, drift and error into the canvas's own units
 *  - nodes, edges: the graph as drawn; colors: each node's branch colour
 *  - metric: the error the y axis shows
 *  - roleOf, dominatorOf: a node's part in the comparison, and what beats it
 *  - onNodeClick, onNodeDoubleClick: the graph's own handlers, so shift-click and double-click work the same here
 *  - onClose: called by the panel's close button
 */
export default function AnalysisInset({
    region, scales, nodes, edges, colors, metric, roleOf, dominatorOf, onNodeClick, onNodeDoubleClick, onClose,
}) {
    const { x: panX, y: panY, zoom } = useViewport();
    const canvas = { width: useStore((state) => state.width), height: useStore((state) => state.height) };

    // The box on the plot, carried through the pan and zoom onto the screen
    const toScreenX = (drift) => scales.x(drift) * zoom + panX;
    const toScreenY = (error) => scales.y(error) * zoom + panY;
    const box = {
        left: toScreenX(region.x[0]), right: toScreenX(region.x[1]),
        top: toScreenY(region.y[1]), bottom: toScreenY(region.y[0]),
    };

    const size = {
        width: Math.round(clamp(canvas.width * 0.42, 280, 440)),
        height: Math.round(clamp(canvas.height * 0.5, 230, 340)),
    };
    // Placed once, when the inset opens, and moved only by the reader dragging its header
    const [position, setPosition] = useState(() => placement(box, canvas, size, scales.axisLeft ?? AXIS_LEFT));
    const left = clamp(position.left, 4, canvas.width - size.width - 4);
    const top = clamp(position.top, 4, canvas.height - size.height - 4);
    const panel = { left, top, right: left + size.width, bottom: top + size.height };

    const startDrag = (event) => {
        if (event.button !== 0 || event.target.closest("button")) return;
        const handle = event.currentTarget;
        const from = { x: event.clientX, y: event.clientY, left, top };
        const move = (moveEvent) => setPosition({
            left: from.left + moveEvent.clientX - from.x,
            top: from.top + moveEvent.clientY - from.y,
        });
        const end = () => {
            handle.removeEventListener("pointermove", move);
            handle.removeEventListener("pointerup", end);
            handle.removeEventListener("pointercancel", end);
        };
        handle.setPointerCapture(event.pointerId);
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", end);
        handle.addEventListener("pointercancel", end);
    };

    const plotted = nodes.filter(isPlotted);
    const inside = plotted.filter((node) => {
        const drift = driftOf(node);
        const error = errorOf(node, metric);
        return drift >= region.x[0] && drift <= region.x[1] && error >= region.y[0] && error <= region.y[1];
    });

    // The nodes in the box, drawn large inside the panel
    const plotWidth = size.width;
    const plotHeight = size.height - HEADER;
    const x = d3.scaleLinear().domain(fitted(inside.map(driftOf), region.x)).range([PAD.left, plotWidth - PAD.right]);
    const y = d3.scaleLinear().domain(fitted(inside.map((node) => errorOf(node, metric)), region.y))
        .range([plotHeight - PAD.bottom, PAD.top]);
    const dots = spread(inside.map((node) => ({ node, x: x(driftOf(node)), y: y(errorOf(node, metric)) })));
    const dotAt = new Map(dots.map((dot) => [dot.node.id, dot.at]));
    // Edges with an end in the region, drawn to wherever the other end falls - clipped at the panel's plot
    const pointOf = (id) => {
        if (dotAt.has(id)) return dotAt.get(id);
        const node = plotted.find((one) => one.id === id);
        return node ? { x: x(driftOf(node)), y: y(errorOf(node, metric)) } : null;
    };
    const links = edges
        .filter((edge) => dotAt.has(edge.source) || dotAt.has(edge.target))
        .map((edge) => ({ edge, from: pointOf(edge.source), to: pointOf(edge.target) }))
        .filter((link) => link.from && link.to);

    const lines = leaderLines(box, panel);
    const clipId = "analysis-inset-clip";

    return (
        <>
            <svg className="analysis-inset-leaders" width={canvas.width} height={canvas.height} aria-hidden="true">
                <rect className="analysis-inset-box" x={box.left} y={box.top}
                      width={Math.max(1, box.right - box.left)} height={Math.max(1, box.bottom - box.top)}/>
                {lines.map(([a, b], i) => <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}/>)}
            </svg>

            <div className="analysis-inset" style={{ left, top, width: size.width, height: size.height }}>
                <div className="analysis-inset-header" onPointerDown={startDrag} title="Drag to move">
                    <span>Detail · {inside.length} node{inside.length === 1 ? "" : "s"}</span>
                    <button type="button" className="analysis-inset-close" onClick={onClose} aria-label="Close the detail inset">×</button>
                </div>
                <svg width={plotWidth} height={plotHeight}>
                    <defs>
                        <clipPath id={clipId}>
                            <rect x={PAD.left} y={PAD.top} width={plotWidth - PAD.left - PAD.right}
                                  height={plotHeight - PAD.top - PAD.bottom}/>
                        </clipPath>
                    </defs>

                    {/* The region's own scale, so the values are readable however small its range */}
                    {ticksOf(x, 3, false).map((tick) => (
                        <g key={`x${tick.value}`} className="analysis-inset-tick">
                            <line x1={tick.at} x2={tick.at} y1={PAD.top} y2={plotHeight - PAD.bottom}/>
                            <text x={tick.at} y={plotHeight - PAD.bottom + 14} textAnchor="middle">{tick.label}</text>
                        </g>
                    ))}
                    {ticksOf(y, 3, true).map((tick) => (
                        <g key={`y${tick.value}`} className="analysis-inset-tick">
                            <line x1={PAD.left} x2={plotWidth - PAD.right} y1={tick.at} y2={tick.at}/>
                            <text x={PAD.left - 6} y={tick.at} dy="0.32em" textAnchor="end">{tick.label}</text>
                        </g>
                    ))}

                    <g clipPath={`url(#${clipId})`}>
                        {links.map(({ edge, from, to }) => (
                            <line key={edge.id} className="analysis-inset-link" x1={from.x} y1={from.y} x2={to.x} y2={to.y}
                                  stroke={colors?.get(edge.target) ?? ROOT_COLOR}/>
                        ))}
                        {/* Each fanned-out dot's line back to the point it shares */}
                        {dots.filter((dot) => dot.anchor).map((dot) => (
                            <line key={`spoke-${dot.node.id}`} className="analysis-inset-spoke"
                                  x1={dot.anchor.x} y1={dot.anchor.y} x2={dot.at.x} y2={dot.at.y}/>
                        ))}
                        {[...new Map(dots.filter((dot) => dot.anchor).map((dot) => [`${dot.anchor.x},${dot.anchor.y}`, dot.anchor])).values()]
                            .map((anchor) => <circle key={`anchor-${anchor.x},${anchor.y}`} className="analysis-inset-anchor"
                                                      cx={anchor.x} cy={anchor.y} r={2.5}/>)}
                    </g>

                    {dots.map(({ node, at }) => {
                        const role = roleOf(node);
                        const dominator = dominatorOf(node);
                        return (
                            <g
                                key={node.id}
                                className={`analysis-inset-node ${dominator ? "analysis-inset-node--dominated" : ""}`}
                                transform={`translate(${at.x}, ${at.y})`}
                                onMouseEnter={(event) => showTooltip(analysisTooltip(node, metric, { role, dominator }), event)}
                                onMouseMove={(event) => moveTooltip(event)}
                                onMouseLeave={() => hideTooltip()}
                                onMouseDown={(event) => event.preventDefault()}
                                onClick={(event) => onNodeClick(event, node)}
                                onDoubleClick={(event) => { hideTooltip(); onNodeDoubleClick(event, node); }}
                            >
                                {role === "current" && <circle className="analysis-inset-ring analysis-inset-ring--current" r={DOT_R + 4}/>}
                                {role === "selection-a" && <circle className="analysis-inset-ring analysis-inset-ring--selection-a" r={DOT_R + 4}/>}
                                <circle r={DOT_R} fill={colors?.get(node.id) ?? ROOT_COLOR}/>
                                <text x={DOT_R + 5} y={-DOT_R - 1}>{labelOf(node)}</text>
                            </g>
                        );
                    })}
                </svg>
            </div>
        </>
    );
}
