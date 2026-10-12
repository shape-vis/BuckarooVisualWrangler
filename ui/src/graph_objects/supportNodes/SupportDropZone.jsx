import {useState} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {SUPPORT_DRAG_TYPE} from "../../store/supportNodes.js";
import {nodeName} from "../../utils/comparison.js";
import "../../styles/Nodes.css";

/**
 * Where a sub-node dragged in from outside the graph can be dropped: drawn over its host's group, or over a
 * group of the default size when the host has none yet, only while such a drag is under way. Groups themselves
 * take no pointer events, so this is the one place in the graph that accepts the drop - anywhere else the
 * browser refuses it and nothing happens.
 */
export function SupportDropZone({data}) {
    const {supportDrag, addSupportNode, endSupportDrag} = usePgraph();
    const [over, setOver] = useState(false);

    const accepts = (event) => event.dataTransfer.types.includes(SUPPORT_DRAG_TYPE);

    const onDragOver = (event) => {
        if (!accepts(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        setOver(true);
    };

    const onDrop = (event) => {
        if (!accepts(event)) return;
        event.preventDefault();
        setOver(false);
        let payload = supportDrag;
        try {
            payload = JSON.parse(event.dataTransfer.getData(SUPPORT_DRAG_TYPE)) ?? payload;
        } catch {
            // Some browsers keep the data back; the drag's own record of it is as good
        }
        // Only for the node it belongs to: the zone is drawn there, but a stale drag must not land elsewhere
        if (payload?.hostId === data.hostId) addSupportNode(payload.hostId, payload.kind, payload.config);
        endSupportDrag();
    };

    return (
        <div
            className={`support-drop-zone nodrag nopan ${over ? "support-drop-zone--over" : ""}`}
            style={{width: data.width, height: data.height}}
            onDragOver={onDragOver}
            onDragEnter={onDragOver}
            onDragLeave={() => setOver(false)}
            onDrop={onDrop}
        >
            <span className="support-drop-zone-label">Drop to keep it beside {nodeName(data.hostId)}</span>
        </div>
    );
}
