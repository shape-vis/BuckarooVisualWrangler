import {useMemo} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {collapsedNodeIds} from "../../utils/graphTopology.js";
import {QualitySparklineChart, QualitySparklineHeader} from "../../visualizations/QualitySparkline.jsx";
import "../../styles/SparklineSupport.css";

/**
 * The quality-sparkline kind of supporting sub-node: one quality dimension along a branch, kept beside the node
 * the branch ends on. It is not added from the modal - it is a Quality panel card's sparkline, dragged into this
 * node's group (see SupportDropZone).
 *
 * Its config is a snapshot of the card: {dimension, branch: {source, target, destination}, nodes, values,
 * deltas}. A node's numbers never change once it exists, so the snapshot stays true. Which of its nodes the
 * graph has folded away is read live, so the rings follow folding as the panel's do.
 */
export function SparklineBody({record}) {
    const {collapsedRuns} = usePgraph();
    const foldedNodeIds = useMemo(() => collapsedNodeIds(collapsedRuns), [collapsedRuns]);
    const {dimension, nodes = [], values = [], deltas = []} = record.config;

    return (
        <div className="sparkline-support">
            <QualitySparklineHeader dimension={dimension} values={values} />
            <div className="sparkline-support-chart">
                <QualitySparklineChart
                    dimension={dimension}
                    values={values}
                    deltas={deltas}
                    nodeIds={nodes}
                    collapsedNodeIds={foldedNodeIds}
                />
            </div>
        </div>
    );
}
