import {createContext, useCallback, useContext, useEffect, useMemo, useState} from "react";
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
import {setGraphToClickedNode, getPGraph, getQualityTrajectory} from "../utils/serverCalls.jsx";
import {useDock} from "./DockContext.jsx";
import {branchColor, SHARED_BRANCH_COLOR} from "./branchColors.js";
import "../styles/Nodes.css"


export const PGraphContext = createContext(null);

const dagreGraph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

/* The footprint dagre reserves per node. This has to track what the nodes actually measure in
   Nodes.css - min-width 150px plus padding, border, the label and the icon row, and the comparison
   badge that floats above them - because dagre packs the graph to whatever size it is told. The old
   100x75 was smaller than a rendered node, which is why they crowded. */
const nodeWidth = 200;
const nodeHeight = 100;

// Gaps between siblings, between ranks, and between edges sharing a rank. Ranks need the most room:
// that is where the edge labels sit.
const NODE_SEPARATION = 70;
const RANK_SEPARATION = 110;
const EDGE_SEPARATION = 24;

/* Roughly how wide an edge label renders, so dagre can reserve space for it. Labels name the columns
   now ("delete · salary × years"), so they are long enough to collide with a sibling branch's label
   unless the layout accounts for them. */
const EDGE_LABEL_HEIGHT = 22;
const EDGE_LABEL_CHAR_WIDTH = 7;
const MIN_EDGE_LABEL_WIDTH = 60;

const edgeLabelSize = (label) => ({
    width: Math.max(MIN_EDGE_LABEL_WIDTH, String(label ?? "").length * EDGE_LABEL_CHAR_WIDTH),
    height: EDGE_LABEL_HEIGHT,
    labelpos: "c",
});


const nodeTypes = {
    noteNode: NoteNode,
    rootNoteNode:  RootNoteNode
};

