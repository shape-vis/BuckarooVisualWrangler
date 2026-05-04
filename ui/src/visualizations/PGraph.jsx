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
    const { comparisonNodeIds } = useAttributeSelection();

    useEffect(() => {
        const shades = ["#a8c8ff", "#92baff", "#7fadff", "#6fa1ff"];
        setNodes((nds) =>
            nds.map((node) => {
                const isActive = nds.length === 1 || node.id === tableName;
                const cmpIdx = !isActive ? comparisonNodeIds.indexOf(node.id) : -1;
                let backgroundColor = "white";
                if (isActive) backgroundColor = "#64ea96";
                else if (cmpIdx >= 0) backgroundColor = shades[cmpIdx] ?? "#a8c8ff";
                return {
                    ...node,
                    style: { ...(node.style || {}), backgroundColor },
                };
            })
        );
    }, [tableName, comparisonNodeIds, setNodes]);


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
