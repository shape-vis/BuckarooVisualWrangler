import {useCallback} from "react";
import "../styles/Nodes.css"
import { Handle, Position} from "@xyflow/react";
import {IconButton} from "../elements/Buttons.jsx";
import {usePgraph} from "../store/PGraphContext.jsx";
import "../styles/Buttons.css"


/**
 * Names a node's role in the current comparison. Floats above the node so it cannot be confused with
 * the node's own label, and so it costs the node no height in the dagre layout.
 */
function ComparisonBadge( { role } ){
    if (!role) return null;

    return (
        <div className={`node-comparison-badge node-comparison-badge--${role}`}>
            {role === "current" ? "comparator" : "baseline"}
        </div>
    );
}

export function NoteNode( { id, data, isConnectable } ){

const { openNodeDetail } = usePgraph();
// React Flow gives the node its real id; data.label is truncated for display and cannot be used here
const openDetail = useCallback(() => openNodeDetail(id), [openNodeDetail, id]);

return (
    <>
        <Handle type="target" position={Position.Top} isConnectable={isConnectable}/>
        <ComparisonBadge role={data.comparisonRole} />
        <div>
            <div className={"node-node-label"}>
                <h3>{data.label}</h3>
                <div className={"note-node-icon-container"}>
                    <IconButton className="node-sub-buttons">&#8644;</IconButton>
                    <IconButton className="node-sub-buttons">&#9998;</IconButton>
                    <IconButton
                        className="node-sub-button-chart"
                        title="Inspect this node's quality"
                        onClick={openDetail}
                    >&#9602;&#9605;&#9603;&#9607;&#9601;</IconButton>
                </div>
            </div>
        </div>
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
    </>
)
}

export function RootNoteNode( { id, data, isConnectable } ){

const { openNodeDetail } = usePgraph();
const openDetail = useCallback(() => openNodeDetail(id), [openNodeDetail, id]);

return (
    <>
        <ComparisonBadge role={data.comparisonRole} />
        <div>
            <div className={"node-node-label"}>
                <h3>{data.label}</h3>
                <div className={"note-node-icon-container"}>
                    <IconButton className="node-sub-buttons">&#8644;</IconButton>
                    <IconButton className="node-sub-buttons">&#9998;</IconButton>
                    <IconButton
                        className="node-sub-button-chart"
                        title="Inspect this node's quality"
                        onClick={openDetail}
                    >&#9602;&#9605;&#9603;&#9607;&#9601;</IconButton>

                </div>
            </div>
        </div>
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
    </>
)
}