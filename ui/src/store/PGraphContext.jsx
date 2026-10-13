import {createContext, useCallback, useContext, useEffect, useMemo, useRef, useState} from "react";
import {
    addEdge,
    ConnectionLineType,
    useNodesState,
    useEdgesState
} from "@xyflow/react";
import {NoteNode, RootNoteNode, CollapsedNode, AnalysisDotNode} from "../graph_objects/NodeTypes.jsx";
import {ProspectiveNode} from "../graph_objects/ProspectiveNode.jsx";
import dagre from '@dagrejs/dagre';
import {useTableName} from "./TableNameContext"
import { clearScatterPlotCache, clearHeatMapCache, clearHistogramCache } from "./visualizationCaches.jsx";
import {ViewContext} from "../pages/Buckaroo.jsx";
import {setGraphToClickedNode, getPGraph, getBranchTrajectory} from "../utils/serverCalls.jsx";
import {useDock} from "./DockContext.jsx";
import {descendantsOf, orderCollapsibleRun, collapsedRunId, applyCollapse,
        isSupportId} from "../utils/graphTopology.js";
import {SupportNode} from "../graph_objects/supportNodes/SupportNode.jsx";
import {SupportGroup} from "../graph_objects/supportNodes/SupportGroup.jsx";
import {SupportDropZone} from "../graph_objects/supportNodes/SupportDropZone.jsx";
import {EDGE_GAP, branchSides, edgeReserve, placeSupportNodes, sideReserve, spreadSupportGroups, treeEdgesOf} from "../graph_objects/supportNodes/supportLayout.js";
import {useSupportNodes} from "./supportNodes.js";
import {setNodeLabels} from "../utils/comparison.js";
import "../styles/Nodes.css";
import "../styles/SupportNode.css";
import "../styles/ProspectiveNode.css";
import "../styles/AnalysisDot.css";


export const PGraphContext = createContext(null);

/* The footprint dagre reserves per node. This has to track what the nodes actually measure in
   Nodes.css - min-width 150px plus padding, border, the label and the icon row, and the comparison
   badge that floats above them - because dagre packs the graph to whatever size it is told, and a
   footprint smaller than a rendered node crowds them. */
const nodeWidth = 200;
const nodeHeight = 100;

/* A candidate draws its preview chart, so it is about three cards tall: its title, rows and reason, the chart,
   its buttons and the node tools. Dagre reserves that, so the chart does not run into the rank below. */
const PREVIEW_FOOTPRINT = {height: 340};

// The edge into a candidate: dashed, since its wrangle has not been accepted
const PROVISIONAL_EDGE_STYLE = {stroke: "#7c3aed", strokeDasharray: "6 4"};

// The wrangles joining graph nodes, drawn heavier than React Flow's 1px so the tree reads at a glance
export const TREE_EDGE_WIDTH = 2.5;

// Gaps between siblings, between ranks, and between edges sharing a rank. Ranks get the most room:
// that is where the edge labels sit, and where the magnifier's readout hangs.
const NODE_SEPARATION = 50;
const RANK_SEPARATION = 80;
const EDGE_SEPARATION = 14;

/* Roughly how wide an edge label renders, so dagre can reserve space for it. A label is the bare
   operation - "impute", "delete" - with its columns in the edge's hover detail, so it stays short. */
const EDGE_LABEL_HEIGHT = 20;
const EDGE_LABEL_CHAR_WIDTH = 7;
const MIN_EDGE_LABEL_WIDTH = 44;

/* Nodes we build ourselves keep the type they were built with: a collapsed placeholder stands in for a run,
   and a prospective node is a staged wrangle, with its preview and its Accept and Decline. Everything else is
   a node the server sent, which the layout types. */
const PRESERVED_TYPES = new Set(["collapsedNode", "prospectiveNode"]);

// No branch picked out of the graph yet. Shared, so it is frozen: a branch is only ever replaced, never edited.
const EMPTY_BRANCH = Object.freeze({source: null, target: null, destination: null});

