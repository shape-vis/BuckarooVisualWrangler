import {createContext, useCallback, useContext} from "react";
import {
    addEdge,
    ConnectionLineType,
    useNodesState,
    useEdgesState
} from "@xyflow/react";
import {NoteNode, RootNoteNode} from "../graph_objects/NodeTypes.jsx";
import {ShadowNode} from "../graph_objects/ShadowNode.jsx";
import {PlanShadowNode} from "../graph_objects/PlanShadowNode.jsx";
import {PlanStepShadow} from "../graph_objects/PlanStepShadow.jsx";
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
const SHADOW_NODE_WIDTH = 280;
const SHADOW_NODE_HEIGHT = 140;
const STEP_SHADOW_NODE_WIDTH = 440;
const STEP_SHADOW_NODE_HEIGHT = 320;

const NODE_OVERRIDES_KEY = "pgraph-node-overrides";

const loadNodeOverrides = () => {
    try {
        const raw = sessionStorage.getItem(NODE_OVERRIDES_KEY);
        return raw ? JSON.parse(raw) : {};
    } catch {
        return {};
    }
};

const saveNodeOverrides = (overrides) => {
    try {
        sessionStorage.setItem(NODE_OVERRIDES_KEY, JSON.stringify(overrides));
    } catch {
        // sessionStorage unavailable — overrides simply won't persist this run
    }
};

const updateNodeOverride = (nodeId, patch) => {
    const overrides = loadNodeOverrides();
    overrides[nodeId] = { ...(overrides[nodeId] || {}), ...patch };
    saveNodeOverrides(overrides);
};

const applyNodeOverrides = (nodes) => {
    const overrides = loadNodeOverrides();
    return nodes.map((n) => {
        const o = overrides[n.id];
        if (!o) return n;
        return { ...n, data: { ...n.data, ...o } };
    });
};


const nodeTypes = {
    noteNode: NoteNode,
    rootNoteNode: RootNoteNode,
    shadowNode: ShadowNode,
    planShadowNode: PlanShadowNode,
    planStepShadow: PlanStepShadow,
};

const getLayoutedElements = (nodes, edges, direction = 'TB') => {
    const isHorizontal = direction === 'LR';
    const dagreGraph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

    dagreGraph.setGraph({rankdir: direction, nodesep: 40, ranksep: 60});

    nodes.forEach((node, idx) => {
        if (node.data.label.length > 20) {
            node.data.label = node.data.label.slice(0, 2)
        }
        if (!node.type) {
            node.type = idx === 0 ? "rootNoteNode" : "noteNode";
        }
        const isShadow = node.type === "shadowNode" || node.type === "planShadowNode" || node.type === "planStepShadow" || node.data?.isShadow;
        const isStepShadow = node.type === "planStepShadow";
        const w = isStepShadow ? STEP_SHADOW_NODE_WIDTH : (isShadow ? SHADOW_NODE_WIDTH : DEFAULT_NODE_WIDTH);
        const h = isStepShadow ? STEP_SHADOW_NODE_HEIGHT : (isShadow ? SHADOW_NODE_HEIGHT : DEFAULT_NODE_HEIGHT);
        dagreGraph.setNode(node.id, {width: w, height: h});
    });

    edges.forEach((edge) => {
        dagreGraph.setEdge(edge.source, edge.target);
    });

    dagre.layout(dagreGraph);

    const newNodes = nodes.map((node) => {
        const nodeWithPosition = dagreGraph.node(node.id);
        const isShadow = node.type === "shadowNode" || node.type === "planShadowNode" || node.type === "planStepShadow" || node.data?.isShadow;
        const isStepShadow = node.type === "planStepShadow";
        const w = isStepShadow ? STEP_SHADOW_NODE_WIDTH : (isShadow ? SHADOW_NODE_WIDTH : DEFAULT_NODE_WIDTH);
        const h = isStepShadow ? STEP_SHADOW_NODE_HEIGHT : (isShadow ? SHADOW_NODE_HEIGHT : DEFAULT_NODE_HEIGHT);
        return {
            ...node,
            targetPosition: isHorizontal ? 'left' : 'top',
            sourcePosition: isHorizontal ? 'right' : 'bottom',
            position: {
                x: nodeWithPosition.x - w / 2,
                y: nodeWithPosition.y - h / 2,
            },
        };
    });

    return {nodes: applyNodeOverrides(newNodes), edges};
};

export function PGraphProvider({children}) {
    const {tableName, setTableName} = useTableName();
    const { setComparisonNodeIds, comparisonMode, MAX_COMPARISONS } = useAttributeSelection();
    const initialNodes = [
        {id: tableName, position: {x: 0, y: 0}, data: {label: tableName}, type: "rootNoteNode"}
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

    const setNodeNote = useCallback((nodeId, note) => {
        updateNodeOverride(nodeId, { note });
        setNodes((nds) => nds.map((n) =>
            n.id === nodeId ? { ...n, data: { ...n.data, note } } : n
        ));
    }, [setNodes]);

    const setNodeLabel = useCallback((nodeId, label) => {
        updateNodeOverride(nodeId, { label });
        setNodes((nds) => nds.map((n) =>
            n.id === nodeId ? { ...n, data: { ...n.data, label } } : n
        ));
    }, [setNodes]);

    const onNodeDoubleClick = useCallback(
        async (event, node) => {
            if (node.data?.isShadow) return;
            await setGraphToClickedNode(node.id);
            setTableName(node.id);
            setComparisonNodeIds([]);
            clearScatterPlotCache();
            clearHistogramCache();
            clearHeatMapCache();
            viewContext.setRefreshKey(k => k + 1);
        }, [setTableName, setComparisonNodeIds, viewContext]
    )

    const onNodeClick = useCallback((event, node) => {
        if (!event?.shiftKey) return;
        if (node.id === tableName) {
            setComparisonNodeIds([]);
            return;
        }
        if (comparisonMode === 'single') {
            setComparisonNodeIds(prev => prev[0] === node.id ? [] : [node.id]);
            return;
        }
        setComparisonNodeIds(prev => {
            if (prev.includes(node.id)) return prev.filter(x => x !== node.id);
            if (prev.length >= MAX_COMPARISONS) return prev;
            return [...prev, node.id];
        });
    }, [tableName, setComparisonNodeIds, comparisonMode, MAX_COMPARISONS]);

    return (
        <PGraphContext.Provider value={{
            nodes, setNodes,
            edges, setEdges,
            nodeTypes,
            onNodesChange, onEdgesChange, onConnect, onLayout,
            getLayoutedElements, onNodeDoubleClick, onNodeClick,
            setNodeNote, setNodeLabel,
        }}>
            {children}
        </PGraphContext.Provider>
    );
}

export function usePgraph() {
    return useContext(PGraphContext);
}
