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
import {SelectionContext} from "./SelectionContext.jsx";
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
import "../styles/Nodes.css"


export const PGraphContext = createContext(null);

const dagreGraph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

/* The footprint dagre reserves per node. This has to track what the nodes actually measure in
   Nodes.css - min-width 150px plus padding, border, the label and the icon row, and the comparison
   badge that floats above them - because dagre packs the graph to whatever size it is told. The old
   100x75 was smaller than a rendered node, which is why they crowded. */
const nodeWidth = 200;
const nodeHeight = 100;

/* A candidate draws its preview chart, so it is about three cards tall: its title, rows and reason, the chart,
   its buttons and the node tools. Dagre reserves that, so the chart does not run into the rank below. */
const PREVIEW_FOOTPRINT = {height: 340};

// The edge into a candidate: dashed, since its wrangle has not been accepted
const PROVISIONAL_EDGE_STYLE = {stroke: "#7c3aed", strokeDasharray: "6 4"};

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

/* `reserve` is the room, by node id, that a node's supporting sub-nodes need on its left and right (see
   sideReserve). Dagre is told that node is that much wider, so its neighbours keep clear, and the card is
   placed inside the wider slot with the room either side of it.

   `edgeRoom` is the room, by target node id, that a sub-node beside that node's incoming edge needs (see
   edgeReserve). Dagre is told the edge's label is that size and sits to its right, clear of the edge's own
   label - which also opens the gap between the two ranks to its height. */
const getLayoutedElements = (nodes, edges, direction = 'TB', {reserve = new Map(), edgeRoom = new Map()} = {}) => {
    const isHorizontal = direction === 'LR';
    const dagreGraph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

    if (!nodes || nodes.length === 0) return {nodes: [], edges: edges || []};

    dagreGraph.setGraph({
        rankdir: direction,
        nodesep: NODE_SEPARATION,
        ranksep: RANK_SEPARATION,
        edgesep: EDGE_SEPARATION,
    });

    /* Nodes we build ourselves keep the type they were built with. Everything else is a node the server
       sent, which is typed below. A collapsed placeholder stands in for a run; a candidate is drawn as a
       prospective node - a staged wrangle, with its preview and its Accept and Decline. Labels are the server's
       own short ones - n0b, c7 - so they need no shortening. */
    const PRESERVED_TYPES = new Set(["collapsedNode", "prospectiveNode"]);
    const isPreserved = (node) => PRESERVED_TYPES.has(node.type);

    nodes.forEach((node) => {
        if (!isPreserved(node)) {
            node.type = node.data?.provisional ? "prospectiveNode" : "noteNode";
            if (node.data?.provisional) node.data.footprint = PREVIEW_FOOTPRINT;
        }
        // A node that draws taller than a card - a repair candidate with its preview chart - says so
        const height = node.data?.footprint?.height ?? nodeHeight;
        const room = reserve.get(node.id);
        dagreGraph.setNode(node.id, room
            ? {width: nodeWidth + room.left + room.right, height: Math.max(height, room.height)}
            : {width: nodeWidth, height});
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
        const label = edgeLabelSize(edge.label);
        const room = edgeRoom.get(edge.target);
        dagreGraph.setEdge(edge.source, edge.target, room
            ? {width: room.width, height: room.height, labelpos: room.side === "left" ? "l" : "r",
               labeloffset: label.width / 2 + EDGE_GAP}
            : label);
    });

    dagre.layout(dagreGraph);

    const newNodes = nodes.map((node) => {
        const nodeWithPosition = dagreGraph.node(node.id);
        return {
            ...node,
            targetPosition: isHorizontal ? 'left' : 'top',
            sourcePosition: isHorizontal ? 'right' : 'bottom',
            position: {
                // The card sits after any room reserved on its left
                x: nodeWithPosition.x - nodeWithPosition.width / 2 + (reserve.get(node.id)?.left ?? 0),
                y: nodeWithPosition.y - (node.data?.footprint?.height ?? nodeHeight) / 2,
            },

        };
    });

    /* The server sends type "edgeType", which is not a registered edge type - React Flow silently
       falls back to its bezier default. Name that default outright so the curve is a choice rather
       than a fallback, and so it cannot change under us. */
    const newEdges = edges.map((edge) => ({
        ...edge,
        type: "default",
        // An edge into a candidate is dashed and does not animate: its wrangle has not been accepted yet
        ...(edge.data?.provisional ? {animated: false} : {}),
        style: {...edge.style, ...(edge.data?.provisional ? PROVISIONAL_EDGE_STYLE : {}), strokeWidth: TREE_EDGE_WIDTH},
    }));

    return {nodes: newNodes, edges: newEdges};
};

