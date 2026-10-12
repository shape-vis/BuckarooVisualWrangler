import {useState} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {PLOT_KINDS, nodeName, referenceBase, viewsFor} from "../../utils/comparison.js";
import {driftZoomKey, settingsOf} from "../../utils/comparisonSpec.js";
import {useComparisonData} from "../../visualizations/useComparisonData.js";
import ComparisonPlot from "../../visualizations/ComparisonPlot.jsx";
import {specOfCompare} from "./compareView.js";
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
    const columnKind = (serverNodesById?.[b]?.data?.distortion?.columns?.[x]
        ?? serverNodesById?.[a]?.data?.distortion?.columns?.[x])?.kind;
    const {activeView} = viewsFor({kind, view: spec.view, columnKind, single: a === b});
    const {loading, current, plotData} = useComparisonData({a, b, kind, x, y, keep: spec.kept, base});

    const [zoom, setZoom] = useState(() => ({
        key: spec.zoom && kind === "drift" ? driftZoomKey({x, a, b, base}) : null,
        range: spec.zoom,
    }));
    const [hidden, setHidden] = useState(spec.hidden);

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
                onHide={(category) => setHidden((was) => (was.includes(category) ? was : [...was, category]))}
                zoom={zoom}
                onZoom={setZoom}
                compact
            />
            {!loading && current?.error && (
                <div className="compare-plot-status">
                    <span className="compare-plot-pill compare-plot-pill--error">{current.error}</span>
                </div>
            )}
            {!x && <div className="compare-plot-status"><span className="compare-plot-pill">Nothing to plot</span></div>}
        </div>
    );
}

export function CompareBody({record, host}) {
    const spec = specOfCompare(record, Object.keys(host?.data?.metrics?.columns ?? {}));
    const kindLabel = PLOT_KINDS.find((option) => option.id === spec.kind)?.label ?? spec.kind;
    const summary = `${nodeName(spec.a)} → ${nodeName(spec.b)} · ${kindLabel}${spec.x ? ` · ${spec.x}` : ""}`;

    return (
        <div className="compare-support-body">
            <div className="compare-support-summary">
                <span className="compare-support-summary-text" title={summary}>{summary}</span>
            </div>
            <ComparePreview key={settingsOf(spec)} spec={spec} />
        </div>
    );
}