const edgeLabelSize = (label) => ({
    width: Math.max(MIN_EDGE_LABEL_WIDTH, String(label ?? "").length * EDGE_LABEL_CHAR_WIDTH),
    height: EDGE_LABEL_HEIGHT,
    labelpos: "c",
});

const labelWidthOf = (edge) => edgeLabelSize(edge.label).width;


const nodeTypes = {
    noteNode: NoteNode,
    rootNoteNode:  RootNoteNode,
    collapsedNode: CollapsedNode,
    prospectiveNode: ProspectiveNode,
    // Analysis mode's simple view draws every node as one of these
    analysisNode: AnalysisDotNode,
    // Every kind of supporting sub-node, beside its host - see graph_objects/supportNodes/registry.js
    supportNode: SupportNode,
    // The boundary around a node and its sub-nodes
    supportGroup: SupportGroup,
    // Where a sub-node dragged in from the Quality panel is dropped, only while one is being dragged
    supportDropZone: SupportDropZone,
};

/* What the graph draws until the server's graph arrives: the current table, alone, as the root */
function placeholderNodes(tableName) {
    return [{id: tableName, position: {x: 0, y: 0}, data: {label: tableName}, type: "rootNoteNode"}];
}

const isPreserved = (node) => PRESERVED_TYPES.has(node.type);

/* Types a node the server sent: a candidate - a provisional node - is drawn as a prospective node, as tall as
   its preview chart needs; anything else as a plain card. */
function typeServerNode(node) {
    if (node.data?.provisional) {
        node.type = "prospectiveNode";
        node.data.footprint = PREVIEW_FOOTPRINT;
    } else {
        node.type = "noteNode";
    }
}

/* The size dagre is told a node is: its card, or taller for a node that draws taller than a card - a repair
   candidate with its preview chart says so in its footprint - widened by any room reserved for its sub-nodes. */
function layoutSizeOf(node, room) {
    const height = node.data?.footprint?.height ?? nodeHeight;
    if (!room) {
        return {width: nodeWidth, height};
    }
    return {width: nodeWidth + room.left + room.right, height: Math.max(height, room.height)};
}

/* What dagre is told an edge's label is. Passing the label's size makes dagre lay the graph out around the
   labels rather than letting sibling branches print theirs on top of one another. When a sub-node sits beside
   the edge, the "label" is that sub-node's room instead, set to one side of the edge's own label. */
function layoutLabelOf(edge, room) {
    const label = edgeLabelSize(edge.label);
    if (!room) {
        return label;
    }
    const labelpos = room.side === "left" ? "l" : "r";
    return {width: room.width, height: room.height, labelpos, labeloffset: label.width / 2 + EDGE_GAP};
}

/* The server sends type "edgeType", which is not a registered edge type - React Flow silently
   falls back to its bezier default. Name that default outright so the curve is a choice rather
   than a fallback, and so it cannot change under us. */
function styleTreeEdge(edge) {
    // An edge into a candidate is dashed and does not animate: its wrangle has not been accepted yet
    const provisional = Boolean(edge.data?.provisional);
    const provisionalStyle = provisional ? PROVISIONAL_EDGE_STYLE : {};

    const styled = {
        ...edge,
        type: "default",
        style: {...edge.style, ...provisionalStyle, strokeWidth: TREE_EDGE_WIDTH},
    };
    if (provisional) {
        styled.animated = false;
    }
    return styled;
}

/* `reserve` is the room, by node id, that a node's supporting sub-nodes need on its left and right (see
   sideReserve). Dagre is told that node is that much wider, so its neighbours keep clear, and the card is
   placed inside the wider slot with the room either side of it.

   `edgeRoom` is the room, by target node id, that a sub-node beside that node's incoming edge needs (see
   edgeReserve). Dagre is told the edge's label is that size and sits to its right, clear of the edge's own
   label - which also opens the gap between the two ranks to its height.

   Writes each node's type, and a candidate's footprint, onto the nodes it is handed. */
