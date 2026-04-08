/**
 * Global context so that all components can update the pgraph based on wrangling that is done
 */

import {createContext, useCallback, useContext, useState} from "react";
import {addEdge, applyEdgeChanges, applyNodeChanges} from "@xyflow/react";
import {TextUpdaterNode} from "../graph_objects/TextUpdaterNode";

export const PGraphContext = createContext(null);

const initialNodes = [
    {
        id: "n1",
        position: {x: 0, y: 0},
        data: {label: "Node 1"},
        type: "input",
    },
    {
        id: "n2",
        position: {x: 100, y: 100},
        data: {label: "Node 2"},
    },
];

const initialEdges = [
    {
        id: "n1-n2",
        source: "n1",
        target: "n2",
        type: "step",
        label: "wrangler operation",
    },
];

const nodeTypes = {
    textUpdater: TextUpdaterNode,
};

export function PGraphProvider({children}) {
    const [nodes, setNodes] = useState(initialNodes);
    const [edges, setEdges] = useState(initialEdges);


    const onNodesChange = useCallback(
        (changes) =>
            setNodes((nodesSnapshot) => applyNodeChanges(changes, nodesSnapshot)),
        [],
    );
    const onEdgesChange = useCallback(
        (changes) =>
            setEdges((edgesSnapshot) => applyEdgeChanges(changes, edgesSnapshot)),
        [],
    );

    const onConnect = useCallback((params) =>
            setEdges((edgesSnapshot) => addEdge(params, edgesSnapshot)),
        [],
    );

    return (
        <PGraphContext.Provider value={{
            nodes, setNodes,
            edges, setEdges,
            onNodesChange, onEdgesChange, onConnect
        }}>
            {children}
        </PGraphContext.Provider>
    )
}

export function usePgraph() {
    return useContext(PGraphContext)
}
