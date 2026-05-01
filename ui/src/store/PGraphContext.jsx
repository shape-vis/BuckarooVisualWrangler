import {createContext, useCallback, useContext} from "react";
import {
    addEdge,
    ConnectionLineType,
    useNodesState,
    useEdgesState
} from "@xyflow/react";
import {NoteNode, RootNoteNode} from "../graph_objects/NodeTypes.jsx";
import dagre from '@dagrejs/dagre';
import {useTableName} from "./TableNameContext"
import {SelectionContext} from "./SelectionContext.jsx";
import { clearScatterPlotCache, clearHeatMapCache, clearHistogramCache } from "./visualizationCaches.jsx";
import {ViewContext} from "../pages/Buckaroo.jsx";
import {setGraphToClickedNode} from "../utils/serverCalls.jsx";
import "../styles/Nodes.css"


export const PGraphContext = createContext(null);

const dagreGraph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
const nodeWidth = 100;
const nodeHeight = 75;


const nodeTypes = {
    noteNode: NoteNode,
    rootNoteNode:  RootNoteNode
};

const getLayoutedElements = (nodes, edges, direction = 'TB') => {
    const isHorizontal = direction === 'LR';
    const dagreGraph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

    dagreGraph.setGraph({rankdir: direction});

    nodes.forEach((node) => {
        if (node.data.label.length > 20) {
            node.data.label = node.data.label.slice(0, 2)
        }
        node.type = "noteNode"
        dagreGraph.setNode(node.id, {width: nodeWidth, height: nodeHeight});
    });

    nodes[0].type = "rootNoteNode"

    edges.forEach((edge) => {
        dagreGraph.setEdge(edge.source, edge.target);
    });

    dagre.layout(dagreGraph);

    const newNodes = nodes.map((node) => {
        const nodeWithPosition = dagreGraph.node(node.id);
        return {
            ...node,
            targetPosition: isHorizontal ? 'left' : 'top',
            sourcePosition: isHorizontal ? 'right' : 'bottom',
            position: {
                x: nodeWithPosition.x - nodeWidth / 2,
                y: nodeWithPosition.y - nodeHeight / 2,
            },

        };
    });

    return {nodes: newNodes, edges};
};

export function PGraphProvider({children}) {
    const {tableName, setTableName} = useTableName();
    const initialNodes = [
        {id: tableName, position: {x: 0, y: 0}, data: {label: tableName}, type: "rootNoteNode"}
    ];

    const viewContext = useContext(ViewContext);
    // const setRefreshKey = viewContext.setRefreshKey();

    const initialEdges = [
        {id: "n1-n2", source: "n1", target: "n2", type: "step", label: "wrangler operation"},
    ];

    // Precompute initial layout once at module load
    const {nodes: layoutedNodes, edges: layoutedEdges} = getLayoutedElements(
        initialNodes,
        initialEdges
    );

    const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState(layoutedEdges);

    const onConnect = useCallback(
        (params) =>
            setEdges((eds) =>
                addEdge(
                    {...params, type: ConnectionLineType.SmoothStep, animated: true},
                    eds,
                ),
            ),
        [setEdges],
    );

    const onLayout = useCallback(
        (direction) => {
            const {nodes: ln, edges: le} = getLayoutedElements(nodes, edges, direction);
            setNodes([...ln]);
            setEdges([...le]);
        },
        [nodes, edges, setNodes, setEdges],
    );

    /* https://reactflow.dev/api-reference/types/node-mouse-handler - this is how you know the params */
    const onNodeDoubleClick = useCallback(
        async (event, node) => {
            //setTableName is a dependency you have to list for this to work
            await setGraphToClickedNode(node.id);
            setTableName(node.id);
            // clearHighlight();
            clearScatterPlotCache();
            clearHistogramCache();
            clearHeatMapCache();
            viewContext.setRefreshKey(k => k + 1);
            node.style
        }, [setTableName, viewContext]
    )

    return (
        <PGraphContext.Provider value={{
            nodes, setNodes,
            edges, setEdges,
            nodeTypes,
            onNodesChange, onEdgesChange, onConnect, onLayout,
            getLayoutedElements, onNodeDoubleClick
        }}>
            {children}
        </PGraphContext.Provider>
    );
}

export function usePgraph() {
    return useContext(PGraphContext);
}