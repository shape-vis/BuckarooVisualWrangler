import {
    ReactFlow,
    Background,
    Controls,
    addEdge,
    MiniMap, ConnectionLineType, Panel, BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../styles/PGraph.css";
import {usePgraph} from "../store/PGraphContext.jsx";
import {useAISuggestions} from "../store/AISuggestionsContext.jsx";
import {useTableName} from "../store/TableNameContext.jsx";
import {showTooltip, moveTooltip, hideTooltip} from "../utils/visCommon.jsx";
import {useCallback, useEffect, useMemo, useRef} from "react";


export default function PGraph() {

/* The AI's own messages: a failure, or the model reporting that it found nothing worth
   repairing. Neither is a node, so both live in the same top-center panel the collapse error
   already uses. */
const ai = useAISuggestions();

const { onNodesChange, onEdgesChange, onConnect, onNodeDoubleClick, onNodeClick,
        onEdgeClick, nodeTypes, comparisonPair,
        selectionStage, eligibleDestinations, selectedBranchEdges,
        clearAllSelections, hasAnySelection,
        nodes, edges,
        collapsedRuns, collapseNodes, expandAllRuns,
        collapseError, setCollapseError } = usePgraph();

// Which nodes the c-drag lasso currently has, read when the drag ends
const lassoed = useRef([]);

/* Folding or expanding a run re-lays the whole graph out, but fitView only runs at mount - without
   this the nodes shift under a stale viewport and can end up off-screen entirely. */
const flow = useRef(null);

useEffect(() => {
    flow.current?.fitView({duration: 300, padding: 0.2});
}, [collapsedRuns]);

const { tableName } = useTableName();
// const [showNote, setShowNote] = useState(false);

// Derived on every render rather than written once into node.style, so the marks follow navigation
// instead of going stale after mount.
const styledNodes = useMemo(() => {
    // Only a comparison the user set up with shift-click is signposted. The panel also falls back to
    // comparing against the parent, but that default is between adjacent nodes and needs no marking -
    // labelling it would badge a lone root node that has nothing to compare against.
    const comparisonBaselineId = comparisonPair?.baseline ?? null;

    // While the branch's end is being chosen, the nodes it may end on are marked as pickable
    const markEligible = selectionStage === "destination";

    return nodes.map((node) => {
        const isCurrent = node.id === tableName;
        const isBaseline = node.id === comparisonBaselineId;
        const isEligible = markEligible && eligibleDestinations.has(node.id);
        if (!isCurrent && !isBaseline && !isEligible) return node;

        const role = isCurrent ? "current" : isBaseline ? "baseline" : null;
        const classes = [
            role ? `pgraph-node--${role}` : "",
            isEligible ? "pgraph-node--eligible" : "",
        ].filter(Boolean).join(" ");

        return {
            ...node,
            className: classes,
            // The node components render a badge from this, so the pair is readable in a large graph
            data: (role && comparisonBaselineId) ? {...node.data, comparisonRole: role} : node.data,
        };
    });
}, [nodes, tableName, comparisonPair, selectionStage, eligibleDestinations]);


// The selected branch is lit up in the graph, so the trajectory in the panel is tied to a visible
// path through the tree. Edges are untouched when no branch is selected.
const styledEdges = useMemo(() => {
    if (selectedBranchEdges.size === 0) return edges;

    return edges.map((edge) => {
        if (!selectedBranchEdges.has(`${edge.source}->${edge.target}`)) return edge;

        return {...edge, style: {...edge.style, stroke: "#1877F2", strokeWidth: 3}};
    });
}, [edges, selectedBranchEdges]);

/* The edge is labelled with just the operation, so the columns it acted on live in its hover detail.
   Uses the same shared #tooltip element as every chart, so placement stays edge-aware. */
const onEdgeMouseEnter = useCallback((event, edge) => {
    const detail = edge.data?.detail;
    if (!detail) return;
    showTooltip(`<strong>${detail}</strong><br/>click to start a branch here`, event);
}, []);

const onEdgeMouseMove = useCallback((event) => moveTooltip(event), []);
const onEdgeMouseLeave = useCallback(() => hideTooltip(), []);

/* Holding "c" turns a pane drag into a lasso (selectionKeyCode below). Whatever it caught is folded
   on release, so collapsing is its own gesture and does not compete with the click handlers. */
const onSelectionChange = useCallback(({nodes: selected}) => {
    lassoed.current = selected.map((node) => node.id);
}, []);

const onSelectionEnd = useCallback(() => {
    if (lassoed.current.length > 1) collapseNodes(lassoed.current);
}, [collapseNodes]);

  return (
    <div className="pgraph-container">
      <ReactFlow
        colorMode={"light"}
        onInit={(instance) => { flow.current = instance; }}
        nodes={styledNodes}
        edges={styledEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView={true}
        connectionLineType={ConnectionLineType.SmoothStep}
        onNodeDoubleClick={onNodeDoubleClick}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        onEdgeMouseEnter={onEdgeMouseEnter}
        onEdgeMouseMove={onEdgeMouseMove}
        onEdgeMouseLeave={onEdgeMouseLeave}
        onSelectionChange={onSelectionChange}
        onSelectionEnd={onSelectionEnd}
        /* Hold "c" and drag to lasso a run to collapse. Shift is deliberately not the lasso key -
           it already re-targets the comparison baseline. */
        selectionKeyCode={"c"}
      >
        {/* The selections are made by clicking the graph, so the way out of them belongs here too */}
        {(hasAnySelection || collapsedRuns.length > 0) && (
          <Panel position="top-right" className="pgraph-actions">
            {collapsedRuns.length > 0 && (
              <button
                className="pgraph-action-button"
                onClick={expandAllRuns}
                title="Expand every collapsed run"
              >
                Expand all ({collapsedRuns.length})
              </button>
            )}
            {hasAnySelection && (
              <button
                className="pgraph-action-button"
                onClick={clearAllSelections}
                title="Clear the comparison baseline and the selected branch"
              >
                Clear selections
              </button>
            )}
          </Panel>
        )}

        {ai?.error && (
          <Panel position="top-center">
            <div className="pgraph-collapse-error" onClick={ai.dismissMessages}>
              {ai.error} <span className="pgraph-collapse-error-dismiss">dismiss</span>
            </div>
          </Panel>
        )}

        {/* Not an error and not a node: the model looked and found nothing to do */}
        {ai?.notice && !ai?.error && (
          <Panel position="top-center">
            <div className="pgraph-ai-notice" onClick={ai.dismissMessages}>
              Nothing to repair here — {ai.notice}{" "}
              <span className="pgraph-collapse-error-dismiss">dismiss</span>
            </div>
          </Panel>
        )}

        {/* Why a lasso was refused - §8(b)(iv) only allows an unbroken run on a single branch */}
        {collapseError && (
          <Panel position="top-center">
            <div className="pgraph-collapse-error" onClick={() => setCollapseError(null)}>
              {collapseError} <span className="pgraph-collapse-error-dismiss">dismiss</span>
            </div>
          </Panel>
        )}

        <Background color="#ccc" variant={BackgroundVariant.Lines} />
        <Controls />
        {/*<MiniMap nodeStrokeWidth={3} />*/}
      </ReactFlow>
    </div>
  );
}
