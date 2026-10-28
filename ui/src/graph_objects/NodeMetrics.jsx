import {ERROR_TYPES, ERROR_DIMENSIONS} from "../store/errorColors.js";
import "../styles/Nodes.css";

/**
 * A node's quality metrics: the rate of each error type, then its size. Shared by the magnifier's readout
 * and the quality-metrics sub-node, so the two always show the same numbers the same way. The frame around
 * it is the caller's.
 */
export function NodeMetrics( { metrics } ){
    if (!metrics) return <div className="node-metrics-empty">No metrics</div>;

    return (
        <>
            <div className="node-metrics-rows">
                {ERROR_DIMENSIONS.map((dimension) => (
                    <div key={dimension} className="node-metrics-row" title={ERROR_TYPES[dimension]}>
                        <span className="node-metrics-swatch" data-error-type={dimension} />
                        <span className="node-metrics-value">
                            {((metrics.totals?.[dimension] ?? 0) * 100).toFixed(2)}%
                        </span>
                    </div>
                ))}
            </div>
            <div className="node-metrics-footer">
                {metrics.row_count} rows · {metrics.column_count} cols
            </div>
        </>
    );
}
