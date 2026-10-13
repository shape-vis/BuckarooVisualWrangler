import {useState} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {PLOT_KINDS, nodeName, referenceBase, viewsFor} from "../../utils/comparison.js";
import {driftZoomKey, settingsOf} from "../../utils/comparisonSpec.js";
import {useComparisonData} from "../../visualizations/useComparisonData.js";
import ComparisonPlot from "../../visualizations/ComparisonPlot.jsx";
import {PlotStatus} from "../../elements/ComparePanel.jsx";
import {columnKindOf, specOfCompare, withCategoryHidden} from "./compareView.js";
import {hostColumns} from "./registry.js";
import "../../styles/ComparePanel.css";
import "../../styles/CompareSupport.css";

/**
 * The compare kind of supporting sub-node - see compareView.js. It previews its comparison through the compare
 * window's own plot and data, and the Open in its header shows it there, where changes carry back to it.
 */

/* The comparison's plot, small. Zoom and hidden categories start from the comparison's and are the reader's to
   change here; the caller keys this on the comparison, so a change made in the compare window starts it afresh. */
function ComparePreview({spec}) {
    const {serverNodesById} = usePgraph();
    const {kind, a, b} = spec;
    const x = spec.x;
    const y = kind === "heatmap" ? spec.y : null;
    const base = referenceBase(spec, serverNodesById);
    const distortionA = serverNodesById?.[a]?.data?.distortion;
    const distortionB = serverNodesById?.[b]?.data?.distortion;
    const columnKind = columnKindOf(x, [distortionB, distortionA]);
    const {activeView} = viewsFor({kind, view: spec.view, columnKind, single: a === b});
    const {loading, current, plotData} = useComparisonData({a, b, kind, x, y, keep: spec.kept, base});

    const [zoom, setZoom] = useState(() => {
        let key = null;
        if (spec.zoom && kind === "drift") {
            key = driftZoomKey({x, a, b, base});
        }
        return {key, range: spec.zoom};
    });
    const [hidden, setHidden] = useState(spec.hidden);

    const hideCategory = (category) => setHidden((was) => withCategoryHidden(was, category));

    return (
        // nowheel and nopan keep the graph from zooming or panning under a plot being read
        <div className={`compare-support-plot compare-plot nowheel nopan ${loading ? "compare-plot--loading" : ""}`}>
            <ComparisonPlot
                data={plotData}
                view={activeView}
                measure={spec.measure}
                labelA={nodeName(a)}
                labelB={nodeName(b)}
                hidden={hidden}
                onHide={hideCategory}
                zoom={zoom}
                onZoom={setZoom}
                compact
            />
            {!loading && current?.error && <PlotStatus error>{current.error}</PlotStatus>}
            {!x && <PlotStatus>Nothing to plot</PlotStatus>}
        </div>
    );
}

/** One line naming what the comparison shows: its two nodes, its plot kind and its column. */
function compareSummary(spec) {
    const plotKind = PLOT_KINDS.find((option) => option.id === spec.kind);
    const kindLabel = plotKind?.label ?? spec.kind;

    let summary = `${nodeName(spec.a)} → ${nodeName(spec.b)} · ${kindLabel}`;
    if (spec.x) {
        summary += ` · ${spec.x}`;
    }
    return summary;
}

export function CompareBody({record, host}) {
    const spec = specOfCompare(record, hostColumns(host));
    const summary = compareSummary(spec);

    return (
        <div className="compare-support-body">
            <div className="compare-support-summary">
                <span className="compare-support-summary-text" title={summary}>{summary}</span>
            </div>
            <ComparePreview key={settingsOf(spec)} spec={spec} />
        </div>
    );
}
