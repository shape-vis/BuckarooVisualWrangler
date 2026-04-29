import {useCallback} from "react";
import "../styles/Nodes.css"
import { Handle, Position} from "@xyflow/react";


export function SelectedNode( { data, isConnectable } ){

return (
    <>
        <Handle type="target" position={Position.Top} isConnectable={isConnectable} />
        {data.label}
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
    </>
)
}