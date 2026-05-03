import {
    ReactFlow,
    Background,
    Controls,
    ConnectionLineType, BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../styles/PGraph.css";
import {usePgraph} from "../store/PGraphContext.jsx";
import {useTableName} from "../store/TableNameContext.jsx";
import {useAttributeSelection} from "../store/AttributeSelectionContext.jsx";
import {useEffect} from "react";


export default function PGraph() {

    const { nodes, setNodes, edges, onNodesChange, onEdgesChange, onConnect, onNodeDoubleClick, onNodeClick, nodeTypes } = usePgraph();
    const { tableName } = useTableName();
    const { comparisonNodeId } = useAttributeSelection();

    useEffect(() => {
        setNodes((nds) =>
            nds.map((node) => {
                const isActive = nds.length === 1 || node.id === tableName;
                const isComparison = node.id === comparisonNodeId && !isActive;
                let backgroundColor = "white";
                if (isActive) backgroundColor = "#64ea96";
                else if (isComparison) backgroundColor = "#a8c8ff";
                return {
                    ...node,
                    style: { ...(node.style || {}), backgroundColor },
                };
            })
        );
    }, [tableName, comparisonNodeId, setNodes]);


    return (
        <div className="pgraph-container">
            <ReactFlow
                colorMode={"light"}
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                fitView={true}
                connectionLineType={ConnectionLineType.SmoothStep}
                onNodeDoubleClick={onNodeDoubleClick}
                onNodeClick={onNodeClick}
            >
                <Background color="#ccc" variant={BackgroundVariant.Lines} />
                <Controls />
            </ReactFlow>
        </div>
    );
}
