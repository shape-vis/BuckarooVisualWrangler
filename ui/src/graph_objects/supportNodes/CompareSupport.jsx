import {useState} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {nodeName, referenceBase, viewsFor} from "../../utils/comparison.js";
import {driftZoomKey, settingsOf} from "../../utils/comparisonSpec.js";
import {useComparisonData} from "../../visualizations/useComparisonData.js";
import ComparisonPlot from "../../visualizations/ComparisonPlot.jsx";
import {PlotStatus} from "../../elements/ComparePanel.jsx";
import {FULL_COMPARE_SIZE, columnKindOf, compareSummary, specOfCompare, withCategoryHidden} from "./compareView.js";
import {CompareGlyph} from "./supportGlyphs.jsx";
import {hostColumns} from "./registry.js";
import "../../styles/ComparePanel.css";
import "../../styles/CompareSupport.css";

/**
 * The compare kind of supporting sub-node - see compareView.js. It zooms semantically: while it is small it
 * shows its badge's picture of the comparison, large, rather than a plot squeezed past reading; resized to
 * FULL_COMPARE_SIZE or more, it shows the whole plot the compare window was last left on, through the window's
 * own plot and data. The Open in its header shows it in the window, where changes carry back to it.
 */

/* The comparison's plot, whole. Zoom and hidden categories start from the comparison's and are the reader's to
   change here; the caller keys this on the comparison, so a change made in the compare window starts it afresh. */
function ComparePlotFull({spec}) {
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
            />
            {loading && <PlotStatus>Loading…</PlotStatus>}
            {!loading && current?.error && <PlotStatus error>{current.error}</PlotStatus>}
            {!x && <PlotStatus>Nothing to plot</PlotStatus>}
        </div>
    );
}

// Too small for the whole plot: its badge's picture of it, filling the room, with how to see more
function ComparePicture({record}) {
    return (
        <div className="compare-support-picture">
            <CompareGlyph record={record} />
            <span className="compare-support-hint">Resize to see the plot</span>
        </div>
    );
}

// Whether the sub-node is drawn large enough for the whole plot to read without squeezing
function fitsFullPlot(size) {
    if (!size) return false;
    return size.width >= FULL_COMPARE_SIZE.width && size.height >= FULL_COMPARE_SIZE.height;
}

export function CompareBody({record, host, size}) {
    const spec = specOfCompare(record, hostColumns(host));
    const summary = compareSummary(spec);

    return (
        <div className="compare-support-body">
            <div className="compare-support-summary">
                <span className="compare-support-summary-text" title={summary}>{summary}</span>
            </div>
            {fitsFullPlot(size) ? (
                <ComparePlotFull key={settingsOf(spec)} spec={spec} />
            ) : (
                <ComparePicture record={record} />
            )}
        </div>
    );
}
