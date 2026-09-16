import { NULL_FLAG_TITLE } from "../utils/drift.js";
import "../styles/Drift.css";

/**
 * The null test's flag: this column's drift is larger than 95% of random row deletions of the same size,
 * so the rows removed were not a random sample of it. Red, because red is kept for exactly this - a large
 * drift on its own is not an error state. Draws nothing when the test did not fire or did not apply,
 * never a grey marker, which would read as "tested and passed".
 *
 * Props:
 *  - result: one column's null test, as /api/pgraph/drift_null returns it
 */
export default function DriftFlag({ result }) {
    if (!result?.flagged) return null;

    return (
        <span className="drift-flag" title={`${NULL_FLAG_TITLE} (${Math.round(result.percentile)}th percentile)`}>
            ▲
        </span>
    );
}
