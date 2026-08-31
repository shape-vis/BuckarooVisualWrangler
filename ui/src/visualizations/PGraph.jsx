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
import {useTableName} from "../store/TableNameContext.jsx";
import {showTooltip, moveTooltip, hideTooltip} from "../utils/visCommon.jsx";
import {useCallback, useMemo} from "react";


export default function PGraph() {

const { nodes, edges, onNodesChange, onEdgesChange, onConnect, onNodeDoubleClick, onNodeClick,
        onEdgeClick, nodeTypes, baselineNodeId,
        selectionStage, eligibleDestinations, selectedBranchEdges,
        clearAllSelections, hasAnySelection } = usePgraph();

const { tableName } = useTableName();
// const [showNote, setShowNote] = useState(false);

// Derived on every render rather than written once into node.style, so the marks follow navigation
// instead of going stale after mount.
const styledNodes = useMemo(() => {
    // Only a comparison the user set up with shift-click is signposted. The panel also falls back to
    // comparing against the parent, but that default is between adjacent nodes and needs no marking -
    // labelling it would badge a lone root node that has nothing to compare against.
    const comparisonBaselineId = (baselineNodeId && baselineNodeId !== tableName) ? baselineNodeId : null;

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
}, [nodes, tableName, baselineNodeId, selectionStage, eligibleDestinations]);


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

  return (
    <div className="pgraph-container">
      <ReactFlow
        colorMode={"light"}
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
        /* Shift is the baseline-picking modifier, so it must not also start a selection box */
        selectionKeyCode={null}
      >
        {/* The selections are made by clicking the graph, so the way out of them belongs here too */}
        {hasAnySelection && (
          <Panel position="top-right">
            <button
              className="pgraph-clear-selections"
              onClick={clearAllSelections}
              title="Clear the comparison baseline and the selected branch"
            >
              Clear selections
            </button>
          </Panel>
        )}

        <Background color="#ccc" variant={BackgroundVariant.Lines} />
        <Controls />
        {/*<MiniMap nodeStrokeWidth={3} />*/}
      </ReactFlow>
    </div>
  );
}
