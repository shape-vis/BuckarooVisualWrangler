import * as d3 from "d3";
import {ROLE_COLORS} from "../../utils/comparison.js";
import {useComparisonData} from "../../visualizations/useComparisonData.js";
import {ridgelineOverview} from "../../visualizations/compare/ridgeline.js";
import {shownCategories} from "../../visualizations/compare/flows.js";
import {DRIFT_BASE_COLOR} from "../../visualizations/compare/driftCommon.js";
import {
    FLOW_COLORS, flowKind, layoutFlows, nodeBarColor, ribbonOpacity, ribbonPath,
} from "../../visualizations/flowLayout.js";
import {PlotPicture} from "./SupportPlotCard.jsx";

/**
 * A drift plot in miniature: the node's real drift on one column, drawn small and bare - no axes, labels, zoom
 * strip or legend - with the column's name over it. What a drift or compare sub-node shows until it is expanded
 * to its detailed plot.
 *
 * It draws what the compare window's plot draws whole, from the same result:
 *   - a numeric column as the ridgeline's overview strip does: root's shape filled, each node's curve over it -
 *     each scaled to its own peak, so a node's shape still reads beside a root that towers over it
 *   - a categorical column as the Sankey's minimap does: root's categories, the node's own column, and the
 *     ribbons between them in the flows view's colours - grey stayed, orange recoded, slate removed
 *
 * Props:
 *  - a, b: the two node tables; the same table for one node against root
 *  - column: the column measured
 *  - keep: categories taken out of the Sankey's catch-all, as the comparison asked for them
 *  - base: the node measured from, or null for root
 */

// The miniature's own coordinates; the svg scales to whatever room the sub-node gives it, keeping its shape
const WIDTH = 200;
const HEIGHT = 120;
const PAD = 6;

// The Sankey's root boxes and the nodes' bars, in the miniature's units
const ROOT_BOX = 26;
const BAR = 4;

/* The Sankey is laid out at a full plot's height, then drawn squashed into the miniature: laid out at the
   miniature's own height, the gaps between a column's many categories would leave its ribbons no room at all.
   A column with more categories than usual is laid out taller still. */
const SANKEY_LAYOUT_HEIGHT = 400;
const SANKEY_ROOM_PER_CATEGORY = 16;

// Room left clear over the drawing for the column's name
const LABEL_ROOM = 14;

/* Root's shape and each node's curve over the column's whole range, as the ridgeline's overview strip draws them */
function RidgelineMiniature({overview}) {
    const {density, curves} = overview;
    const {grid, root} = density;

    const x = d3.scaleLinear()
        .domain([grid[0], grid[grid.length - 1]])
        .range([PAD, WIDTH - PAD]);
    const floor = HEIGHT - PAD;

    // Each curve to its own peak
    const yFor = (values) => {
        const peak = d3.max(values) || 1;
        return d3.scaleLinear().domain([0, peak]).range([floor, PAD + LABEL_ROOM]);
    };
    const rootY = yFor(root);
    const rootArea = d3.area().x((_, i) => x(grid[i])).y0(floor).y1((value) => rootY(value))(root);
    const lineOf = (values) => {
        const y = yFor(values);
        return d3.line().x((_, i) => x(grid[i])).y((value) => y(value))(values);
    };

    return (
        <g>
            <path d={rootArea} fill={DRIFT_BASE_COLOR} fillOpacity={0.35}/>
            {["a", "b"].map((role) => curves[role] && (
                <path key={role} d={lineOf(curves[role])} fill="none" stroke={ROLE_COLORS[role]} strokeWidth={1.8}/>
            ))}
            <line x1={PAD} x2={WIDTH - PAD} y1={floor} y2={floor} stroke="#cbd2d9"/>
        </g>
    );
}

/* Where each side's ribbons run, in the miniature's units: from root's edge (x0) out to the side's bar (x1). Root
   sits in the middle with a node either side, or - for one node - at the left with the node on the right. */
