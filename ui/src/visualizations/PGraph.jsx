import {
  ReactFlow,
  Background,
  Controls,
  MiniMap, ConnectionLineType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../styles/PGraph.css";
import {usePgraph} from "../store/PGraphStore.jsx";
import {useTableName} from "../store/TableNameContext.jsx";
import {useMemo} from "react";


export default function PGraph() {

const { nodes, edges, onNodesChange, onEdgesChange, onConnect, onNodeDoubleClick, nodeTypes} = usePgraph();

const { tableName } = useTableName();

const styledNodes = useMemo(() => nodes.map((node) => ({
  ...node,
  style: {
    ...node.style,
    backgroundColor: nodes.length === 1 || node.id === tableName ? "#64ea96" : "white",
  },
})), [nodes, tableName]);


  return (
    <div className="pgraph-container">
      <ReactFlow
        colorMode={"light"}
        nodes={styledNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView={true}
        connectionLineType={ConnectionLineType.SmoothStep}
        onNodeDoubleClick={onNodeDoubleClick}
      >
        <Background />
        <Controls />
        <MiniMap nodeStrokeWidth={3} />
      </ReactFlow>
    </div>
  );
}
