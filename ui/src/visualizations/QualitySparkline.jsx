import Sparkline from "./Sparkline.jsx";
import { ERROR_TYPES, errorColors, DRIFT_COLOR } from "../store/errorColors.js";
import { formatDrift } from "../utils/drift.js";
import "../styles/QualityPanel.css";

/**
 * One quality dimension along a branch - its name, where it starts and ends, and its sparkline - drawn the
 * same wherever it appears: on the Quality panel's cards, and in the sub-node a card is dragged into.
 *
 * dimension is an error type ("missing", "mismatch", "anomaly", "incomplete") or "drift". An error rate falling
 * is an improvement, so its steps are green and red; drift from root has no better direction - see
 * Sparkline's polarity - and reads in its own units.
 */

const asPercent = (rate) => `${((rate ?? 0) * 100).toFixed(2)}%`;

const isDrift = (dimension) => dimension === "drift";

/** The swatch, the dimension's name, and its first and last values - left off when a value is missing. grip
    marks a card that can be dragged. */
export function QualitySparklineHeader({ dimension, values, grip = false }) {
  const measured = values.length > 0 && values.every((value) => value != null);
  const format = isDrift(dimension) ? formatDrift : asPercent;

  return (
    <div className="quality-dimension-header">
      {grip && <span className="quality-grip" aria-hidden="true">⠿</span>}
      <span
        className={`quality-swatch ${isDrift(dimension) ? "quality-swatch--drift" : ""}`}
        data-error-type={isDrift(dimension) ? undefined : dimension}
      />
      <span className="quality-dimension-name">{isDrift(dimension) ? "Drift from root" : ERROR_TYPES[dimension]}</span>
      {measured && (
        <span className="quality-dimension-value">
          {format(values[0])} → {format(values[values.length - 1])}
        </span>
      )}
    </div>
  );
}

/** The dimension's sparkline, in the colour and number format the dimension reads in. */
export function QualitySparklineChart({ dimension, values, deltas, nodeIds, collapsedNodeIds }) {
  return isDrift(dimension) ? (
    <Sparkline
      values={values}
      deltas={deltas}
      nodeIds={nodeIds}
      color={DRIFT_COLOR}
      polarity="neutral"
      format="drift"
      collapsedNodeIds={collapsedNodeIds}
    />
  ) : (
    <Sparkline
      values={values}
      deltas={deltas}
      nodeIds={nodeIds}
      color={errorColors(dimension)}
      collapsedNodeIds={collapsedNodeIds}
    />
  );
}
