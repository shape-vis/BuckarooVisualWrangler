// SankeyMinimap.jsx
// The strip beside the Flows Sankey, as VS Code's minimap is to a file: the whole Sankey drawn small - the same
// layout the plot magnifies, so the two always agree - and a box over the part the plot shows. Drag the box to
// scroll, pull its top or bottom edge to zoom, or click anywhere else to jump there. Drawn by React, with the
// pointer handled here rather than by a brush: a brush draws selections, and this box only ever moves or resizes.

import {useEffect, useRef, useState} from "react";
import {REMOVED_LABEL} from "../utils/comparison.js";
import {FLOW_COLORS, flowKind, isStub, markedFlow, panRange, ribbonPath, ribbonPoint} from "./flowLayout.js";

const WIDTH = 132;
// The outer columns' bars, and root's boxes in the middle
const BAR = 3;
const ROOT = 28;
// How near the box's top or bottom edge a press grabs that edge rather than the box
const EDGE = 6;
// The box never shrinks below this, so there is always something to grab
const MIN_BOX = 24;
// Drift is teal wherever it is drawn - never red
const BOX_COLOR = "#0f766e";
const HANDLE = 8;

const ROOT_LEFT = (WIDTH - ROOT) / 2;
// Each side runs from root's edge (x0) out to its bar (x1), as in the plot
const FRAMES = {
    a: {x0: ROOT_LEFT, x1: 1 + BAR, bar: 1},
    b: {x0: ROOT_LEFT + ROOT, x1: WIDTH - 1 - BAR, bar: WIDTH - 1 - BAR},
};

/* A grip on one of the box's edges, so it reads as something that can be pulled */
function Grip({y}) {
    const middle = y + HANDLE / 2;
    const left = (WIDTH - 14) / 2;
    return (
        <g className="compare-brush-grip compare-brush-grip--rows">
            <rect x={left} y={middle - 3.5} width={14} height={7} rx={2}/>
            <path d={`M${left + 4},${middle - 1} h6 M${left + 4},${middle + 1} h6`}/>
        </g>
    );
}

/**
 * The Sankey's minimap and zoom control.
 *
 * Props:
 *  - world: the whole Sankey laid out unzoomed - see layoutFlows - in the plot's own height
 *  - frame: {top, height, total} - where the Sankey sits in the plot, so the two line up
 *  - range: [f0, f1] the slice of the Sankey the plot shows, as shares of its height, or null for all of it
 *  - onRange: called with the new range, or null
 */