const getLayoutedElements = (nodes, edges, direction = 'TB') => {
    const isHorizontal = direction === 'LR';
    const dagreGraph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

    if (!nodes || nodes.length === 0) return {nodes: [], edges: edges || []};

    dagreGraph.setGraph({
        rankdir: direction,
        nodesep: NODE_SEPARATION,
        ranksep: RANK_SEPARATION,
        edgesep: EDGE_SEPARATION,
    });

    nodes.forEach((node) => {
        // A table name too long to fit collapses to just its node id, which is 3 characters under the
        // n{digit}{letter} scheme - n0a, n1b, ... - rather than the 2 the old n{count} scheme needed
        if (node.data.label.length > 20) {
            node.data.label = node.data.label.slice(0, 3)
        }
        node.type = "noteNode"
        dagreGraph.setNode(node.id, {width: nodeWidth, height: nodeHeight});
    });

    // Find the root by its parent rather than by position: collapsing hands us a filtered list, in
    // which the root is not necessarily first
    const rootNode = nodes.find((node) => node.data.parent === "root") || nodes[0];
    rootNode.type = "rootNoteNode"

    edges.forEach((edge) => {
        // Passing the label's size makes dagre lay the graph out around the labels rather than
        // letting sibling branches print theirs on top of one another
        dagreGraph.setEdge(edge.source, edge.target, edgeLabelSize(edge.label));
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
    // Opening a node's details brings the dock forward on its tab
    const {revealTab} = useDock();
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

    // The node the attribute summary panel compares the current node against. null means "fall back
    // to the current node's parent".
    const [baselineNodeId, setBaselineNodeId] = useState(null);

    // Which node the comparison actually resolves to. Lives here rather than in the panel so the
    // graph marks the same pair the panel is reporting on, including the un-pinned parent default.
    const resolvedBaselineId = useMemo(() => {
        if (baselineNodeId && baselineNodeId !== tableName) return baselineNodeId;

        const parent = nodes.find((node) => node.id === tableName)?.data?.parent;
        // The root's parent is the string "root", which is not a node, so the root has no baseline
        return (parent && parent !== "root") ? parent : null;
    }, [baselineNodeId, tableName, nodes]);

    // The node the detail panel is inspecting
    const [detailNodeId, setDetailNodeId] = useState(null);
    const [trajectory, setTrajectory] = useState(null);
    const [trajectoryLoading, setTrajectoryLoading] = useState(false);

    const openNodeDetail = useCallback((nodeId) => {
        setDetailNodeId(nodeId);
        revealTab("detail");
    }, [revealTab]);

    /* Fetching the trajectory lives here rather than in the detail panel because the graph needs it
       too: it colors each branch's edges to match that branch's line in the sparklines. Syncing with
       the server when the inspected node changes is what an effect is actually for. */
    useEffect(() => {
        let stale = false;

        async function fetchTrajectory() {
            if (!detailNodeId) {
                setTrajectory(null);
                return;
            }
            setTrajectoryLoading(true);

            const result = await getQualityTrajectory(detailNodeId);
            // A second node can be opened while this request is still out, so late replies are dropped
            if (stale) return;

            setTrajectory(result?.success ? result : null);
            setTrajectoryLoading(false);
        }

        fetchTrajectory();
        return () => { stale = true; };
    }, [detailNodeId]);

    /* Which color each graph edge takes, keyed "source->target". An edge on more than one branch is
       upstream of their fork and belongs to neither, so it stays neutral. */
    const branchEdgeColors = useMemo(() => {
        const claims = new Map();

        (trajectory?.branches ?? []).forEach((branch, index) => {
            for (let step = 0; step < branch.nodes.length - 1; step++) {
                const key = `${branch.nodes[step]}->${branch.nodes[step + 1]}`;
                if (!claims.has(key)) claims.set(key, new Set());
                claims.get(key).add(index);
            }
        });

        const colors = new Map();
        claims.forEach((branchIndexes, key) => {
            colors.set(key, branchIndexes.size === 1
                ? branchColor([...branchIndexes][0])
                : SHARED_BRANCH_COLOR);
        });
        return colors;
    }, [trajectory]);

    // Pull the graph from the server and re-layout it. Every path that mutates the graph - executing a
    // wrangle, undo, redo - has to call this, or the rendered graph drifts from the real one.
    const refreshGraph = useCallback(async () => {
        const pGraphResult = await getPGraph();
        if (!pGraphResult?.nodes) return;

        const layout = getLayoutedElements(pGraphResult.nodes, pGraphResult.edges);
        setNodes(layout.nodes);
        setEdges(layout.edges);
    }, [setNodes, setEdges]);

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
            // Navigating picks a new current node, so the comparison falls back to that node's own
            // parent rather than keeping a baseline chosen for somewhere else in the graph
            setBaselineNodeId(null);
            // clearHighlight();
            clearScatterPlotCache();
            clearHistogramCache();
            clearHeatMapCache();
            viewContext.setRefreshKey(k => k + 1);
            node.style
        }, [setTableName, viewContext]
    )

    /* Shift-click re-targets the delta baseline. A plain click is left alone so it does not compete
       with double-click navigation, and Cmd/Ctrl-click stays free for React Flow's multi-select. */
    const onNodeClick = useCallback(
        (event, node) => {
            if (!event.shiftKey) return;
            event.stopPropagation();
            setBaselineNodeId(current => (current === node.id ? null : node.id));
        }, []
    )

    return (
        <PGraphContext.Provider value={{
            nodes, setNodes,
            edges, setEdges,
            nodeTypes,
            onNodesChange, onEdgesChange, onConnect, onLayout,
            getLayoutedElements, onNodeDoubleClick, onNodeClick,
            baselineNodeId, setBaselineNodeId, resolvedBaselineId,
            detailNodeId, openNodeDetail,
            trajectory, trajectoryLoading, branchEdgeColors,
            refreshGraph
        }}>
            {children}
        </PGraphContext.Provider>
    );
}

export function usePgraph() {
    return useContext(PGraphContext);
}