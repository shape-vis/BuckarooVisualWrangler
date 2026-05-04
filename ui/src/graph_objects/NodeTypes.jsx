import {useCallback} from "react";
import "../styles/Nodes.css"
import { Handle, Position} from "@xyflow/react";
import {IconButton} from "../elements/Buttons.jsx";
import "../styles/Buttons.css"


export function NoteNode( { data, isConnectable } ){

return (
    <>
        <Handle type="target" position={Position.Top} isConnectable={isConnectable}/>
        <div>
            <div className={"node-node-label"}>
                <h3>{data.label}</h3>
                <div className={"note-node-icon-container"}>
                    <IconButton className="node-sub-buttons">&#8644;</IconButton>
                    <IconButton className="node-sub-buttons">&#9998;</IconButton>
                    <IconButton className="node-sub-button-chart">&#9602;&#9605;&#9603;&#9607;&#9601;</IconButton>
                </div>
            </div>
        </div>
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
    </>
)
}

export function RootNoteNode( { data, isConnectable } ){

return (
    <>
        <div>
            <div className={"node-node-label"}>
                <h3>{data.label}</h3>
                <div className={"note-node-icon-container"}>
                    <IconButton className="node-sub-buttons">&#8644;</IconButton>
                    <IconButton className="node-sub-buttons">&#9998;</IconButton>
                    <IconButton className="node-sub-button-chart">&#9602;&#9605;&#9603;&#9607;&#9601;</IconButton>

                </div>
            </div>
        </div>
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
    </>
)
}