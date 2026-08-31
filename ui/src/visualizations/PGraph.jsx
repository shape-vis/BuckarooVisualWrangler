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
import {useMemo} from "react";


export default function PGraph() {

const { nodes, edges, onNodesChange, onEdgesChange, onConnect, onNodeDoubleClick, onNodeClick, nodeTypes, baselineNodeId, branchEdgeColors} = usePgraph();

const { tableName } = useTableName();
// const [showNote, setShowNote] = useState(false);

// Derived on every render rather than written once into node.style, so the marks follow navigation
// instead of going stale after mount.
const styledNodes = useMemo(() => {
    // Only a comparison the user set up with shift-click is signposted. The panel also falls back to
    // comparing against the parent, but that default is between adjacent nodes and needs no marking -
    // labelling it would badge a lone root node that has nothing to compare against.
    const comparisonBaselineId = (baselineNodeId && baselineNodeId !== tableName) ? baselineNodeId : null;

    return nodes.map((node) => {
        const isCurrent = node.id === tableName;
        const isBaseline = node.id === comparisonBaselineId;
        if (!isCurrent && !isBaseline) return node;

        const role = isCurrent ? "current" : "baseline";
        return {
            ...node,
            className: `pgraph-node--${role}`,
            // The node components render a badge from this, so the pair is readable in a large graph
            data: comparisonBaselineId ? {...node.data, comparisonRole: role} : node.data,
        };
    });
}, [nodes, tableName, baselineNodeId]);


// While a node's details are open, each branch's edges take that branch's color from the sparklines,
// so a line in the panel can be traced to a path in the tree. Untouched when nothing is open.
const styledEdges = useMemo(() => {
    if (branchEdgeColors.size === 0) return edges;

    return edges.map((edge) => {
        const color = branchEdgeColors.get(`${edge.source}->${edge.target}`);
        if (!color) return edge;

        return {...edge, style: {...edge.style, stroke: color, strokeWidth: 2.5}};
    });
}, [edges, branchEdgeColors]);

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
        /* Shift is the baseline-picking modifier, so it must not also start a selection box */
        selectionKeyCode={null}
      >
        <Background color="#ccc" variant={BackgroundVariant.Lines} />
        <Controls />
        {/*<MiniMap nodeStrokeWidth={3} />*/}
      </ReactFlow>
    </div>
  );
}