const getLayoutedElements = (nodes, edges, direction = 'TB', {reserve = new Map(), edgeRoom = new Map()} = {}) => {
    if (!nodes || nodes.length === 0) return {nodes: [], edges: edges || []};

    const isHorizontal = direction === 'LR';
    const dagreGraph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
    dagreGraph.setGraph({
        rankdir: direction,
        nodesep: NODE_SEPARATION,
        ranksep: RANK_SEPARATION,
        edgesep: EDGE_SEPARATION,
    });

    for (const node of nodes) {
        if (!isPreserved(node)) {
            typeServerNode(node);
        }
        dagreGraph.setNode(node.id, layoutSizeOf(node, reserve.get(node.id)));
    }

    // Find the root by its parent rather than by position: collapsing hands us a filtered list, in
    // which the root is not necessarily first
    const rootNode = nodes.find((node) => node.data.parent === "root") || nodes[0];
    // The || nodes[0] fallback can land on anything, so guard the write as well as the search -
    // otherwise a render with no root would promote a prospective node into the root's shape
    if (rootNode && !isPreserved(rootNode)) rootNode.type = "rootNoteNode"

    for (const edge of edges) {
        dagreGraph.setEdge(edge.source, edge.target, layoutLabelOf(edge, edgeRoom.get(edge.target)));
    }

    dagre.layout(dagreGraph);

    const newNodes = nodes.map((node) => {
        const laidOut = dagreGraph.node(node.id);
        // The card sits after any room reserved on its left
        const leftRoom = reserve.get(node.id)?.left ?? 0;
        const height = node.data?.footprint?.height ?? nodeHeight;
        return {
            ...node,
            targetPosition: isHorizontal ? 'left' : 'top',
            sourcePosition: isHorizontal ? 'right' : 'bottom',
            position: {
                x: laidOut.x - laidOut.width / 2 + leftRoom,
                y: laidOut.y - height / 2,
            },
        };
    });

    const newEdges = edges.map(styleTreeEdge);

    return {nodes: newNodes, edges: newEdges};
};

/* Lays the folded graph out as a tree, then places the supporting sub-nodes beside it.

   Sub-nodes stay out of dagre: it only reserves room beside each host or edge, and they are placed in that
   room afterwards. They go on the side their host's branch leans to - left for a left child - and which side
   that is only shows once the tree is laid out. So with any to place, the bare tree is laid out once to see
   where each host lands, and again with each one's room reserved on that side.

   Returns the tree's nodes and edges, and supportPlacement: the sub-nodes and their links, as
   placeSupportNodes gives them. */
function layoutWithSupport(folded, supported) {
    /* Laying out writes onto the nodes it is handed, and applyCollapse hands back the server's own node
       objects when nothing is folded - so every layout gets copies. */
    function layoutTree(reserve, edgeRoom) {
        const nodeCopies = folded.nodes.map((node) => ({...node, data: {...node.data}}));
        const edgeCopies = [...folded.edges];
        return getLayoutedElements(nodeCopies, edgeCopies, 'TB', {reserve, edgeRoom});
    }

    const bareLayout = layoutTree(new Map(), new Map());
    const sides = branchSides(supported, bareLayout.nodes, bareLayout.edges);

    let layout = bareLayout;
    if (supported.length > 0) {
        layout = layoutTree(sideReserve(supported, sides), edgeReserve(supported, sides));
    }

    // Edge sub-nodes follow the drawn edge rather than dagre's, so groups can still crowd; move them apart
    const treeNodes = spreadSupportGroups(supported, layout.nodes, layout.edges, labelWidthOf, sides);
    const supportPlacement = placeSupportNodes(supported, treeNodes, layout.edges, labelWidthOf, sides);

    return {treeNodes, treeEdges: layout.edges, supportPlacement};
}

/* The nodes to draw, each keeping the size React Flow measured it at last time.

   The layout builds every node afresh, and React Flow treats one that arrives without a measured size as never
   measured: it hides it, drops its handles - so its edges vanish too - and waits for a fresh measurement, which
   a node whose size did not change may never get. Declining one candidate would hide its siblings that way,
   until something else redrew the graph. A node whose size does change is measured again regardless, since
   React Flow keeps watching its element. */
