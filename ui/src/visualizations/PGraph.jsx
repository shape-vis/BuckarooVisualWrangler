import {
  ReactFlow,
  Background,
  Controls,
  addEdge,
  MiniMap,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../styles/PGraph.css";
import {getPGraph} from "../store/serverCalls.jsx";
import {usePgraph} from "../store/PGraphContext.tsx";



export default function PGraph() {

const { nodes, setNodes, edges, setEdges, nodeTypes,
  onNodesChange, onEdgesChange, onConnect} = usePgraph();

  async function fetchGraph() {
    try {
      const response = await getPGraph();

      if (!response || !response.success) {
        console.error("[PGRAPH] API call failed:", response);
        throw new Error(`PGraph update failed: ${response.error || "Unknown error"}`);
      }

    } catch (err) {
      console.error(err?.message || err);
    }
  }

  // fetchGraph();

  return (
    <div className="pgraph-container">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView={true}
      >
        <Background />
        <Controls />
        <MiniMap nodeStrokeWidth={3} />
      </ReactFlow>
    </div>
  );
}
