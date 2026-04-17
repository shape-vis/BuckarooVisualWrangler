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


export default function PGraph() {

const { nodes, edges, onNodesChange, onEdgesChange, onConnect, onNodeDoubleClick} = usePgraph();

const { tableName } = useTableName();

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
        onNodeDoubleClick={onNodeDoubleClick}
      >
        <Background />
        <Controls />
        <MiniMap nodeStrokeWidth={3} />
      </ReactFlow>
    </div>
  );
}