function keepMeasuredSizes(current, drawn) {
    const measuredSizes = new Map();
    for (const node of current) {
        if (node.measured) measuredSizes.set(node.id, node.measured);
    }

    return drawn.map((node) => {
        const measured = measuredSizes.get(node.id);
        if (!measured) return node;
        return {...node, measured};
    });
}

/* The tree's drawn nodes, split into the accepted ones and the candidates. A folded run's placeholder is
   neither: it is a way of looking at nodes already drawn. */
function splitDrawnNodes(treeNodes) {
    const acceptedNodes = [];
    const candidateNodes = [];
    for (const node of treeNodes) {
        if (node.type === "prospectiveNode") {
            candidateNodes.push(node);
        } else if (node.type !== "collapsedNode") {
            acceptedNodes.push(node);
        }
    }
    return {acceptedNodes, candidateNodes};
}

/* What the view should move to after a draw, by id - empty when nothing new arrived. An accepted node is new
   once ever, including a candidate the moment it is accepted; a candidate is new whenever it was not drawn
   just before. The focus is each new node, or the node new candidates hang from, together with all of that
   node's candidates. */
function newFocusIds(acceptedNodes, candidateNodes, seenNodeIds, previousCandidateIds) {
    const anchors = new Set();
    for (const node of acceptedNodes) {
        if (!seenNodeIds.has(node.id)) anchors.add(node.id);
    }
    for (const node of candidateNodes) {
        if (!previousCandidateIds.has(node.id)) anchors.add(node.data.parent);
    }
    if (anchors.size === 0) return [];

    const candidateIds = [];
    for (const node of candidateNodes) {
        if (anchors.has(node.data.parent)) candidateIds.push(node.id);
    }
    return [...anchors, ...candidateIds];
}

// Which step of picking a branch the user is on: its edge, then where it ends
function selectionStageOf(branchSelection) {
    if (!branchSelection.target) return "edge";
    if (!branchSelection.destination) return "destination";
    return "complete";
}

