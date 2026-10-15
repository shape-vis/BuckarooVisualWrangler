import { useEffect, useRef, useState } from "react";
import FocusedPlot, { CellPlot } from "../visualizations/FocusedPlot.jsx";
import "../styles/SelectionPanel.css";
import { updateBackendAttributes } from "../utils/serverCalls.jsx";
import { errorColors } from "../store/errorColors.js";
import { useTableName } from "../store/TableNameContext.jsx";
import { heatMapCache, histogramCache, scatterPlotCache } from "../store/visualizationCaches.jsx";

// ── Icon: magnifier (zoom-in) ─────────────────────────────────────────────────
function MagnifierIcon({ x, y, onClick }) {
    const r = 4.5;
    const cx = x + r + 1;
    const cy = y + r + 1;
    return (
        <g
            className="plot-cell-icon"
            onClick={e => { e.stopPropagation(); onClick(); }}
        >
            <rect x={x - 1} y={y - 1} width={16} height={16} fill="white" fillOpacity={0.85} />
            <circle cx={cx} cy={cy} r={r} fill="none" stroke="#444" strokeWidth={1.5} />
            <line
                x1={cx + r * 0.65} y1={cy + r * 0.65}
                x2={cx + r * 1.5}  y2={cy + r * 1.5}
                stroke="#444" strokeWidth={1.5} strokeLinecap="round"
            />
        </g>
    );
}