// The wrangles joining graph nodes, drawn heavier than React Flow's 1px so the tree reads at a glance
export const TREE_EDGE_WIDTH = 2.5;

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

    // Selection A: the node shift-clicked to compare against the current node (selection B), or null
    const [selectionAId, setSelectionAId] = useState(null);

    /* The pair the user set up on purpose: a shift-clicked selection A against the current node as
       selection B. The graph badges it in both its modes, and the header's Compare button opens it. */
    const comparisonPair = useMemo(() => (
        (selectionAId && selectionAId !== tableName)
            ? {a: selectionAId, b: tableName}
            : null
    ), [selectionAId, tableName]);

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

    /* Clears every selection the graph holds at once - the comparison's selection A and the branch alike.
       They are picked with overlapping gestures (shift-click, click, edge click), so a single way out
       matters more than being able to clear them individually. */
    const clearAllSelections = useCallback(() => {
        setSelectionAId(null);
        setBranchSelection({source: null, target: null, destination: null});
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

    /* Where the branch is allowed to end: the chosen edge's target and everything below it. Computed
       here from the edges the UI already holds, so the graph can show which nodes are pickable
       without a round trip. The server validates the choice independently. */
    /* Anywhere below the start edge, a candidate included - it is a node of the graph like any other. Links
       out to supporting sub-nodes are not walked at all. */
    const eligibleDestinations = useMemo(
        () => (branchSelection.target
            ? new Set(descendantsOf(treeEdgesOf(edges), branchSelection.target))
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
    // Every real node drawn so far, so a folded run expanding again is not mistaken for new nodes
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
       expanding restores the real nodes without another request. */
    /* pareto rides along: which leaves another leaf beats outright on error and drift together, worked
       out on the server - see PGraph.pareto */
    const [serverGraph, setServerGraph] = useState({nodes: [], edges: [], pareto: null, comparisons: []});

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

        function drawGraph() {
            const folded = applyCollapse(serverGraph.nodes, serverGraph.edges, liveRuns);
            const visible = new Set(folded.nodes.map((node) => node.id));
            /* applyCollapse hands back the server's own node objects by reference when nothing is
               folded, and laying out writes type and label onto whatever it is given - so build a
               new array rather than pushing onto that one. */
            /* Supporting sub-nodes stay out of dagre: it only reserves room beside each host or edge, and
               they are placed in that room afterwards. Only a host that is drawn gets them - one folded into
               a run keeps its records for when it is expanded - and hidden ones reserve no room either, so
               hiding them lets the tree close up. */
            const supported = supportNodes.filter((record) => visible.has(record.hostId) && isSupportShown(record));
            const lay = (reserve, edgeRoom) => getLayoutedElements(
                folded.nodes.map((node) => ({...node, data: {...node.data}})),
                [...folded.edges],
                'TB',
                {reserve, edgeRoom},
            );
            /* Sub-nodes go on the side their host's branch leans to - left for a left child - and which side that
               is only shows once the tree is laid out. So with any to place, the bare tree is laid out once to see
               where each host lands, and again with each one's room reserved on that side. */
            const first = lay(new Map(), new Map());
            const sides = branchSides(supported, first.nodes, first.edges);
            const layout = supported.length
                ? lay(sideReserve(supported, sides), edgeReserve(supported, sides))
                : first;
            const labelWidthOf = (edge) => edgeLabelSize(edge.label).width;
            // Edge sub-nodes follow the drawn edge rather than dagre's, so groups can still crowd; move them apart
            const treeNodes = spreadSupportGroups(supported, layout.nodes, layout.edges, labelWidthOf, sides);
            const beside = placeSupportNodes(supported, treeNodes, layout.edges, labelWidthOf, sides);
            // After the tree, since React Flow needs every host ahead of the sub-nodes it parents
            setNodes([...treeNodes, ...beside.nodes]);
            setEdges([...layout.edges, ...beside.edges]);

            /* What arrived with this draw. An accepted node is new once ever - including a candidate the moment
               it is accepted; a candidate whenever it was not drawn just before. A folded run's placeholder is a
               way of looking at nodes already seen. The graph's first draw is the whole graph, which the view
               fits anyway, so it only records. */
            const isStaged = (node) => node.type === "prospectiveNode";
            const real = treeNodes.filter((node) => !isStaged(node) && node.type !== "collapsedNode");
            const staged = treeNodes.filter(isStaged);
            const firstDraw = seenNodeIds.current.size === 0;
            const newReal = real.filter((node) => !seenNodeIds.current.has(node.id)).map((node) => node.id);
            const newStaged = staged.filter((node) => !drawnCandidateIds.current.has(node.id));
            real.forEach((node) => seenNodeIds.current.add(node.id));
            drawnCandidateIds.current = new Set(staged.map((node) => node.id));

            // The node in focus: a new node, or the one new candidates hang from - with its candidates
            const anchors = new Set([...newReal, ...newStaged.map((node) => node.data.parent)]);
            if (!firstDraw && anchors.size > 0) {
                const children = staged.filter((node) => anchors.has(node.data.parent)).map((node) => node.id);
                setFocus((current) => ({ids: [...anchors, ...children], key: current.key + 1}));
            }
        }

        drawGraph();
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
        setServerGraph({nodes: result.nodes, edges: result.edges, pareto: result.pareto,
            comparisons: result.comparisons ?? []});
    }, []);

    // Pull the graph from the server and re-layout it. Every path that mutates the graph - executing a
    // wrangle, undo, redo - has to call this, or the rendered graph drifts from the real one.
    const refreshGraph = useCallback(async () => {
        const pGraphResult = await getPGraph();
        if (!pGraphResult?.nodes) return;

        // Folding and layout happen in the effect above, so both paths into the graph agree
        receiveGraph(pGraphResult);
    }, [receiveGraph]);

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

    const onLayout = useCallback(
        (direction) => {
            const {nodes: ln, edges: le} = getLayoutedElements(nodes, edges, direction);
            setNodes([...ln]);
            setEdges([...le]);
        },
        [nodes, edges, setNodes, setEdges],
    );

    /* https://reactflow.dev/api-reference/types/node-mouse-handler - this is how you know the params */
    /* Makes a node the current one: the server's session moves to its table and every view is pulled again.
       Double-clicking a node does this, and so does a sub-node's "Open in Plot Wrangler". */
    const navigateToNode = useCallback(
        async (nodeId) => {
            //setTableName is a dependency you have to list for this to work
            await setGraphToClickedNode(nodeId);
            setTableName(nodeId);
            /* Navigating picks a new current node, so the comparison falls back to that node's own
               parent rather than keeping a selection A chosen for somewhere else in the graph. The
               branch goes with it: React Flow fires onNodeClick on the first click of a double
               click, so without this, double-clicking a node while choosing where a branch ends
               would both end the branch there and navigate away from it. */
            clearAllSelections();
            // clearHighlight();
            clearScatterPlotCache();
            clearHistogramCache();
            clearHeatMapCache();
            viewContext.setRefreshKey(k => k + 1);
        }, [setTableName, viewContext, clearAllSelections]
    )

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
            nodes, setNodes,
            edges, setEdges,
            nodeTypes,
            onNodesChange, onEdgesChange, onConnect, onLayout, navigateToNode,
            getLayoutedElements, onNodeDoubleClick, onNodeClick, onEdgeClick,
            selectionAId, setSelectionAId, comparisonPair, serverNodesById,
            pareto: serverGraph.pareto,
            // The comparisons saved on the graph, each a comparison object - see utils/comparisonSpec.js
            comparisons: serverGraph.comparisons,
            branchSelection, selectionStage, eligibleDestinations, selectedBranchEdges,
            // Staged wrangles, as nodes of the graph - see CandidatesContext for accepting and declining them
            candidates, isCandidate, currentIsCandidate,
            hasCandidates: candidates.length > 0,
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