import {
  ReactFlow,
  Background,
  Controls,
  addEdge,
  MiniMap, ConnectionLineType, Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../styles/PGraph.css";
import {getPGraph} from "../utils/serverCalls.jsx";
import {usePgraph} from "../store/PGraphContext.jsx";
import {useTableName} from "../store/TableNameContext.jsx";
import {useEffect} from "react";


export default function PGraph() {

const { nodes, edges, onNodesChange, onEdgesChange, onConnect, onNodeDoubleClick, nodeTypes} = usePgraph();

const { tableName } = useTableName();

useEffect(() => {
    nodes.forEach((node) => {
      if (nodes.length === 1) {
          node.style = {backgroundColor: "#64ea96"}
      } else if (nodes.length > 1) {
          if (node.id === tableName) {
              node.style = {backgroundColor: "#64ea96"}
          }
          else {
              node.style = {backgroundColor: "white"}
          }
      }
    })
}, [])


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
      >
        <Background />
        <Controls />
        <MiniMap nodeStrokeWidth={3} />
      </ReactFlow>
    </div>
  );
}
