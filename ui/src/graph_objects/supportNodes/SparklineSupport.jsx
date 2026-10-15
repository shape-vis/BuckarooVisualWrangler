import {useEffect, useMemo, useState} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {useHostWindow} from "../../store/HostWindowContext.jsx";
import {ERROR_DIMENSIONS} from "../../store/errorColors.js";
import {collapsedNodeIds} from "../../utils/graphTopology.js";
import {nodeName} from "../../utils/comparison.js";
import {QualitySparklineChart, QualitySparklineHeader} from "../../visualizations/QualitySparkline.jsx";
import {SparklineGlyph} from "./supportGlyphs.jsx";
import "../../styles/SparklineSupport.css";

/**
 * The quality-sparkline kind of supporting sub-node: one quality dimension - an error type, or drift from root -
 * along a branch that ends at its host.
 *
 * It is added from the support-nodes window as a blank placeholder, one per dimension, and then needs a source:
 * the graph lights up the edges above its host, and the one clicked is where the branch starts - see
 * PGraphContext's sparkline picking. Until then it says so, and Pick source starts the picking again; once it
 * has one, Change source does.
 *
 * Its config is {dimension, branch: {source, target, destination} | null, nodes, values, deltas}: a snapshot of
 * the branch's trajectory. A node's numbers never change once it exists, so the snapshot stays true. Which of
 * its nodes the graph has folded away is read live, so the rings follow folding.
 */

const SPARKLINE_DIMENSIONS = [...ERROR_DIMENSIONS, "drift"];

// A new sparkline, before it has a branch
function blankSparklineConfig(dimension) {
    return {dimension, branch: null, nodes: [], values: [], deltas: []};
}

/** What the sparkline's footer button says: picking, or the first pick, or a new one. */
function pickLabel(picking, hasSource) {
    if (picking) return "Picking…";
    if (hasSource) return "Change source";
    return "Pick source";
}

/** What the sparkline says where its chart goes, when it has no chart to draw. */
function emptyMessage(picking, hasSource) {
    if (picking) return "Click a highlighted edge above this node in the graph";
    if (hasSource) return "Not measured on every node of this branch";
    return "No source yet";
}

export function SparklineBody({record}) {
    const {collapsedRuns, sparklinePick, startSparklinePick} = usePgraph();
    const foldedNodeIds = useMemo(() => collapsedNodeIds(collapsedRuns), [collapsedRuns]);
    const {dimension, nodes = [], values = [], deltas = []} = record.config;

    const hasSource = nodes.length > 1;
    const measured = values.length > 0 && values.every((value) => value != null);
    const picking = sparklinePick?.recordId === record.id;

    let shownValues = [];
    if (hasSource) {
        shownValues = values;
    }

    const pick = (event) => {
        event.stopPropagation();
        startSparklinePick(record.id, record.hostId);
    };

    return (
        <div className="sparkline-support">
            <QualitySparklineHeader dimension={dimension} values={shownValues} />
            {hasSource && measured ? (
                <div className="sparkline-support-chart">
                    <QualitySparklineChart
                        dimension={dimension}
                        values={values}
                        deltas={deltas}
                        nodeIds={nodes}
                        collapsedNodeIds={foldedNodeIds}
                    />
                </div>
            ) : (
                <div className="sparkline-support-empty">{emptyMessage(picking, hasSource)}</div>
            )}
            <div className="sparkline-support-footer">
                {hasSource && (
                    <span className="sparkline-support-branch" title={nodes.join(" → ")}>
                        {nodeName(nodes[0])} → {nodeName(nodes[nodes.length - 1])}
                    </span>
                )}
                <button
                    type="button"
                    className="support-node-inline-action"
                    onClick={pick}
                    onDoubleClick={(event) => event.stopPropagation()}
                    disabled={picking}
                    title="Pick the edge in the graph where this sparkline's branch starts"
                >
                    {pickLabel(picking, hasSource)}
                </button>
            </div>
        </div>
    );
}

/* One blank sparkline card in the window: its dimension, a faint stand-in for its line, and Add. Adding starts
   picking its source straight away, which opens the graph. */
function SparklineCard({dimension, onAdd}) {
    const hostWindow = useHostWindow();
    const [added, setAdded] = useState(false);

    // A short confirmation, since the sub-node appears in the graph rather than here
    useEffect(() => {
        if (!added) return undefined;
        const timer = hostWindow.setTimeout(() => setAdded(false), 2000);
        return () => hostWindow.clearTimeout(timer);
    }, [added, hostWindow]);

    const add = () => {
        onAdd(dimension);
        setAdded(true);
    };

    return (
        <div className="sparkline-card">
            <QualitySparklineHeader dimension={dimension} values={[]} />
            <div className="sparkline-card-placeholder">
                <SparklineGlyph record={{config: {dimension}}} />
            </div>
            <div className="support-plot-actions">
                <button type="button" className="support-plot-action support-plot-action--primary" onClick={add}>
                    {added ? "Added ✓ - now pick its edge" : "Add To Node"}
                </button>
            </div>
        </div>
    );
}

/**
 * The window's picker for this kind: a blank card for each dimension. onAdd(config) adds one and hands back its
 * id, so its source can be picked straight away.
 */
export function SparklineGallery({hostId, onAdd}) {
    const {startSparklinePick} = usePgraph();

    const addOne = (dimension) => {
        const id = onAdd(blankSparklineConfig(dimension));
        startSparklinePick(id, hostId);
    };

    return (
        <div className="support-plot-gallery sparkline-gallery">
            {SPARKLINE_DIMENSIONS.map((dimension) => (
                <SparklineCard key={dimension} dimension={dimension} onAdd={addOne} />
            ))}
        </div>
    );
}
