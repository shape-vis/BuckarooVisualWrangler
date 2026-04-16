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
import {usePgraph} from "../store/PGraphContext.tsx";


export default function PGraph() {

const { nodes, setNodes, edges, setEdges, nodeTypes,
  onNodesChange, onEdgesChange, onConnect, onLayout} = usePgraph();

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



  return (
    <div className="pgraph-container">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        // nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView={true}
        connectionLineType={ConnectionLineType.SmoothStep}
      >
        <Panel position="top-right">
        <button className="xy-theme__button" onClick={() => onLayout('TB')}>
          vertical layout
        </button>
        <button className="xy-theme__button" onClick={() => onLayout('LR')}>
          horizontal layout
        </button>
      </Panel>
        <Background />
        <Controls />
        <MiniMap nodeStrokeWidth={3} />
      </ReactFlow>
    </div>
  );
}
