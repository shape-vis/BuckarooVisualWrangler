import {useEffect, useRef} from "react";
import * as d3 from "d3";
import {LEFT_M, SVG_H, SVG_W, TOP_M, draw1D, draw2D, usePreviewPlotData} from "../../visualizations/previewPlots.js";
import {errorColors} from "../../store/errorColors.js";
import {ColumnPicker, SupportPlotCard} from "./SupportPlotCard.jsx";

/**
 * One error plot of one node's table: a histogram of a column, its bars stacked by error type, or a heatmap
 * of two, drawn exactly as the repair preview draws them - see visualizations/previewPlots.js. Shared by the
 * gallery the error-plot sub-node is picked from and by the sub-node itself, in the frame every sub-node plot
 * shares (SupportPlotCard), whose Change Columns reports each pick through onColumns.
 *
 * Props:
 *  - table: the node table to plot
 *  - plot: "histogram" or "heatmap"
 *  - columns: [x] for a histogram, [x, y] for a heatmap
 *  - columnChoices: the columns that can be picked - the node's own
 *  - onColumns: called with the next columns
 *  - actions: anything more for the card's footer, beside Change Columns
 *  - enabled: false holds the request back, for a card not yet scrolled into view
 */

const PLOT_LABELS = {histogram: "Histogram", heatmap: "Heatmap"};

const describeErrorPlot = (plot, columns) => `${PLOT_LABELS[plot] ?? plot} · ${columns.join(" × ")}`;

export default function ErrorPlotCard({table, plot, columns, columnChoices, onColumns, actions = null, enabled = true}) {
    const svgRef = useRef(null);
    const {data, loading, error} = usePreviewPlotData({table, kind: plot, columns, enabled});

    useEffect(() => {
        if (!data || !svgRef.current) return;
        const svg = d3.select(svgRef.current);
        svg.selectAll("*").remove();
        const canvas = svg.append("g").attr("transform", `translate(${LEFT_M}, ${TOP_M})`);
        if (plot === "histogram") draw1D(canvas, data, errorColors);
        else draw2D(canvas, data, errorColors);
    }, [data, plot]);

    const pick = (index) => (column) => onColumns(columns.map((was, i) => (i === index ? column : was)));

    return (
        <SupportPlotCard
            title={describeErrorPlot(plot, columns)}
            actions={actions}
            pickers={(
                <>
                    <ColumnPicker
                        label={plot === "heatmap" ? "X" : "Column"}
                        value={columns[0]}
                        choices={columnChoices}
                        onChange={pick(0)}
                    />
                    {plot === "heatmap" && (
                        <ColumnPicker label="Y" value={columns[1]} choices={columnChoices} onChange={pick(1)} />
                    )}
                </>
            )}
        >
            {loading && <div className="support-plot-status">Loading…</div>}
            {error && <div className="support-plot-status support-plot-status--error">{error}</div>}
            {!loading && !error && (
                <svg
                    ref={svgRef}
                    viewBox={`0 0 ${SVG_W} ${SVG_H}`}
                    preserveAspectRatio="xMidYMid meet"
                    className="support-plot-svg"
                />
            )}
        </SupportPlotCard>
    );
}
