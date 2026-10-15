import { useMemo } from "react";
import HeatMap from "./HeatMap.jsx";
import HistogramBarChart from "./HistogramBarChart.jsx";
import ScatterPlot from "./ScatterPlot.jsx";

/**
 * One of the attribute matrix's plots, and the same plot drawn on its own, large, with its axis labels - as the
 * matrix shows it zoomed in, and as an error-plot sub-node shows it while it is wrangled on. Either way it is the
 * matrix's own plot: brushing it selects rows for Repair, and the selection lights up every other plot.
 */

// ── Icon: minimize (compress arrows) ─────────────────────────────────────────
function MinimizeIcon({ x, y, onClick }) {
    const s = 16;
    const m = 3;
    const arm = 5;
    return (
        <g
            className="plot-minimize-icon"
            onClick={e => { e.stopPropagation(); onClick(); }}
        >
            <rect x={x - 1} y={y - 1} width={s + 2} height={s + 2} fill="white" fillOpacity={0.85} />
            {/* top-left corner arrows pointing inward */}
            <polyline
                points={`${x + m},${y + m + arm} ${x + m},${y + m} ${x + m + arm},${y + m}`}
                fill="none" stroke="#444" strokeWidth={1.5} strokeLinejoin="round"
            />
            {/* bottom-right corner arrows pointing inward */}
            <polyline
                points={`${x + s - m},${y + s - m - arm} ${x + s - m},${y + s - m} ${x + s - m - arm},${y + s - m}`}
                fill="none" stroke="#444" strokeWidth={1.5} strokeLinejoin="round"
            />
        </g>
    );
}

// ── One cell's plot ───────────────────────────────────────────────────────────
/**
 * The plot for cell (i, j) of the matrix: a histogram on the diagonal, a scatterplot above it and a heatmap
 * below it. Used for the matrix's own cells and for the one zoomed in on.
 *
 * The histogram takes its position and size as objects and redraws whenever they change, so they are
 * memoised here rather than built fresh on every render of the panel.
 */
export function CellPlot({ i, j, cellID, xPos, yPos, size, xCol, yCol, errorColors }) {
    const histogramPos = useMemo(() => ({ x: xPos, y: yPos }), [xPos, yPos]);
    const histogramSize = useMemo(() => ({ w: size, h: size }), [size]);

    if (i === j) {
        return (
            <HistogramBarChart
                cellID={cellID}
                pos={histogramPos}
                size={histogramSize}
                attrX={xCol}
                errorColors={errorColors}
            />
        );
    }

    if (i < j) {
        return (
            <ScatterPlot
                cellID={cellID}
                xPos={xPos}
                yPos={yPos}
                size={size}
                attrX={xCol}
                attrY={yCol}
                errorColors={errorColors}
            />
        );
    }

    return (
        <HeatMap
            cellID={cellID}
            xPos={xPos}
            yPos={yPos}
            size={size}
            attrX={xCol}
            attrY={yCol}
            errorColors={errorColors}
        />
    );
}

/* Room left for the axis labels. The left needs to fit D3's left-axis tick labels (up to ~80px for 10-char
   strings); the bottom, ~50px for its bottom-axis tick labels, drawn below the plot area. */
const FOCUSED_X = 90;
const FOCUSED_Y = 70;
const RIGHT_ROOM = 40;
const BOTTOM_ROOM = 100;
const MIN_FOCUSED = 80;

/**
 * Cell (i, j) of the matrix drawn on its own in a w by h svg, with its column names along its axes. onMinimize,
 * when given, puts the minimize icon on its top-right corner.
 */
export default function FocusedPlot({ i, j, xCol, yCol, w, h, errorColors, onMinimize }) {
    const cellID = `cell-${xCol}-${yCol}`;

    const fitted = Math.min(w - FOCUSED_X - RIGHT_ROOM, h - FOCUSED_Y - BOTTOM_ROOM);
    const size = Math.max(MIN_FOCUSED, fitted);

    return (
        <g>
            {/* X axis label */}
            <text
                x={FOCUSED_X + size / 2}
                y={FOCUSED_Y - 28}
                textAnchor="middle"
                fontSize={14}
                fontWeight="500"
            >
                {xCol}
            </text>
            {/* Y axis label (only for 2-D plots) */}
            {i !== j && (
                <text
                    x={FOCUSED_X - 65}
                    y={FOCUSED_Y + size / 2}
                    textAnchor="middle"
                    fontSize={13}
                    fontWeight="500"
                    transform={`rotate(-90, ${FOCUSED_X - 65}, ${FOCUSED_Y + size / 2})`}
                >
                    {yCol}
                </text>
            )}
            <CellPlot
                i={i}
                j={j}
                cellID={cellID}
                xPos={FOCUSED_X}
                yPos={FOCUSED_Y}
                size={size}
                xCol={xCol}
                yCol={yCol}
                errorColors={errorColors}
            />
            {onMinimize && (
                <MinimizeIcon
                    x={FOCUSED_X + size - 18}
                    y={FOCUSED_Y + 2}
                    onClick={onMinimize}
                />
            )}
        </g>
    );
}
