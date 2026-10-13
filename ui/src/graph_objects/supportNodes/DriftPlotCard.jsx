import {useState} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {nodeName, viewsFor, VIEW_LABELS} from "../../utils/comparison.js";
import {useComparisonData} from "../../visualizations/useComparisonData.js";
import ComparisonPlot from "../../visualizations/ComparisonPlot.jsx";
import {PlotStatus} from "../../elements/ComparePanel.jsx";
import {ColumnPicker, SupportPlotCard} from "./SupportPlotCard.jsx";
import {columnKindOf, withCategoryHidden} from "./compareView.js";
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
    const requestedColumn = enabled ? column : "";
    const {loading, current, plotData} = useComparisonData({
        a: table, b: table, kind: "drift", x: requestedColumn, keep: null, base: null,
    });
    // The node says which kind of column this is; a column it has no drift for is told by the result instead
    const knownKind = columnKind ?? plotData?.b?.kind;
    const {activeView: view} = viewsFor({kind: "drift", view: null, columnKind: knownKind, single: true});
    const [zoom, setZoom] = useState({key: null, range: null});
    const [hidden, setHidden] = useState([]);

    const hideCategory = (category) => setHidden((was) => withCategoryHidden(was, category));

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
                onHide={hideCategory}
                zoom={zoom}
                onZoom={setZoom}
            />
            {loading && <PlotStatus>Loading…</PlotStatus>}
            {!loading && current?.error && <PlotStatus error>{current.error}</PlotStatus>}
        </div>
    );
}

export default function DriftPlotCard({table, column, columnChoices, onColumn, actions = null, enabled = true}) {
    const {serverNodesById} = usePgraph();
    // Ridgeline or Sankey follows the column, numeric or categorical, as root decided it
    const distortion = serverNodesById?.[table]?.data?.distortion;
    const columnKind = columnKindOf(column, [distortion]);

    // Until the node says which kind the column is, the title names no view
    let title = `Drift · ${column}`;
    if (columnKind) {
        const view = viewsFor({kind: "drift", view: null, columnKind, single: true}).activeView;
        if (view) {
            title = `Drift · ${column} (${VIEW_LABELS[view]})`;
        }
    }

    return (
        <SupportPlotCard
            title={title}
            actions={actions}
            pickers={<ColumnPicker label="Column" value={column} choices={columnChoices} onChange={onColumn} />}
        >
            <DriftPlot key={column} table={table} column={column} columnKind={columnKind} enabled={enabled} />
        </SupportPlotCard>
    );
}
