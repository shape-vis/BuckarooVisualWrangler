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
import { useAttributeSelection } from "./AttributeSelectionContext.jsx";
import { clearScatterPlotCache, clearHeatMapCache, clearHistogramCache } from "./visualizationCaches.jsx";
import {ViewContext} from "../pages/Buckaroo.jsx";
import {setGraphToClickedNode} from "../utils/serverCalls.jsx";
import "../styles/Nodes.css"


export const PGraphContext = createContext(null);

const DEFAULT_NODE_WIDTH = 100;
const DEFAULT_NODE_HEIGHT = 75;
export const EMBEDDED_NODE_WIDTH = 820;
export const EMBEDDED_NODE_HEIGHT = 660;


const nodeTypes = {
    noteNode: NoteNode,
    rootNoteNode:  RootNoteNode
};

const getNodeDims = (node) => {
    const styleW = node.style?.width;
    const styleH = node.style?.height;
    const measuredW = node.measured?.width;
    const measuredH = node.measured?.height;
    if (node.data?.showPlots) {
        return {
            width: styleW || measuredW || EMBEDDED_NODE_WIDTH,
            height: styleH || measuredH || EMBEDDED_NODE_HEIGHT,
        };
    }
    return {
        width: styleW || measuredW || DEFAULT_NODE_WIDTH,
        height: styleH || measuredH || DEFAULT_NODE_HEIGHT,
    };
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
        const {width, height} = getNodeDims(node);
        dagreGraph.setNode(node.id, {width, height});
    });

    nodes[0].type = "rootNoteNode"

    edges.forEach((edge) => {
        dagreGraph.setEdge(edge.source, edge.target);
    });

    dagre.layout(dagreGraph);

    const newNodes = nodes.map((node) => {
        const nodeWithPosition = dagreGraph.node(node.id);
        const {width, height} = getNodeDims(node);
        return {
            ...node,
            targetPosition: isHorizontal ? 'left' : 'top',
            sourcePosition: isHorizontal ? 'right' : 'bottom',
            position: {
                x: nodeWithPosition.x - width / 2,
                y: nodeWithPosition.y - height / 2,
            },

        };
    });

    return {nodes: newNodes, edges};
};

export function PGraphProvider({children}) {
    const {tableName, setTableName} = useTableName();
    const { setComparisonNodeId } = useAttributeSelection();
    const initialNodes = [
        {id: tableName, position: {x: 0, y: 0}, data: {label: tableName, showPlots: false}, type: "rootNoteNode"}
    ];

    const viewContext = useContext(ViewContext);

    const initialEdges = [
        {id: "n1-n2", source: "n1", target: "n2", type: "step", label: "wrangler operation"},
    ];

    const {nodes: layoutedNodes, edges: layoutedEdges} = getLayoutedElements(
        initialNodes,
        initialEdges,
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

    const toggleNodePlots = useCallback((nodeId) => {
        setNodes((nds) => {
            const flipped = nds.map((n) => {
                if (n.id !== nodeId) return n;
                const next = !n.data?.showPlots;
                const style = {...(n.style || {})};
                if (next) {
                    style.width = style.width || EMBEDDED_NODE_WIDTH;
                    style.height = style.height || EMBEDDED_NODE_HEIGHT;
                } else {
                    delete style.width;
                    delete style.height;
                }
                return {
                    ...n,
                    data: {...n.data, showPlots: next},
                    style,
                };
            });
            const {nodes: laid} = getLayoutedElements(flipped, edges);
            return laid;
        });
    }, [setNodes, edges]);

    const setNodeNote = useCallback((nodeId, note) => {
        setNodes((nds) => nds.map((n) =>
            n.id === nodeId ? { ...n, data: { ...n.data, note } } : n
        ));
    }, [setNodes]);

    const collapseNode = useCallback((nodeId) => {
        setNodes((nds) => {
            const collapsed = nds.map((n) => {
                if (n.id !== nodeId) return n;
                const style = {...(n.style || {})};
                delete style.width;
                delete style.height;
                return {
                    ...n,
                    data: {...n.data, showPlots: false},
                    style,
                };
            });
            const {nodes: laid} = getLayoutedElements(collapsed, edges);
            return laid;
        });
    }, [setNodes, edges]);

    const onNodeDoubleClick = useCallback(
        async (event, node) => {
            await setGraphToClickedNode(node.id);
            setTableName(node.id);
            setComparisonNodeId(null);
            clearScatterPlotCache();
            clearHistogramCache();
            clearHeatMapCache();
            viewContext.setRefreshKey(k => k + 1);
        }, [setTableName, setComparisonNodeId, viewContext]
    )

    const onNodeClick = useCallback((event, node) => {
        if (!event?.shiftKey) return;
        if (node.id === tableName) {
            setComparisonNodeId(null);
            return;
        }
        setComparisonNodeId((prev) => (prev === node.id ? null : node.id));
    }, [tableName, setComparisonNodeId]);

    return (
        <PGraphContext.Provider value={{
            nodes, setNodes,
            edges, setEdges,
            nodeTypes,
            onNodesChange, onEdgesChange, onConnect, onLayout,
            getLayoutedElements, onNodeDoubleClick, onNodeClick,
            toggleNodePlots, collapseNode, setNodeNote,
        }}>
            {children}
        </PGraphContext.Provider>
    );
}

export function usePgraph() {
    return useContext(PGraphContext);
}