function sankeyFrames(single) {
    if (single) {
        const rootLeft = PAD;
        return {
            rootLeft,
            sides: {b: {x0: rootLeft + ROOT_BOX, x1: WIDTH - PAD - BAR, bar: WIDTH - PAD - BAR}},
        };
    }
    const rootLeft = (WIDTH - ROOT_BOX) / 2;
    return {
        rootLeft,
        sides: {
            a: {x0: rootLeft, x1: PAD + BAR, bar: PAD},
            b: {x0: rootLeft + ROOT_BOX, x1: WIDTH - PAD - BAR, bar: WIDTH - PAD - BAR},
        },
    };
}

/* The whole Sankey, small: the same layout the plot magnifies and the minimap draws narrow */
function SankeyMiniature({data}) {
    const categories = shownCategories(data, []);
    if (categories.length === 0) return null;

    const layoutHeight = Math.max(SANKEY_LAYOUT_HEIGHT, categories.length * SANKEY_ROOM_PER_CATEGORY);
    const world = layoutFlows(data, categories, layoutHeight);
    const {rootLeft, sides} = sankeyFrames(data.single);

    // Squashed from the layout's height into the room under the name
    const top = PAD + LABEL_ROOM;
    const squash = (HEIGHT - top - PAD) / layoutHeight;
    const transform = `translate(0, ${top}) scale(1, ${squash})`;

    return (
        <g transform={transform}>
            {world.sides.map((side) => {
                const frame = sides[side.id];
                if (!frame) return null;
                return side.placed.map((ribbon, index) => (
                    <path
                        key={`${side.id}-${index}`}
                        d={ribbonPath(ribbon, frame.x0, frame.x1)}
                        fill={FLOW_COLORS[flowKind(ribbon)]}
                        fillOpacity={ribbonOpacity(ribbon)}
                    />
                ));
            })}
            {[...world.roots.values()].map((box) => (
                <rect
                    key={`root-${box.label}`}
                    x={rootLeft}
                    y={box.y0}
                    width={ROOT_BOX}
                    height={Math.max(0.5, box.y1 - box.y0)}
                    fill="#e2e8f0"
                    stroke="#94a3b8"
                    strokeWidth={0.5}
                />
            ))}
            {world.sides.map((side) => {
                const frame = sides[side.id];
                if (!frame) return null;
                return [...side.targets.values()].map((bar) => (
                    <rect
                        key={`${side.id}-${bar.label}`}
                        x={frame.bar}
                        y={bar.y0}
                        width={BAR}
                        height={Math.max(0.5, bar.y1 - bar.y0)}
                        fill={nodeBarColor(bar)}
                    />
                ));
            })}
        </g>
    );
}

export default function DriftMiniature({a, b, column, keep = null, base = null}) {
    const {loading, current, plotData} = useComparisonData({a, b, kind: "drift", x: column, keep, base});

    // A numeric column has the ridgeline's overview; a categorical one, the Sankey's flows
    const overview = ridgelineOverview(plotData);

    let drawing = null;
    if (overview) {
        drawing = <RidgelineMiniature overview={overview} />;
    } else if (plotData) {
        drawing = <SankeyMiniature data={plotData} />;
    }

    let status = null;
    if (!column) {
        status = "No column";
    } else if (current?.error) {
        status = "Could not load";
    } else if (!plotData) {
        status = "Loading…";
    }

    return (
        <PlotPicture label={column}>
            {status ? (
                <span className="support-plot-picture-status">{status}</span>
            ) : (
                <svg
                    className={`support-plot-miniature ${loading ? "support-plot-miniature--loading" : ""}`}
                    viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                    preserveAspectRatio="xMidYMid meet"
                    aria-hidden="true"
                >
                    {drawing}
                </svg>
            )}
        </PlotPicture>
    );
}
