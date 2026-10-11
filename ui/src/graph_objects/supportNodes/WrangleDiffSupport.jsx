import WrangleDiffChart from "../../visualizations/WrangleDiffChart.jsx";
import {nodeName} from "../../utils/comparison.js";

/**
 * The wrangle-diff kind of supporting sub-node: hung beside the edge into its host, showing what that edge's
 * wrangle did to the data - the parent's state against the host's, on the column(s) the wrangle acted on.
 *
 * The before is the host's real parent, from the server's graph, even when the parent is drawn folded into a
 * run: the wrangle is the same one either way.
 */
export function WrangleDiffBody({host}) {
    const parent = host?.data?.parent;
    const wrangle = host?.data?.wrangle;
    const columns = wrangle?.columns ?? [];

    if (!parent || parent === "root" || columns.length === 0) {
        return <div className="wrangle-diff-message">Nothing to compare for this edge</div>;
    }

    return (
        <div className="wrangle-diff">
            <div className="wrangle-diff-title" title={`${nodeName(parent)} → ${nodeName(host.id)}`}>
                {wrangle.op} · {columns.join(", ")}
            </div>
            <WrangleDiffChart parent={parent} node={host.id} columns={columns.slice(0, 2)} />
        </div>
    );
}
