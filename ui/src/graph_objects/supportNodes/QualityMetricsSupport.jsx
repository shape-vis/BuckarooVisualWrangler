import {NodeMetrics} from "../NodeMetrics.jsx";

/**
 * The quality-metrics kind of supporting sub-node: the host's quality metrics, drawn as a folded run's
 * magnifier draws them, and the only place a node's own metrics are shown. Read from the host each
 * render, so it follows the host's numbers rather than a copy taken when it was added - and needs no
 * settings.
 */
export function QualityMetricsBody({host}) {
    return (
        <div className="support-node-metrics">
            <NodeMetrics metrics={host?.data?.metrics} />
        </div>
    );
}
