import {usePgraph} from "../../store/PGraphContext.jsx";
import {showTooltip, moveTooltip, hideTooltip} from "../../utils/visCommon.jsx";
import {escapeHtml} from "../../utils/html.js";
import {getSupportType} from "./registry.js";
import "../../styles/SupportNode.css";

/**
 * A node's hidden supporting sub-nodes, as badges in a row across its top edge - the way a trading card carries
 * its small symbols. Every sub-node of the node that is not drawn has one, whatever hid it: its own minimise,
 * the node's eye, or one of the graph's toggles. Each badge is its kind's tiny picture of itself (the registry's
 * Badge); hovering one names it, and clicking it brings that one sub-node back, leaving the rest as they were.
 *
 * It floats over the card's edge rather than taking room in it, so it costs the dagre layout nothing.
 */
export function SupportBadges({hostId}) {
    const {supportNodes, isSupportShown, restoreSupportNode, graphMode} = usePgraph();

    // The plot hides every sub-node, so badges there would only clutter it
    if (graphMode === "analysis") return null;

    const hidden = supportNodes.filter((record) => record.hostId === hostId && !isSupportShown(record));
    if (hidden.length === 0) return null;

    const stop = (event) => event.stopPropagation();

    return (
        <div className="support-badges" onDoubleClick={stop}>
            {hidden.map((record) => {
                const type = getSupportType(record.kind);
                const Badge = type?.Badge;
                const label = type?.label ?? record.kind;
                const summary = type?.summary?.(record) ?? "";

                const labelText = escapeHtml(label);
                const summaryText = escapeHtml(summary);
                let tooltip = `<strong>${labelText}</strong><br/>`;
                if (summaryText) {
                    tooltip += `${summaryText}<br/>`;
                }
                tooltip += "Click to show it again";

                return (
                    <button
                        key={record.id}
                        type="button"
                        className="support-badge"
                        aria-label={`Show ${label}`}
                        onClick={(event) => {
                            stop(event);
                            hideTooltip();
                            restoreSupportNode(record.id);
                        }}
                        onMouseEnter={(event) => showTooltip(tooltip, event)}
                        onMouseMove={moveTooltip}
                        onMouseLeave={hideTooltip}
                    >
                        {Badge && <Badge record={record} />}
                    </button>
                );
            })}
        </div>
    );
}
