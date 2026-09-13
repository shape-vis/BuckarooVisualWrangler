import {createContext, useCallback, useContext, useEffect, useMemo, useState} from "react";
import {
    addEdge,
    ConnectionLineType,
    useNodesState,
    useEdgesState
} from "@xyflow/react";
import {NoteNode, RootNoteNode, CollapsedNode} from "../graph_objects/NodeTypes.jsx";
import {ProspectiveNode} from "../graph_objects/ProspectiveNode.jsx";
import dagre from '@dagrejs/dagre';
import {useTableName} from "./TableNameContext"
import {SelectionContext} from "./SelectionContext.jsx";
import { clearScatterPlotCache, clearHeatMapCache, clearHistogramCache } from "./visualizationCaches.jsx";
import {ViewContext} from "../pages/Buckaroo.jsx";
import {setGraphToClickedNode, getPGraph, getBranchTrajectory} from "../utils/serverCalls.jsx";
import {useDock} from "./DockContext.jsx";
import {descendantsOf, orderCollapsibleRun, collapsedRunId, applyCollapse,
        isProspectiveId} from "../utils/graphTopology.js";
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
    rootNoteNode:  RootNoteNode,
    collapsedNode: CollapsedNode,
    prospectiveNode: ProspectiveNode
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

    /* Nodes we build ourselves keep the type and label they were built with. Everything else is
       a node the server sent, which is retyped and re-labelled below. A collapsed placeholder
       stands in for a run; a prospective node stands in for a wrangle that has not happened. */
    const PRESERVED_TYPES = new Set(["collapsedNode", "prospectiveNode"]);
    const isPreserved = (node) => PRESERVED_TYPES.has(node.type);

    nodes.forEach((node) => {
        if (!isPreserved(node)) {
            // A table name too long to fit collapses to just its node id, which is 3 characters under
            // the n{digit}{letter} scheme - n0a, n1b, ... - not the 2 the old n{count} scheme needed
            if (node.data.label.length > 20) {
                node.data.label = node.data.label.slice(0, 3)
            }
            node.type = "noteNode"
        }
        dagreGraph.setNode(node.id, {width: nodeWidth, height: nodeHeight});
    });

    // Find the root by its parent rather than by position: collapsing hands us a filtered list, in
    // which the root is not necessarily first
    const rootNode = nodes.find((node) => node.data.parent === "root") || nodes[0];
    // The || nodes[0] fallback can land on anything, so guard the write as well as the search -
    // otherwise a render with no root would promote a prospective node into the root's shape
    if (rootNode && !isPreserved(rootNode)) rootNode.type = "rootNoteNode"

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

    /* The pair the user set up on purpose: a shift-clicked baseline against the current node. Only
       this pair is badged in the graph and offered to the header's Compare button - the panel's
       fallback to the parent is a default, not a selection. */
    const comparisonPair = useMemo(() => (
        (baselineNodeId && baselineNodeId !== tableName)
            ? {baseline: baselineNodeId, comparator: tableName}
            : null
    ), [baselineNodeId, tableName]);

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

    /* A folded run stands for a sequence of wrangles, so its trajectory is the branch running through
       it: from its head, out through its first step, down to its tail. Selecting it this way means a
       collapsed node's sparkline is the same thing as any other branch's - just one already named. */
    const selectRunBranch = useCallback((runNodes) => {
        if (!runNodes || runNodes.length < 2) return;

        setBranchSelection({
            source: runNodes[0],
            target: runNodes[1],
            destination: runNodes[runNodes.length - 1],
        });
        revealTab("quality");
    }, [revealTab]);

    /* Where the branch is allowed to end: the chosen edge's target and everything below it. Computed
       here from the edges the UI already holds, so the graph can show which nodes are pickable
       without a round trip. The server validates the choice independently. */
    /* descendantsOf now walks the suggestion edges too, so filter them back out - a suggestion
       is not somewhere a branch can end. */
    const eligibleDestinations = useMemo(
        () => (branchSelection.target
            ? new Set([...descendantsOf(edges, branchSelection.target)].filter((id) => !isProspectiveId(id)))
            : new Set()),
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

    /* Runs of nodes folded into a single placeholder in the view. Purely a way of looking at the
       graph: the underlying nodes, their tables and their metrics are untouched, so collapsing can
       never change a number - see §8(b)(ii) and (iii). */
    const [collapsedRuns, setCollapsedRuns] = useState([]);
    const [collapseError, setCollapseError] = useState(null);

    /* The AI's suggestions, drawn as nodes hanging off the node they were asked for. Like
       collapsing, this is a way of looking at the graph rather than part of it: nothing here has
       a table behind it until the user accepts it.

       It lives here, rather than in the context that fetches it, because the effect below is the
       only writer of what React Flow draws. Anything injected through setNodes from outside would
       be erased the next time the server graph or a collapsed run changed. Entries are
       {id, parent, op, label, reason, rowCount, suggestion}. */
    const [prospectiveNodes, setProspectiveNodes] = useState([]);
    const clearProspectiveNodes = useCallback(() => setProspectiveNodes([]), []);

    /* Fold the nodes the user lassoed. Rejects anything that is not one unbroken run on a single
       branch, because collapsing through a fork would orphan the sibling subtree. */
    const collapseNodes = useCallback((selectedIds) => {
        // A lasso catches whatever is under it, suggestions included; they are not part of the
        // run being folded, so drop them before the run is validated
        const run = orderCollapsibleRun(edges, selectedIds.filter((id) => !isProspectiveId(id)));
        if (run.error) {
            setCollapseError(run.error);
            return;
        }

        setCollapseError(null);
        setCollapsedRuns(current => {
            const id = collapsedRunId(run.nodes);
            if (current.some(existing => existing.id === id)) return current;
            return [...current, {id, nodes: run.nodes}];
        });
    }, [edges]);

    const expandRun = useCallback((runId) => {
        setCollapsedRuns(current => current.filter(run => run.id !== runId));
    }, []);

    const expandAllRuns = useCallback(() => setCollapsedRuns([]), []);

    /* The graph as the server sent it, before any folding. Collapsing is derived from this, so
       expanding restores the real nodes without another request. */
    const [serverGraph, setServerGraph] = useState({nodes: [], edges: []});

    /* Every real node by id, whether or not it is drawn. A node folded into a run is gone from
       `nodes`, but anything describing it - the compare modal, say - still needs its data. */
    const serverNodesById = useMemo(
        () => Object.fromEntries(serverGraph.nodes.map((node) => [node.id, node])),
        [serverGraph]
    );

    /* Fold the server's graph into what React Flow should draw, and write it into React Flow's own
       state rather than deriving it alongside.

       This has to be the state React Flow owns. It reports each node's measured size back through
       onNodesChange, and a node missing from that state never receives its dimensions - React Flow
       then keeps it permanently invisible while still laying out around it. */
    useEffect(() => {
        if (serverGraph.nodes.length === 0) return;

        function drawGraph() {
            const folded = applyCollapse(serverGraph.nodes, serverGraph.edges, collapsedRuns);

            /* A suggestion whose parent has been folded into a run has nothing to hang off.
               dagre.setEdge invents a node for an endpoint it does not know, and that invented
               node has no dimensions - which turns every position in the graph into NaN. */
            const visible = new Set(folded.nodes.map((node) => node.id));
            const live = prospectiveNodes.filter((s) => visible.has(s.parent));

            const suggested = live.map((s) => ({
                id: s.id,
                type: "prospectiveNode",
                position: {x: 0, y: 0},
                data: {
                    label: s.label,
                    parent: s.parent,
                    reason: s.reason,
                    rowCount: s.rowCount,
                    errorType: s.errorType,
                    suggestion: s.suggestion,
                    metrics: null,
                },
            }));

            const suggestedEdges = live.map((s) => ({
                id: `e${s.id}`,
                source: s.parent,
                target: s.id,
                label: s.op,
                animated: false,
                style: {stroke: "#7c3aed", strokeDasharray: "6 4"},
            }));

            /* applyCollapse hands back the server's own node objects by reference when nothing is
               folded, and laying out writes type and label onto whatever it is given - so build a
               new array rather than pushing onto that one. */
            const layout = getLayoutedElements(
                [...folded.nodes, ...suggested],
                [...folded.edges, ...suggestedEdges],
            );
            setNodes(layout.nodes);
            setEdges(layout.edges);
        }

        drawGraph();
    }, [serverGraph, collapsedRuns, prospectiveNodes, setNodes, setEdges]);

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

        // Folding and layout happen in the effect above, so both paths into the graph agree
        setServerGraph({nodes: pGraphResult.nodes, edges: pGraphResult.edges});
    }, []);

    /* Pull the graph as soon as there is a table to pull it for.

       Nothing did this before: refreshGraph was only called after a wrangle, undo or redo, so a
       freshly uploaded table rendered the seeded placeholder node above instead of its own root,
       and serverGraph stayed empty. The effect that draws the graph returns early while that is
       true, which meant anything derived from the real graph - the AI's suggestions among them -
       had nothing to attach to and silently never appeared. */
    useEffect(() => {
        if (!tableName) return;

        // Guarded the way the trajectory fetch above is: a reply that arrives after the table
        // has moved on must not write itself into the graph
        let stale = false;
        (async () => {
            const result = await getPGraph();
            if (stale || !result?.nodes) return;
            setServerGraph({nodes: result.nodes, edges: result.edges});
        })();

        return () => { stale = true; };
    }, [tableName]);

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
            // A suggestion has no table behind it, and this sets the app's current table from the
            // node id without asking - navigating to one would point every panel at nothing
            if (isProspectiveId(node.id)) return;
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
            // Same reason: a suggestion cannot be a comparison baseline
            if (isProspectiveId(node.id)) return;
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
            baselineNodeId, setBaselineNodeId, resolvedBaselineId, comparisonPair, serverNodesById,
            branchSelection, selectionStage, eligibleDestinations, selectedBranchEdges,
            prospectiveNodes, setProspectiveNodes, clearProspectiveNodes,
            hasProspectiveNodes: prospectiveNodes.length > 0,
            startBranchSelection, resetBranchSelection,
            clearAllSelections, hasAnySelection,
            collapsedRuns, collapseNodes, expandRun, expandAllRuns, selectRunBranch,
            collapseError, setCollapseError,
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