export function PGraphProvider({children}) {
    const {tableName, setTableName} = useTableName();
    // Opening a node's details brings the dock forward on its tab
    const {revealTab} = useDock();
    const {setRefreshKey} = useContext(ViewContext);

    const [nodes, setNodes, onNodesChange] = useNodesState(placeholderNodes(tableName));
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);

    // Selection A: the node shift-clicked to compare against the current node (selection B), or null
    const [selectionAId, setSelectionAId] = useState(null);

    /* The pair the user set up on purpose: a shift-clicked selection A against the current node as
       selection B. The graph badges it in both its modes, and the header's Compare button opens it. */
    const comparisonPair = useMemo(() => {
        const hasSelectionA = selectionAId && selectionAId !== tableName;
        if (!hasSelectionA) return null;
        return {a: selectionAId, b: tableName};
    }, [selectionAId, tableName]);

    /* The branch the user is picking out of the graph: an edge fixes where it starts and which way it
       leaves that node, a destination fixes where it stops. Both are chosen by clicking the graph. */
    const [branchSelection, setBranchSelection] = useState(EMPTY_BRANCH);
    const [branchTrajectory, setBranchTrajectory] = useState(null);
    const [branchTrajectoryLoading, setBranchTrajectoryLoading] = useState(false);

    const selectionStage = selectionStageOf(branchSelection);

    const startBranchSelection = useCallback(() => {
        setBranchSelection(EMPTY_BRANCH);
        revealTab("quality");
    }, [revealTab]);

    const resetBranchSelection = useCallback(() => {
        setBranchSelection(EMPTY_BRANCH);
    }, []);

    /* Clears every selection the graph holds at once - the comparison's selection A and the branch alike.
       They are picked with overlapping gestures (shift-click, click, edge click), so a single way out
       matters more than being able to clear them individually. */
    const clearAllSelections = useCallback(() => {
        setSelectionAId(null);
        setBranchSelection(EMPTY_BRANCH);
    }, []);

    const hasAnySelection = Boolean(selectionAId || branchSelection.target);

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

    /* Where the branch is allowed to end: the chosen edge's target and everything below it, a candidate
       included - it is a node of the graph like any other. Links out to supporting sub-nodes are not walked.
       Computed here from the edges the UI already holds, so the graph can show which nodes are pickable
       without a round trip. The server validates the choice independently. */
    const eligibleDestinations = useMemo(() => {
        if (!branchSelection.target) return new Set();
        return new Set(descendantsOf(treeEdgesOf(edges), branchSelection.target));
    }, [edges, branchSelection.target]);

    /* Fetching lives here rather than in the panel because the graph needs the result too - it lights
       up the branch's edges. Syncing to the server when the selection changes is what effects are for. */
    useEffect(() => {
        let stale = false;

        async function fetchTrajectory() {
            const {source, target, destination} = branchSelection;
            if (!source || !target || !destination) {
                setBranchTrajectory(null);
                // A request for the previous selection may still be out; its reply is dropped, so it cannot
                // end the loading state itself
                setBranchTrajectoryLoading(false);
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

    /* How the graph is laid out. "wrangling" is the tree; "analysis" plots every node on drift from root
       against its error - analysisMetric names which error - drawn as dots ("simple") or as the full
       cards ("full"). Like collapsing, a way of looking at the graph: the tree layout underneath is
       never touched, so switching back puts every node where it was. */
    const [graphMode, setGraphMode] = useState("wrangling");
    const [analysisStyle, setAnalysisStyle] = useState("full");
    const [analysisMetric, setAnalysisMetric] = useState("total");

    /* The supporting sub-nodes hung beside nodes, and the modal that adds them. Their records live here
       for the same reason: the effect below draws them. */
    const support = useSupportNodes();
    const {supportNodes, isSupportShown} = support;

    /* Where the view should go next: whenever new nodes appear - the node a wrangle made, or a set of
       prospective nodes - the graph recentres on that node and its prospective children rather than leaving
       them wherever they landed. {ids, key}, a new key per request, so a request is taken once (takeFocus)
       even by a graph view that a wrangle has remounted since. Worked out here because the view's own state
       does not survive that remount. */
    const [focus, setFocus] = useState({ids: [], key: 0});
    const takenFocusKey = useRef(0);
    const takeFocus = useCallback((key) => {
        if (key === takenFocusKey.current) return false;
        takenFocusKey.current = key;
        return true;
    }, []);
    // Every accepted node drawn so far, so a folded run expanding again is not mistaken for new nodes
    const seenNodeIds = useRef(new Set());
    // The candidates drawn last time, so new ones can be told from those already on the graph
    const drawnCandidateIds = useRef(new Set());

    /* Fold the nodes the user lassoed. Rejects anything that is not one unbroken run on a single
       branch, because collapsing through a fork would orphan the sibling subtree. */
    const collapseNodes = useCallback((selectedIds) => {
        // A lasso catches whatever is under it, sub-nodes included; they are not part of the run being
        // folded, so drop them before the run is validated. A host's links out to its sub-nodes would read
        // as a fork, so the run is judged on the tree's own edges. A candidate is a node like any other.
        const run = orderCollapsibleRun(
            treeEdgesOf(edges),
            selectedIds.filter((id) => !isSupportId(id)),
        );
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
       expanding restores the real nodes without another request. pareto rides along: which leaves another
       leaf beats outright on error and drift together, worked out on the server - see PGraph.pareto */
    const [serverGraph, setServerGraph] = useState({nodes: [], edges: [], pareto: null});

    /* Every real node by id, whether or not it is drawn. A node folded into a run is gone from
       `nodes`, but anything describing it - the compare modal, say - still needs its data. */
    const serverNodesById = useMemo(
        () => Object.fromEntries(serverGraph.nodes.map((node) => [node.id, node])),
        [serverGraph]
    );

    /* Candidates: wrangles staged as provisional nodes - a repair of the user's selection, or one the AI
       suggested - see app/server_utils/candidates.py. Each is a node of the graph like any other, sent with
       the rest; the one thing not allowed is wrangling from it, until it is accepted. */
    const candidates = useMemo(() => serverGraph.nodes.filter((node) => node.data?.provisional), [serverGraph]);
    const candidateIds = useMemo(() => new Set(candidates.map((node) => node.id)), [candidates]);
    const isCandidate = useCallback((id) => candidateIds.has(id), [candidateIds]);
    // Whether the session is on a candidate, which nothing may be wrangled from
    const currentIsCandidate = candidateIds.has(tableName);

    /* A run the user folded keeps the ids it was made from. A candidate in one may since have been declined -
       always as the run's last node, since nothing hangs off a candidate - so a run is read without ids the
       graph no longer has, and one left too short to fold is let go. */
    const liveRuns = useMemo(() => {
        const present = new Set(serverGraph.nodes.map((node) => node.id));
        return collapsedRuns
            .map((run) => ({...run, nodes: run.nodes.filter((id) => present.has(id))}))
            .filter((run) => run.nodes.length >= 2);
    }, [collapsedRuns, serverGraph]);

    /* Fold the server's graph into what React Flow should draw, and write it into React Flow's own
       state rather than deriving it alongside.

       This has to be the state React Flow owns. It reports each node's measured size back through
       onNodesChange, and a node missing from that state never receives its dimensions - React Flow
       then keeps it permanently invisible while still laying out around it. */
    useEffect(() => {
        if (serverGraph.nodes.length === 0) return;

        const folded = applyCollapse(serverGraph.nodes, serverGraph.edges, liveRuns);
        const visible = new Set(folded.nodes.map((node) => node.id));
        /* Only a host that is drawn gets its sub-nodes - one folded into a run keeps its records for when it is
           expanded - and hidden ones reserve no room either, so hiding them lets the tree close up. */
        const supported = supportNodes.filter((record) => visible.has(record.hostId) && isSupportShown(record));
        const {treeNodes, treeEdges, supportPlacement} = layoutWithSupport(folded, supported);

        // The tree first, since React Flow needs every host ahead of the sub-nodes it parents
        const drawnNodes = [...treeNodes, ...supportPlacement.nodes];
        setNodes((current) => keepMeasuredSizes(current, drawnNodes));
        setEdges([...treeEdges, ...supportPlacement.edges]);

        /* The graph's first draw is the whole graph, which the view fits anyway, so it only records what
           was drawn. */
        const {acceptedNodes, candidateNodes} = splitDrawnNodes(treeNodes);
        const firstDraw = seenNodeIds.current.size === 0;
        const focusIds = newFocusIds(acceptedNodes, candidateNodes, seenNodeIds.current, drawnCandidateIds.current);
        acceptedNodes.forEach((node) => seenNodeIds.current.add(node.id));
        drawnCandidateIds.current = new Set(candidateNodes.map((node) => node.id));

        if (!firstDraw && focusIds.length > 0) {
            setFocus((current) => ({ids: focusIds, key: current.key + 1}));
        }
    }, [serverGraph, liveRuns, supportNodes, isSupportShown, setNodes, setEdges]);

    // The edges making up the selected branch, keyed "source->target", for highlighting in the graph
    const selectedBranchEdges = useMemo(() => {
        const path = branchTrajectory?.nodes ?? [];
        const keys = new Set();
        for (let step = 0; step < path.length - 1; step++) {
            keys.add(`${path[step]}->${path[step + 1]}`);
        }
        return keys;
    }, [branchTrajectory]);

    /* Take a graph the server sent. Every node's label - n2b, or a candidate's c7 - is registered before the
       graph is, so anything that names a node by nodeName reads the new labels on the render that follows. */
    const receiveGraph = useCallback((result) => {
        setNodeLabels(new Map(result.nodes.map((node) => [node.id, node.data?.label ?? node.id])));
        setServerGraph({nodes: result.nodes, edges: result.edges, pareto: result.pareto});
    }, []);

    // Pull the graph from the server and re-layout it. Every path that mutates the graph - executing a
    // wrangle, undo, redo - has to call this, or the rendered graph drifts from the real one.
    const refreshGraph = useCallback(async () => {
        const pGraphResult = await getPGraph();
        if (!pGraphResult?.nodes) return;

        // Folding and layout happen in the effect above, so both paths into the graph agree
        receiveGraph(pGraphResult);
    }, [receiveGraph]);

    /* Pull the graph as soon as there is a table to pull it for. Until it arrives the placeholder node is
       drawn and serverGraph is empty - and the effect that draws the graph waits on it, as does anything
       derived from the real graph, the AI's suggestions among them. */
    useEffect(() => {
        if (!tableName) return;

        // Guarded the way the trajectory fetch above is: a reply that arrives after the table
        // has moved on must not write itself into the graph
        let stale = false;
        (async () => {
            const result = await getPGraph();
            if (stale || !result?.nodes) return;
            receiveGraph(result);
        })();

        return () => { stale = true; };
    }, [tableName, receiveGraph]);

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

    /* Makes a node the current one: the server's session moves to its table and every view is pulled again.
       Double-clicking a node does this, and so does a sub-node's "Open in Plot Wrangler". */
    const navigateToNode = useCallback(
        async (nodeId) => {
            await setGraphToClickedNode(nodeId);
            setTableName(nodeId);
            /* Navigating picks a new current node, so the comparison falls back to that node's own
               parent rather than keeping a selection A chosen for somewhere else in the graph. The
               branch goes with it: React Flow fires onNodeClick on the first click of a double
               click, so without this, double-clicking a node while choosing where a branch ends
               would both end the branch there and navigate away from it. */
            clearAllSelections();
            clearScatterPlotCache();
            clearHistogramCache();
            clearHeatMapCache();
            setRefreshKey(k => k + 1);
        }, [setTableName, setRefreshKey, clearAllSelections]
    )

    // React Flow's node mouse handlers take (event, node) - see https://reactflow.dev/api-reference/types/node-mouse-handler
    const onNodeDoubleClick = useCallback(
        async (event, node) => {
            // A supporting sub-node only ever describes its host, and has no table to navigate to. A candidate
            // does: it can be made current and explored, though nothing can be wrangled from it until accepted
            if (isSupportId(node.id)) return;
            await navigateToNode(node.id);
        }, [navigateToNode]
    )

    /* Shift-click re-targets selection A. A plain click ends a branch that is mid-selection,
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
            // A supporting sub-node cannot be selection A; a candidate can, to compare it before accepting it
            if (isSupportId(node.id)) return;
            setSelectionAId(current => (current === node.id ? null : node.id));
        }, [selectionStage, eligibleDestinations, pickBranchDestination]
    )

    /* Clicking an edge starts a branch there. Allowed at any stage so the branch can be re-aimed
       without resetting first. */
    const onEdgeClick = useCallback(
        (event, edge) => {
            event.stopPropagation();
            // A link out to a sub-node is not a wrangle, so no branch runs along it
            if (isSupportId(edge.target)) return;
            pickBranchEdge(edge.source, edge.target);
            revealTab("quality");
        }, [pickBranchEdge, revealTab]
    )

    return (
        <PGraphContext.Provider value={{
            nodes,
            edges,
            nodeTypes,
            onNodesChange, onEdgesChange, onConnect, navigateToNode,
            onNodeDoubleClick, onNodeClick, onEdgeClick,
            comparisonPair, serverNodesById,
            pareto: serverGraph.pareto,
            branchSelection, selectionStage, eligibleDestinations, selectedBranchEdges,
            // Staged wrangles, as nodes of the graph - see CandidatesContext for accepting and declining them
            candidates, isCandidate, currentIsCandidate,
            // supportNodes, add/update/removeSupportNode, supportModalHost, open/closeSupportModal
            ...support,
            startBranchSelection, resetBranchSelection,
            clearAllSelections, hasAnySelection,
            collapsedRuns, collapseNodes, expandRun, expandAllRuns, selectRunBranch,
            graphMode, setGraphMode, analysisStyle, setAnalysisStyle, analysisMetric, setAnalysisMetric,
            collapseError, setCollapseError,
            branchTrajectory, branchTrajectoryLoading,
            refreshGraph,
            focus, takeFocus,
        }}>
            {children}
        </PGraphContext.Provider>
    );
}

export function usePgraph() {
    return useContext(PGraphContext);
}