export default function SankeyMinimap({world, frame, range, onRange}) {
    const svgRef = useRef(null);
    const [f0, f1] = range ?? [0, 1];
    const H = frame.height;
    const minSpan = Math.min(1, MIN_BOX / H);

    /* What a press would do where the pointer is - "top", "bottom", "move" or "jump" - which sets the cursor.
       While dragging it is "dragging-" and what the drag is doing. */
    const [mode, setMode] = useState(null);
    const drag = useRef(null);

    /* A drag reports on every pointer move, but the plot only needs the latest range once a frame. A range
       covering the whole Sankey is no zoom at all. */
    const pending = useRef(null);
    const request = useRef(0);
    const send = (next) => {
        pending.current = next;
        if (request.current) return;
        request.current = requestAnimationFrame(() => {
            request.current = 0;
            const [start, end] = pending.current;
            onRange(start <= 1e-4 && end >= 1 - 1e-4 ? null : [start, end]);
        });
    };
    useEffect(() => () => cancelAnimationFrame(request.current), []);

    // The pointer's height on the minimap, as a share of the Sankey's
    const fractionAt = (event) => (event.clientY - svgRef.current.getBoundingClientRect().top - frame.top) / H;
    const modeAt = (at) => {
        const edge = EDGE / H;
        // A box short enough for both edges to be in reach gives each the half nearer it
        if (Math.abs(at - f0) <= edge && at < (f0 + f1) / 2) return "top";
        if (Math.abs(at - f1) <= edge) return "bottom";
        if (Math.abs(at - f0) <= edge) return "top";
        return at > f0 && at < f1 ? "move" : "jump";
    };

    const onPointerDown = (event) => {
        if (event.button !== 0) return;
        const at = fractionAt(event);
        if (at < 0 || at > 1) return;
        event.preventDefault();
        let start = [f0, f1];
        let next = modeAt(at);
        // A press outside the box brings the box there, centred on it, and a drag carries on from there
        if (next === "jump") {
            const span = f1 - f0;
            const top = Math.min(Math.max(at - span / 2, 0), 1 - span);
            start = [top, top + span];
            send(start);
            next = "move";
        }
        drag.current = {mode: next, at, start};
        setMode(`dragging-${next}`);
        svgRef.current.setPointerCapture(event.pointerId);
    };

    const onPointerMove = (event) => {
        const at = fractionAt(event);
        if (!drag.current) {
            const next = at < 0 || at > 1 ? null : modeAt(at);
            if (next !== mode) setMode(next);
            return;
        }
        const {mode: dragging, start: [s0, s1]} = drag.current;
        const delta = at - drag.current.at;
        if (dragging === "move") {
            const span = s1 - s0;
            const top = Math.min(Math.max(s0 + delta, 0), 1 - span);
            send([top, top + span]);
        } else if (dragging === "top") {
            send([Math.min(Math.max(s0 + delta, 0), s1 - minSpan), s1]);
        } else {
            send([s0, Math.max(Math.min(s1 + delta, 1), s0 + minSpan)]);
        }
    };

    const onPointerUp = (event) => {
        if (!drag.current) return;
        drag.current = null;
        svgRef.current.releasePointerCapture(event.pointerId);
        setMode(modeAt(fractionAt(event)));
    };

    /* The wheel over the minimap scrolls the plot, as it does over the plot itself. Attached by hand, since
       React's own wheel handler is passive and could not keep the page from scrolling too. */
    useEffect(() => {
        const svg = svgRef.current;
        const onWheel = (event) => {
            const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : 1);
            const next = panRange(range, pixels / H);
            if (next === range) return;
            event.preventDefault();
            onRange(next);
        };
        svg.addEventListener("wheel", onWheel, {passive: false});
        return () => svg.removeEventListener("wheel", onWheel);
    }, [range, H, onRange]);

    const reset = () => onRange(null);

    // Each side's bubble gets a dot where its ribbon is, so there is somewhere to aim the box
    const spots = world.sides.map((side) => {
        const marked = markedFlow(side.flows);
        const ribbon = marked && side.placed.find((r) => r.source === marked.source && r.target === marked.target);
        if (!ribbon) return null;
        const {x0, x1} = FRAMES[side.id];
        const [x, y] = ribbonPoint(ribbon, x0, x1, 0.5);
        return {id: side.id, color: side.color, x, y};
    }).filter(Boolean);

    const boxTop = f0 * H;
    const boxBottom = f1 * H;

    return (
        <div className="compare-brush compare-brush--rows compare-minimap">
            <svg
                ref={svgRef}
                width={WIDTH}
                height={frame.total}
                className={mode ? `compare-minimap--${mode}` : undefined}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerLeave={() => { if (!drag.current) setMode(null); }}
            >
                <text className="compare-brush-label" x={0} y={frame.top - 14}>
                    overview
                    <title>The whole Sankey, small. The box is the part the plot shows.</title>
                </text>
                <g transform={`translate(0, ${frame.top})`}>
                    {world.sides.map((side) => {
                        const {x0, x1} = FRAMES[side.id];
                        return side.placed.map((r, i) => (
                            <path
                                key={`${side.id}-${i}`}
                                d={ribbonPath(r, x0, x1)}
                                fill={FLOW_COLORS[flowKind(r)]}
                                fillOpacity={isStub(r) ? 0.3 : flowKind(r) === "stayed" ? 0.35 : 0.7}
                            />
                        ));
                    })}
                    {[...world.roots.values()].map((n) => (
                        <rect key={`root-${n.label}`} className="compare-minimap-root"
                              x={ROOT_LEFT} y={n.y0} width={ROOT} height={Math.max(0.5, n.y1 - n.y0)}/>
                    ))}
                    {world.sides.map((side) => [...side.targets.values()].map((n) => (
                        <rect key={`${side.id}-${n.label}`} x={FRAMES[side.id].bar} y={n.y0} width={BAR}
                              height={Math.max(0.5, n.y1 - n.y0)}
                              fill={n.label === REMOVED_LABEL ? FLOW_COLORS.removed : "#475569"}/>
                    )))}
                    {spots.map((spot) => (
                        <circle key={spot.id} cx={spot.x} cy={spot.y} r={3} fill={spot.color} stroke="#ffffff" strokeWidth={1}/>
                    ))}

                    {/* Zoomed in, what the plot leaves out is faded, so the box stands out as the part in view */}
                    {range && (
                        <>
                            <rect className="compare-minimap-shade" x={0} y={0} width={WIDTH} height={boxTop}/>
                            <rect className="compare-minimap-shade" x={0} y={boxBottom} width={WIDTH} height={H - boxBottom}/>
                        </>
                    )}
                    <rect
                        x={0.5} y={boxTop} width={WIDTH - 1} height={Math.max(1, boxBottom - boxTop)}
                        fill={BOX_COLOR} fillOpacity={0.1} stroke={BOX_COLOR} strokeOpacity={0.8}
                    />
                    <Grip y={boxTop - HANDLE / 2}/>
                    <Grip y={boxBottom - HANDLE / 2}/>
                </g>
            </svg>
            {range ? (
                <button
                    type="button"
                    className="compare-brush-reset"
                    style={{top: frame.top + frame.height + 12}}
                    onClick={reset}
                >
                    Show all
                </button>
            ) : (
                <span className="compare-brush-hint" style={{top: frame.top + frame.height + 12}}>Drag an edge to zoom</span>
            )}
        </div>
    );
}
