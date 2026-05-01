import {
    ReactFlow,
    Background,
    Controls,
    addEdge,
    MiniMap, ConnectionLineType, Panel, BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../styles/PGraph.css";
import {usePgraph} from "../store/PGraphContext.jsx";
import {useTableName} from "../store/TableNameContext.jsx";
import {useEffect, useState} from "react";


export default function PGraph() {

const { nodes, edges, onNodesChange, onEdgesChange, onConnect, onNodeDoubleClick, nodeTypes} = usePgraph();

const { tableName } = useTableName();
// const [showNote, setShowNote] = useState(false);

// colors the double-clicked node green, and the rest white
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
        <Background color="#ccc" variant={BackgroundVariant.Lines} />
        <Controls />
        {/*<MiniMap nodeStrokeWidth={3} />*/}
      </ReactFlow>
    </div>
  );
}
