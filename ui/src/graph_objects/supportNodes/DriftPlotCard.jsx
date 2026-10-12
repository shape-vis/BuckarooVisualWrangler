import {useState} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {nodeName, viewsFor, VIEW_LABELS} from "../../utils/comparison.js";
import {useComparisonData} from "../../visualizations/useComparisonData.js";
import ComparisonPlot from "../../visualizations/ComparisonPlot.jsx";
import {ColumnPicker, SupportPlotCard} from "./SupportPlotCard.jsx";
import "../../styles/ComparePanel.css";

/**
 * One node's drift from root on one column, drawn as the compare window draws drift - a ridgeline for a numeric
 * column, a Sankey for a categorical one - with only the one node: the ridgeline's single row is the node filled
 * with root dashed over it, the gap between them the mass that moved; the Sankey runs from root to the node.
 * Zoom strip, minimap, hover notes and legend as in the window. Shared by the drift-plot gallery and the
 * sub-node, in the frame every sub-node plot shares.
 *
 * Props:
 *  - table: the node table
 *  - column: the column measured
 *  - columnChoices: the columns that can be picked - the node's own
 *  - onColumn: called with the next column
 *  - actions: anything more for the card's footer, beside Change Columns
 *  - enabled: false holds the request back, for a card not yet scrolled into view
 */

/* The plot itself. Zoom and hidden categories are the reader's, kept here - the caller keys this on the column,
   so another column starts unzoomed with every category shown. */
function DriftPlot({table, column, columnKind, enabled}) {
    // A node measured against itself is a single-node result: one side, against root
    const {loading, current, plotData} = useComparisonData({
        a: table, b: table, kind: "drift", x: enabled ? column : "", keep: null, base: null,
    });
    // The node says which kind of column this is; a column it has no drift for is told by the result instead
    const {activeView: view} = viewsFor({kind: "drift", view: null, columnKind: columnKind ?? plotData?.b?.kind, single: true});
    const [zoom, setZoom] = useState({key: null, range: null});
    const [hidden, setHidden] = useState([]);

    return (
        // nowheel and nopan keep the graph from zooming or panning under a plot being read
        <div className={`support-drift-plot compare-plot nowheel nopan ${loading ? "compare-plot--loading" : ""}`}>
            <ComparisonPlot
                data={plotData}
                view={view}
                measure="items"
                labelA={nodeName(table)}
                labelB={nodeName(table)}
                hidden={hidden}
                onHide={(category) => setHidden((was) => (was.includes(category) ? was : [...was, category]))}
                zoom={zoom}
                onZoom={setZoom}
            />
            {loading && <div className="compare-plot-status"><span className="compare-plot-pill">Loading…</span></div>}
            {!loading && current?.error && (
                <div className="compare-plot-status">
                    <span className="compare-plot-pill compare-plot-pill--error">{current.error}</span>
                </div>
            )}
        </div>
    );
}

export default function DriftPlotCard({table, column, columnChoices, onColumn, actions = null, enabled = true}) {
    const {serverNodesById} = usePgraph();
    // Ridgeline or Sankey follows the column, numeric or categorical, as root decided it
    const columnKind = serverNodesById?.[table]?.data?.distortion?.columns?.[column]?.kind;
    const view = columnKind && viewsFor({kind: "drift", view: null, columnKind, single: true}).activeView;

    return (
        <SupportPlotCard
            title={view ? `Drift · ${column} (${VIEW_LABELS[view]})` : `Drift · ${column}`}
            actions={actions}
            pickers={<ColumnPicker label="Column" value={column} choices={columnChoices} onChange={onColumn} />}
        >
            <DriftPlot key={column} table={table} column={column} columnKind={columnKind} enabled={enabled} />
        </SupportPlotCard>
    );
}