// ── Main panel ────────────────────────────────────────────────────────────────
function SelectionPanel({ selectedAttributes, w, h, errorColors, plotFocus, onPlotFocused }) {
    const { tableName: table_name } = useTableName();
    const [plotSize, setPlotSize] = useState(180);
    const [focusedCell, setFocusedCell] = useState(null); // { i, j } or null

    const view = {
        xPadding: 85, yPadding: 70,
        leftMargin: 30, rightMargin: 40,
        topMargin: 50, bottomMargin: 50,
    };

    const columns = selectedAttributes || [];
    const [prevAttributes, setPrevAttributes] = useState(columns);

    function clearFrontendPlotCaches(removedAttributes, activeAttributes) {
        // clear 1D hist cache
        removedAttributes.forEach((attr) => {
            histogramCache.delete(`${table_name}|${attr}`);
        });

        // clear active-nonactive cache for nonactive attributes, heatmap & scatterplot.
        removedAttributes.forEach((removedAttr) => {
            activeAttributes.forEach((activeAttr) => {
                heatMapCache.delete(`${table_name}|${removedAttr}|${activeAttr}`);
                heatMapCache.delete(`${table_name}|${activeAttr}|${removedAttr}`);
                scatterPlotCache.delete(`${table_name}|${removedAttr}|${activeAttr}`);
                scatterPlotCache.delete(`${table_name}|${activeAttr}|${removedAttr}`);
            });
        });

        // clear nonactive-nonactive cache if there are multiple attributes, heatmap & scatterplot.
        if (removedAttributes.length > 1) {
            for (let i = 0; i < removedAttributes.length; i++) {
                for (let j = i + 1; j < removedAttributes.length; j++) {
                    const first = removedAttributes[i];
                    const second = removedAttributes[j];
                    heatMapCache.delete(`${table_name}|${first}|${second}`);
                    heatMapCache.delete(`${table_name}|${second}|${first}`);
                    scatterPlotCache.delete(`${table_name}|${first}|${second}`);
                    scatterPlotCache.delete(`${table_name}|${second}|${first}`);
                }
            }
        }
    }

    // Updates active active attributes to backend
    useEffect(() => {
        // Determine removed attributes
        const removed = prevAttributes.filter(attr => !columns.includes(attr));

        if (removed.length === 0) {
            setPrevAttributes(columns);
            return;
        }

        const removedKeys = [];

        // Add 1D hist keys for removed attributes
        removed.forEach(attr => {
            removedKeys.push({ type: "1d", column: attr });
        });

        // Add 2D hist keys between removed + active attributes
        removed.forEach(removedAttr => {
            columns.forEach(activeAttr => {
                removedKeys.push({ type: "2d", columns: [removedAttr, activeAttr] }); // upper
                removedKeys.push({ type: "2d", columns: [activeAttr, removedAttr] }); // lower
            });
        });

        // Add 2D keys between removed attributes themselves if more than one removed
        if (removed.length > 1) {
            for (let i = 0; i < removed.length; i++) {
                for (let j = i + 1; j < removed.length; j++) {
                    removedKeys.push({ type: "2d", columns: [removed[i], removed[j]] }); // upper
                    removedKeys.push({ type: "2d", columns: [removed[j], removed[i]] }); // lower
                }
            }
        }

        // Keep frontend cache consistent with backend.
        // Remove cached nonactive viewport keys when deselected.
        clearFrontendPlotCaches(removed, columns);

        // send nonactive views to backend.
        updateBackendAttributes({ removed_keys: removedKeys });

        // Update prevAttributes for next run
        setPrevAttributes(columns);
    }, [selectedAttributes]);

    // Clear focus if columns change (e.g. user deselects an attribute)
    useEffect(() => {
        setFocusedCell(null);
    }, [table_name, selectedAttributes]);

    /* Zoom to a plot asked for from elsewhere - a sub-node's "Open ↗" button - once its columns are in
       the matrix. After the reset above, so a request that arrives with new columns is not cleared by them.
       Applying it hands it back (onPlotFocused) so it is gone rather than remembered as done: applying it twice
       is harmless, which matters because StrictMode runs a new matrix's effects twice - reset, zoom, reset,
       zoom - and a request skipped the second time would be left reset. A heatmap sits below the diagonal,
       with x as its column; if the two are selected the other way round, it is the same pair drawn transposed. */
    useEffect(() => {
        if (!plotFocus) return;
        const [x, y] = plotFocus.columns;
        const xIndex = columns.indexOf(x);
        const yIndex = y === undefined ? xIndex : columns.indexOf(y);
        if (xIndex < 0 || yIndex < 0) return;
        if (y === undefined) {
            setFocusedCell({ i: xIndex, j: xIndex });
        } else {
            setFocusedCell({ i: Math.max(xIndex, yIndex), j: Math.min(xIndex, yIndex) });
        }
        onPlotFocused?.(plotFocus.key);
        // columns is selectedAttributes, under the name the rest of the panel uses
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [plotFocus, table_name, selectedAttributes]);

    useEffect(() => {
        const n = columns.length;
        if (n > 0) {
            let newPlotSize = Math.min(
                (w - view.leftMargin - view.rightMargin) / n - view.xPadding,
                (h - view.topMargin - view.bottomMargin) / n - view.yPadding
            );
            newPlotSize = Math.max(40, newPlotSize);
            setPlotSize(newPlotSize);
        }
    }, [table_name, selectedAttributes, w, h]);

    // ── Focused (expanded) view ───────────────────────────────────────────────
    if (focusedCell !== null) {
        const { i, j } = focusedCell;

        return (
            <g id="matrix-plot-area">
                <FocusedPlot
                    i={i}
                    j={j}
                    xCol={columns[j]}
                    yCol={columns[i]}
                    w={w}
                    h={h}
                    errorColors={errorColors}
                    onMinimize={() => setFocusedCell(null)}
                />
            </g>
        );
    }

    // ── Normal matrix view ────────────────────────────────────────────────────
    // TODO: Only update views in which attributes actually change.
    return (
        <g id="matrix-plot-area">
            {/* Column (x) labels */}
            <g>
                {columns.map((col, i) => (
                    <text
                        key={`xlabel-${i}`}
                        x={view.leftMargin + (i + 1) * view.xPadding + i * plotSize + plotSize / 2}
                        y={view.topMargin - 10}
                        textAnchor="middle"
                    >
                        {col}
                    </text>
                ))}
                {columns.map((col, i) => (
                    <text
                        key={`ylabel-${i}`}
                        x={view.leftMargin - 10}
                        y={view.topMargin + i * (plotSize + view.yPadding) + plotSize / 2}
                        transform={`rotate(-90, ${view.leftMargin - 10}, ${view.topMargin + i * (plotSize + view.yPadding) + plotSize / 2})`}
                        textAnchor="middle"
                    >
                        {col}
                    </text>
                ))}
            </g>

            {/* Plot cells */}
            {columns.map((xCol, j) =>
                columns.map((yCol, i) => {
                    // Named by its columns rather than its position, so a cell keeps its chart
                    // when other attributes are added or removed around it
                    const cellID = `cell-${xCol}-${yCol}`;

                    const xPos = view.leftMargin + (j + 1) * view.xPadding + j * plotSize;
                    const yPos = view.topMargin + i * (plotSize + view.yPadding);
                    const iconX = xPos + plotSize - 16;
                    const iconY = yPos;

                    return (
                        <g key={cellID} className="plot-cell-wrapper">
                            <CellPlot
                                i={i}
                                j={j}
                                cellID={cellID}
                                xPos={xPos}
                                yPos={yPos}
                                size={plotSize}
                                xCol={xCol}
                                yCol={yCol}
                                errorColors={errorColors}
                            />
                            <MagnifierIcon
                                x={iconX}
                                y={iconY}
                                onClick={() => setFocusedCell({ i, j })}
                            />
                        </g>
                    );
                })
            )}
        </g>
    );
}



/**
 * The plot matrix of the selected attributes, drawn in an SVG that fills its parent and is re-measured
 * whenever that parent resizes.
 */
export default function MatrixView({ selectedAttributes, plotFocus, onPlotFocused }) {
    const svgRef = useRef(null);
    const { tableName: table_name } = useTableName();

    const [w, setW] = useState(800);
    const [h, setH] = useState(600);

    useEffect(() => {
        const svg = svgRef.current;

        const resizeObserver = new ResizeObserver(() => {
            const bbox = svg.getBoundingClientRect();
            setW(bbox.width || 800);
            setH(bbox.height || 600);
        });

        if (svgRef.current) {
            resizeObserver.observe(svgRef.current);
        }

        return () => resizeObserver.disconnect();
    }, [table_name, selectedAttributes]);

    return (
        <svg ref={svgRef} id="main-svg" width={"100%"} height={"100%"} overflow="visible">
            <SelectionPanel
                selectedAttributes={selectedAttributes}
                w={w}
                h={h}
                errorColors={errorColors}
                plotFocus={plotFocus}
                onPlotFocused={onPlotFocused}
            />
        </svg>
    );
}
