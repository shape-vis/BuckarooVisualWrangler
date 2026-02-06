import {ReactFlow, Background, Controls, addEdge, MiniMap} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {useState, useCallback, Activity} from 'react'
import { applyEdgeChanges, applyNodeChanges } from '@xyflow/react';
import {TextUpdaterNode} from "../../../../pgraph-scratch/src/TextUpdaterNode.jsx";

const nodeTypes = {
    textUpdater: TextUpdaterNode
}

const initialNodes = [
    {
        id: 'n1',
        position: { x: 0, y: 0 },
        data: { label: 'Node 1' },
        type: 'input',
    },
    {
        id: 'n2',
        position: { x: 100, y: 100 },
        data: { label: 'Node 2' },
    },

];

const initialEdges = [
    {
        id: 'n1-n2',
        source: 'n1',
        target: 'n2',
        type: 'step',
        label: 'wrangler operation'
    },
];

export default function PGraph(){

    const [nodes, setNodes] = useState(initialNodes);
    const [edges, setEdges] = useState(initialEdges);
    const onNodesChange = useCallback(
        (changes) => setNodes((nodesSnapshot) => applyNodeChanges(changes, nodesSnapshot)),
        [],
    );
    const onEdgesChange = useCallback(
        (changes) => setEdges((edgesSnapshot) => applyEdgeChanges(changes, edgesSnapshot)),
        [],
    );

    const onConnect = useCallback(
        (params) => setEdges((edgesSnapshot) =>addEdge(params, edgesSnapshot))
    )


  return (
  
        <div style={{ height: '100%', width: '100%' }}>
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
    )}
    