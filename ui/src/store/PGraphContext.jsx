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
import {setGraphToClickedNode, getPGraph, getBranchTrajectory} from "../utils/serverCalls.jsx";
import {useDock} from "./DockContext.jsx";
import {descendantsOf} from "../utils/graphTopology.js";
import "../styles/Nodes.css"


export const PGraphContext = createContext(null);

const dagreGraph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

/* The footprint dagre reserves per node. This has to track what the nodes actually measure in
   Nodes.css - min-width 150px plus padding, border, the label and the icon row, and the comparison
   badge that floats above them - because dagre packs the graph to whatever size it is told. The old
   100x75 was smaller than a rendered node, which is why they crowded. */
const nodeWidth = 200;
const nodeHeight = 100;

// Gaps between siblings, between ranks, and between edges sharing a rank. Ranks get the most room:
// that is where the edge labels sit, and where the magnifier's readout hangs.
const NODE_SEPARATION = 50;
const RANK_SEPARATION = 80;
const EDGE_SEPARATION = 14;

/* Roughly how wide an edge label renders, so dagre can reserve space for it. Labels are back to the
   bare operation - "impute", "delete" - with the columns moved into the edge's hover detail, so this
   reserves far less than it did when the columns were printed on the edge itself. */
const EDGE_LABEL_HEIGHT = 20;
const EDGE_LABEL_CHAR_WIDTH = 7;
const MIN_EDGE_LABEL_WIDTH = 44;

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

    /* The server sends type "edgeType", which is not a registered edge type - React Flow silently
       falls back to its bezier default. Name that default outright so the curve is a choice rather
       than a fallback, and so it cannot change under us. */
    const newEdges = edges.map((edge) => ({...edge, type: "default"}));

    return {nodes: newNodes, edges: newEdges};
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

    /* The branch the user is picking out of the graph: an edge fixes where it starts and which way it
       leaves that node, a destination fixes where it stops. Both are chosen by clicking the graph. */
    const [branchSelection, setBranchSelection] = useState({source: null, target: null, destination: null});
    const [branchTrajectory, setBranchTrajectory] = useState(null);
    const [branchTrajectoryLoading, setBranchTrajectoryLoading] = useState(false);

    const selectionStage = !branchSelection.target ? "edge"
        : !branchSelection.destination ? "destination"
        : "complete";

    const startBranchSelection = useCallback(() => {
        setBranchSelection({source: null, target: null, destination: null});
        revealTab("quality");
    }, [revealTab]);

    const resetBranchSelection = useCallback(() => {
        setBranchSelection({source: null, target: null, destination: null});
    }, []);

    /* Clears every selection the graph holds at once - the comparison baseline and the branch alike.
       They are picked with overlapping gestures (shift-click, click, edge click), so a single way out
       matters more than being able to clear them individually. */
    const clearAllSelections = useCallback(() => {
        setBaselineNodeId(null);
        setBranchSelection({source: null, target: null, destination: null});
    }, []);

    const hasAnySelection = Boolean(baselineNodeId || branchSelection.target);

    // Choosing an edge always restarts the branch, since the old destination may not lie beyond it
    const pickBranchEdge = useCallback((source, target) => {
        setBranchSelection({source, target, destination: null});
    }, []);

    const pickBranchDestination = useCallback((destination) => {
        setBranchSelection(current => ({...current, destination}));
    }, []);

    /* Where the branch is allowed to end: the chosen edge's target and everything below it. Computed
       here from the edges the UI already holds, so the graph can show which nodes are pickable
       without a round trip. The server validates the choice independently. */
    const eligibleDestinations = useMemo(
        () => (branchSelection.target ? descendantsOf(edges, branchSelection.target) : new Set()),
        [edges, branchSelection.target]
    );

    /* Fetching lives here rather than in the panel because the graph needs the result too - it lights
       up the branch's edges. Syncing to the server when the selection changes is what effects are for. */
    useEffect(() => {
        let stale = false;

        async function fetchTrajectory() {
            const {source, target, destination} = branchSelection;
            if (!source || !target || !destination) {
                setBranchTrajectory(null);
                return;
            }
            setBranchTrajectoryLoading(true);

            const result = await getBranchTrajectory(source, target, destination);
            // The selection can change while this request is out, so late replies are dropped
            if (stale) return;

            setBranchTrajectory(result?.success ? result : null);
            setBranchTrajectoryLoading(false);
        }

        fetchTrajectory();
        return () => { stale = true; };
    }, [branchSelection]);

    // The edges making up the selected branch, keyed "source->target", for highlighting in the graph
    const selectedBranchEdges = useMemo(() => {
        const path = branchTrajectory?.nodes ?? [];
        const keys = new Set();
        for (let step = 0; step < path.length - 1; step++) {
            keys.add(`${path[step]}->${path[step + 1]}`);
        }
        return keys;
    }, [branchTrajectory]);

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
            /* Navigating picks a new current node, so the comparison falls back to that node's own
               parent rather than keeping a baseline chosen for somewhere else in the graph. The
               branch goes with it: React Flow fires onNodeClick on the first click of a double
               click, so without this, double-clicking a node while choosing where a branch ends
               would both end the branch there and navigate away from it. */
            clearAllSelections();
            // clearHighlight();
            clearScatterPlotCache();
            clearHistogramCache();
            clearHeatMapCache();
            viewContext.setRefreshKey(k => k + 1);
            node.style
        }, [setTableName, viewContext, clearAllSelections]
    )

    /* Shift-click re-targets the delta baseline. A plain click ends a branch that is mid-selection,
       and otherwise does nothing so it does not compete with double-click navigation. Cmd/Ctrl-click
       stays free for React Flow's multi-select. */
    const onNodeClick = useCallback(
        (event, node) => {
            if (!event.shiftKey) {
                if (selectionStage === "destination" && eligibleDestinations.has(node.id)) {
                    event.stopPropagation();
                    pickBranchDestination(node.id);
                }
                return;
            }
            event.stopPropagation();
            setBaselineNodeId(current => (current === node.id ? null : node.id));
        }, [selectionStage, eligibleDestinations, pickBranchDestination]
    )

    /* Clicking an edge starts a branch there. Allowed at any stage so the branch can be re-aimed
       without resetting first. */
    const onEdgeClick = useCallback(
        (event, edge) => {
            event.stopPropagation();
            pickBranchEdge(edge.source, edge.target);
            revealTab("quality");
        }, [pickBranchEdge, revealTab]
    )

    return (
        <PGraphContext.Provider value={{
            nodes, setNodes,
            edges, setEdges,
            nodeTypes,
            onNodesChange, onEdgesChange, onConnect, onLayout,
            getLayoutedElements, onNodeDoubleClick, onNodeClick, onEdgeClick,
            baselineNodeId, setBaselineNodeId, resolvedBaselineId,
            branchSelection, selectionStage, eligibleDestinations, selectedBranchEdges,
            startBranchSelection, resetBranchSelection,
            clearAllSelections, hasAnySelection,
            branchTrajectory, branchTrajectoryLoading,
            refreshGraph
        }}>
            {children}
        </PGraphContext.Provider>
    );
}

export function usePgraph() {
    return useContext(PGraphContext);
}