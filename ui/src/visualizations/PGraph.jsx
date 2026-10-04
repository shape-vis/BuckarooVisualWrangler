import {
    ReactFlow,
    Background,
    Controls,
    addEdge,
    MiniMap, ConnectionLineType, Panel, BackgroundVariant, MarkerType, useReactFlow, useStore,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../styles/PGraph.css";
import {usePgraph} from "../store/PGraphContext.jsx";
import {useAISuggestions} from "../store/AISuggestionsContext.jsx";
import {useTableName} from "../store/TableNameContext.jsx";
import {showTooltip, moveTooltip, hideTooltip} from "../utils/visCommon.jsx";
import {nodeName} from "../utils/comparison.js";
import AnalysisAxes from "./AnalysisAxes.jsx";
import AnalysisInset from "./AnalysisInset.jsx";
import AnalysisEdge from "../graph_objects/AnalysisEdge.jsx";
import {
    ANALYSIS_METRICS, DOT, METRIC_LABELS, ROOT_COLOR, plotFitPadding,
    analysisPositions, analysisScales, analysisTooltip, branchColors, driftOf, errorOf, isPlotted,
} from "./analysisLayout.js";
import {useCallback, useEffect, useMemo, useRef, useState} from "react";

// Analysis mode's edges run straight from node to node, whichever way the child sits from its parent
const edgeTypes = {analysis: AnalysisEdge};

// How long the nodes take to glide between the tree and the plot, and how the camera follows them
const GLIDE_MS = 450;
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const FIT_PADDING = 0.15;
// A shift-drag narrower or shorter than this, in screen pixels, is taken as a click rather than a box
const MIN_BOX = 8;

// What a card measures before React Flow has - and while it is drawn as a dot, which it then measures instead
const CARD = {width: 200, height: 100};
const cardSize = (node) => (node.measured?.width > DOT * 2 ? node.measured : CARD);

/* React Flow marks a node "nopan" only while it can be dragged, and the canvas's pan and zoom take any event
   on a node without it - a double-click on a plotted node would zoom the canvas rather than reach the node,
   and navigation with it. Analysis mode's nodes cannot be dragged, so they carry the mark themselves. */
const PLOTTED_NODE_CLASS = "nopan";

/* Where every node goes for a layout: its place in the tree, or its point on the plot along with the plot's
   scales. A suggestion has no numbers, so analysis mode leaves it out - it is hidden there. */
function layoutFor(nodes, mode, style, metric, canvas) {
    if (mode !== "analysis") {
        return {positions: new Map(nodes.map((node) => [node.id, node.position])), scales: null};
    }
    const scales = analysisScales(nodes, metric, style, canvas);
    return {positions: analysisPositions(nodes, scales, metric, style), scales};
}

/* The area a layout covers, for the camera to fit: the whole plot in analysis mode, so its axes' full range is
   in view, or the tree's extent */
function boundsFor(nodes, {positions, scales}) {
    if (scales) return scales.bounds;
    const boxes = nodes.filter(isPlotted).map((node) => {
        const at = positions.get(node.id) ?? node.position;
        const {width, height} = cardSize(node);
        return [at.x, at.y, at.x + width, at.y + height];
    });
    if (!boxes.length) return null;
    const [x0, y0] = [Math.min(...boxes.map((box) => box[0])), Math.min(...boxes.map((box) => box[1]))];
    const [x1, y1] = [Math.max(...boxes.map((box) => box[2])), Math.max(...boxes.map((box) => box[3]))];
    return {x: x0, y: y0, width: x1 - x0, height: y1 - y0};
}

// Each node part of the way from one layout to another
function between(from, to, t) {
    return new Map([...to].map(([id, end]) => {
        const start = from.get(id) ?? end;
        return [id, {x: start.x + (end.x - start.x) * t, y: start.y + (end.y - start.y) * t}];
    }));
}

/* In analysis mode the plot fills the canvas, as a chart fills its frame: when the canvas changes size - the
   window resized, the dock opened beside it - the camera fits the plot to it again. Rendered inside React
   Flow, which is where the canvas's size and camera can be read. */
function FitPlotOnResize({x, y, width, height, axisLeft}) {
    const canvasWidth = useStore((state) => state.width);
    const canvasHeight = useStore((state) => state.height);
    const {fitBounds} = useReactFlow();
    useEffect(() => {
        if (!canvasWidth || !canvasHeight) return;
        fitBounds({x, y, width, height}, {padding: plotFitPadding(axisLeft), duration: 200});
    }, [canvasWidth, canvasHeight, x, y, width, height, axisLeft, fitBounds]);
    return null;
}

/* A segmented control: one choice of a few, each a button */
function Segmented({label, options, value, onChange}) {
    return (
        <div className="pgraph-segmented" role="radiogroup" aria-label={label}>
            {options.map(([id, text]) => (
                <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={value === id}
                    className={`pgraph-segment ${value === id ? "pgraph-segment--active" : ""}`}
                    onClick={() => onChange(id)}
                >
                    {text}
                </button>
            ))}
        </div>
    );
}

export default function PGraph() {

/* The AI's own messages: a failure, or the model reporting that it found nothing worth
   repairing. Neither is a node, so both live in the same top-center panel the collapse error
   already uses. */
const ai = useAISuggestions();

const { onNodesChange, onEdgesChange, onConnect, onNodeDoubleClick, onNodeClick,
        onEdgeClick, nodeTypes, comparisonPair, pareto, serverNodesById,
        selectionStage, eligibleDestinations, selectedBranchEdges,
        clearAllSelections, hasAnySelection,
        nodes, edges,
        collapsedRuns, collapseNodes, expandAllRuns,
        collapseError, setCollapseError,
        graphMode, setGraphMode, analysisStyle, setAnalysisStyle, analysisMetric, setAnalysisMetric } = usePgraph();

const analysing = graphMode === "analysis";

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

/* The leaf that beats a node outright on error and drift together, if any - see PGraph.pareto on the
   server. A folded run stands for its last node, so it takes that node's standing. */
const dominatorOf = useCallback((node) => {
    const table = node.type === "collapsedNode" ? node.data?.tail : node.id;
    return pareto?.dominated?.[table] ?? null;
}, [pareto]);

// The node's part in the comparison: the current node is selection B, a shift-clicked one selection A
const roleOf = useCallback((node) => {
    if (node.id === tableName) return "current";
    return node.id === comparisonPair?.a ? "selection-a" : null;
}, [tableName, comparisonPair]);

/* The canvas's size, which analysis mode sizes its plot from. Measured here rather than read from React Flow,
   whose size is only available inside it. */
const containerRef = useRef(null);
const [canvas, setCanvas] = useState(null);
useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
        const {width, height} = entry.contentRect;
        setCanvas((was) => (was?.width === Math.round(width) && was?.height === Math.round(height)
            ? was : {width: Math.round(width), height: Math.round(height)}));
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
}, []);

/* The detail inset's region, {x: [from, to], y: [from, to]} in drift and error, or null when there is none.
   Small wrangles on a large table barely move a node, so a session's nodes can sit on top of one another;
   shift-dragging a box around them opens an inset that draws that region enlarged, beside the plot. */
const [inset, setInset] = useState(null);

// Where every node belongs in the mode, style and error axis now chosen
const layout = useMemo(
    () => layoutFor(nodes, graphMode, analysisStyle, analysisMetric, canvas),
    [nodes, graphMode, analysisStyle, analysisMetric, canvas]);

/* Switching the mode, the node style or the error axis glides each node from where it is drawn to where it
   now belongs, while the camera fits the new layout, so the reader sees every node travel between the tree
   and its point on the plot. Started from the control that makes the change, so it can record where the
   nodes are drawn at that moment. Anything else - a drag, a new node, a re-measure - lands at once, or a
   drag would trail behind the pointer. */
const [glide, setGlide] = useState(null);
const [frameTime, setFrameTime] = useState(0);
useEffect(() => {
    if (!glide) return undefined;
    let frame = requestAnimationFrame(function step(time) {
        if (time - glide.start >= GLIDE_MS) {
            setGlide(null);
            return;
        }
        setFrameTime(time);
        frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
}, [glide]);

const shown = useMemo(() => {
    if (!glide) return layout.positions;
    const t = Math.min(Math.max((frameTime - glide.start) / GLIDE_MS, 0), 1);
    return between(glide.from, layout.positions, easeInOut(t));
}, [glide, frameTime, layout]);

const relayout = (next) => {
    const mode = next.mode ?? graphMode;
    const style = next.style ?? analysisStyle;
    const metric = next.metric ?? analysisMetric;
    if (mode === graphMode && style === analysisStyle && metric === analysisMetric) return;

    setGlide({from: shown, start: performance.now()});
    setGraphMode(mode);
    setAnalysisStyle(style);
    setAnalysisMetric(metric);
    // An inset's region is in the old error's units, and means nothing to the tree, so either change closes it
    if (mode !== graphMode || metric !== analysisMetric) setInset(null);
    const nextLayout = layoutFor(nodes, mode, style, metric, canvas);
    const bounds = boundsFor(nodes, nextLayout);
    // The plot is fitted beside its y axis, whose width follows its labels
    const padding = nextLayout.scales ? plotFitPadding(nextLayout.scales.axisLeft) : FIT_PADDING;
    if (bounds) flow.current?.fitBounds(bounds, {padding, duration: GLIDE_MS});
};

// Each node's branch colour, which its dot and the edge into it take in analysis mode
const colors = useMemo(
    () => (analysing ? branchColors(nodes, serverNodesById) : null),
    [analysing, nodes, serverNodesById]);

// Derived on every render rather than written once into node.style, so the marks follow navigation
// instead of going stale after mount.
const styledNodes = useMemo(() => {
    // Only a comparison the user set up with shift-click is signposted
    const selectionAId = comparisonPair?.a ?? null;

    // While the branch's end is being chosen, the nodes it may end on are marked as pickable
    const markEligible = selectionStage === "destination";

    return nodes.map((node) => {
        const isCurrent = node.id === tableName;
        const isSelectionA = node.id === selectionAId;
        const isEligible = markEligible && eligibleDestinations.has(node.id);
        const isDominated = Boolean(dominatorOf(node));
        const position = shown.get(node.id) ?? node.position;

        // Suggestions have no numbers, so the plot has nowhere to put them
        if (analysing && !isPlotted(node)) return {...node, hidden: true};

        const role = isCurrent ? "current" : isSelectionA ? "selection-a" : null;

        /* The simple view's dot. Its role travels in data rather than as a class: the role classes style a
           card. Root, the pair and anything chosen are named outright; the rest on hover. */
        if (analysing && analysisStyle === "simple") {
            const isRun = node.type === "collapsedNode";
            return {
                ...node,
                type: "analysisNode",
                position,
                draggable: false,
                className: [
                    PLOTTED_NODE_CLASS,
                    isEligible ? "pgraph-node--eligible" : "",
                    isDominated ? "pgraph-node--dominated" : "",
                ].filter(Boolean).join(" "),
                data: {
                    ...node.data,
                    analysis: {
                        color: colors?.get(node.id) ?? ROOT_COLOR,
                        role,
                        label: isRun ? `${nodeName(node.data.head)}…${nodeName(node.data.tail)}` : nodeName(node.id),
                        showLabel: node.data?.parent === "root" || Boolean(role) || isEligible,
                    },
                },
            };
        }

        const moved = position !== node.position;
        if (!isCurrent && !isSelectionA && !isEligible && !isDominated && !moved && !analysing) return node;

        const classes = [
            analysing ? PLOTTED_NODE_CLASS : "",
            role ? `pgraph-node--${role}` : "",
            isEligible ? "pgraph-node--eligible" : "",
            // Alongside the other marks rather than instead of them - a dominated node can still be current
            isDominated ? "pgraph-node--dominated" : "",
        ].filter(Boolean).join(" ");

        return {
            ...node,
            position,
            className: classes,
            // A card's place on the plot is its data, so it cannot be dragged off it
            ...(analysing ? {draggable: false} : {}),
            // The node components render a badge from this, so the pair is readable in a large graph
            data: (role && selectionAId) ? {...node.data, comparisonRole: role} : node.data,
        };
    });
}, [nodes, tableName, comparisonPair, selectionStage, eligibleDestinations, dominatorOf, shown, analysing,
    analysisStyle, colors]);


// The selected branch is lit up in the graph, so the trajectory in the panel is tied to a visible
// path through the tree. Edges are untouched when no branch is selected.
const styledEdges = useMemo(() => {
    const selectedStyle = {stroke: "#1877F2", strokeWidth: 3};

    /* Analysis mode draws each edge as a straight arrow from parent to child in the child's branch colour,
       without its label - the operation and its columns are still in the hover detail */
    if (analysing) {
        const hidden = new Set(nodes.filter((node) => !isPlotted(node)).map((node) => node.id));
        return edges.map((edge) => {
            const selected = selectedBranchEdges.has(`${edge.source}->${edge.target}`);
            const color = selected ? selectedStyle.stroke : colors?.get(edge.target) ?? ROOT_COLOR;
            return {
                ...edge,
                type: "analysis",
                label: undefined,
                // A plot's lines are solid; the tree's moving dashes would read as uncertainty here
                animated: false,
                hidden: hidden.has(edge.source) || hidden.has(edge.target),
                markerEnd: {type: MarkerType.ArrowClosed, color, width: 16, height: 16},
                style: selected ? selectedStyle : {stroke: color, strokeWidth: 1.75, opacity: 0.85},
            };
        });
    }

    if (selectedBranchEdges.size === 0) return edges;

    return edges.map((edge) => {
        if (!selectedBranchEdges.has(`${edge.source}->${edge.target}`)) return edge;

        return {...edge, style: {...edge.style, ...selectedStyle}};
    });
}, [edges, nodes, selectedBranchEdges, analysing, colors]);

/* The edge is labelled with just the operation, so the columns it acted on live in its hover detail.
   Uses the same shared #tooltip element as every chart, so placement stays edge-aware. */
const onEdgeMouseEnter = useCallback((event, edge) => {
    const detail = edge.data?.detail;
    if (!detail) return;
    showTooltip(`<strong>${detail}</strong><br/>click to start a branch here`, event);
}, []);

const onEdgeMouseMove = useCallback((event) => moveTooltip(event), []);
const onEdgeMouseLeave = useCallback(() => hideTooltip(), []);

/* In analysis mode a node's hover gives its numbers on both axes. In the tree, a greyed node says what
   beats it, so ruling it out is never unexplained. */
const onNodeMouseEnter = useCallback((event, node) => {
    const dominator = dominatorOf(node);
    if (analysing && isPlotted(node)) {
        showTooltip(analysisTooltip(node, analysisMetric, {role: roleOf(node), dominator}), event);
        return;
    }
    if (!dominator) return;
    showTooltip(`<strong>Dominated by ${nodeName(dominator)}</strong><br/>`
        + "no worse on error or drift, and better on at least one", event);
}, [dominatorOf, analysing, analysisMetric, roleOf]);

const onNodeMouseMove = useCallback((event) => moveTooltip(event), []);
const onNodeMouseLeave = useCallback(() => hideTooltip(), []);

/* In the tree, holding "c" turns a pane drag into a lasso (selectionKeyCode below). Whatever it caught is
   folded on release, so collapsing is its own gesture and does not compete with the click handlers. */
const onSelectionChange = useCallback(({nodes: selected}) => {
    lassoed.current = selected.map((node) => node.id);
}, []);

/* On the plot, holding shift draws a box instead, and letting go opens a detail inset on what is inside it: the
   box is read back into drift and error, which is what the inset keeps, so it stays on the same nodes however
   the plot is panned or zoomed. A box too small to mean anything, or around no nodes, is ignored. */
const boxStart = useRef(null);
const onSelectionStart = useCallback((event) => {
    boxStart.current = {x: event.clientX, y: event.clientY};
}, []);

const onSelectionEnd = (event) => {
    if (!analysing) {
        if (lassoed.current.length > 1) collapseNodes(lassoed.current);
        return;
    }
    const start = boxStart.current;
    boxStart.current = null;
    if (!start || !layout.scales || !flow.current) return;
    if (Math.abs(event.clientX - start.x) < MIN_BOX || Math.abs(event.clientY - start.y) < MIN_BOX) return;

    const corners = [start, {x: event.clientX, y: event.clientY}].map((point) => flow.current.screenToFlowPosition(point));
    const drift = corners.map((point) => layout.scales.x.invert(point.x)).sort((a, b) => a - b);
    const error = corners.map((point) => layout.scales.y.invert(point.y)).sort((a, b) => a - b);
    // Neither number goes below zero, so a box dragged past an axis stops at it
    const span = (lo, hi) => [Math.max(0, lo), Math.max(0, hi)];
    const [x, y] = [span(...drift), span(...error)];
    if (!(x[1] > x[0]) || !(y[1] > y[0])) return;
    const inside = (node) => isPlotted(node) && driftOf(node) >= x[0] && driftOf(node) <= x[1]
        && errorOf(node, analysisMetric) >= y[0] && errorOf(node, analysisMetric) <= y[1];
    if (!nodes.some(inside)) return;
    setInset({x, y});
};

  return (
    <div ref={containerRef} className={`pgraph-container ${analysing ? "pgraph-container--analysis" : ""}`}>
      <ReactFlow
        colorMode={"light"}
        onInit={(instance) => { flow.current = instance; }}
        nodes={styledNodes}
        edges={styledEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView={true}
        /* React Flow stops zooming out at half size by default, which in a narrow pane cannot fit the whole
           plot - analysis mode's full cards need a sixth of their size - nor a large tree */
        minZoom={0.05}
        connectionLineType={ConnectionLineType.SmoothStep}
        onNodeDoubleClick={onNodeDoubleClick}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        onEdgeMouseEnter={onEdgeMouseEnter}
        onEdgeMouseMove={onEdgeMouseMove}
        onEdgeMouseLeave={onEdgeMouseLeave}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseMove={onNodeMouseMove}
        onNodeMouseLeave={onNodeMouseLeave}
        onSelectionChange={onSelectionChange}
        onSelectionStart={onSelectionStart}
        onSelectionEnd={onSelectionEnd}
        /* A node's place on the plot is its data, so analysis mode neither drags nodes nor lassos them into
           a run - folding re-lays the tree, which the plot does not show */
        nodesDraggable={!analysing}
        /* In the tree, hold "c" and drag to lasso a run to collapse - shift is not the lasso key there, since
           shift-click re-targets the comparison's selection A. On the plot nothing is lassoed, so shift-drag
           is free to draw the box that magnifies; a shift-click on a node still picks selection A. */
        selectionKeyCode={analysing ? "Shift" : "c"}
      >
        {/* The graph's controls, and the way out of the selections made by clicking it */}
        <Panel position="top-right" className="pgraph-toolbar">
          <div className="pgraph-toolbar-row">
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
                title="Clear selection A and the selected branch"
              >
                Clear selections
              </button>
            )}
            <Segmented
              label="Graph mode"
              options={[["wrangling", "Wrangling"], ["analysis", "Analysis"]]}
              value={graphMode}
              onChange={(mode) => relayout({mode})}
            />
          </div>
          {analysing && (
            <div className="pgraph-toolbar-row">
              <Segmented
                label="Node style"
                options={[["simple", "Simple"], ["full", "Full nodes"]]}
                value={analysisStyle}
                onChange={(style) => relayout({style})}
              />
              <label className="pgraph-axis-pick">
                Error
                <select value={analysisMetric} onChange={(event) => relayout({metric: event.target.value})}>
                  {ANALYSIS_METRICS.map((metric) => <option key={metric} value={metric}>{METRIC_LABELS[metric]}</option>)}
                </select>
              </label>
            </div>
          )}
          {analysing && (
            <div className="pgraph-toolbar-row">
              <span className="pgraph-hint">Shift-drag around overlapping nodes for a detail inset</span>
            </div>
          )}
        </Panel>

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

        {/* The plot's own gridlines replace the tree's background in analysis mode */}
        {analysing && layout.scales
          ? <AnalysisAxes scales={layout.scales} metric={analysisMetric} />
          : <Background color="#ccc" variant={BackgroundVariant.Lines} />}
        {analysing && layout.scales && <FitPlotOnResize {...layout.scales.bounds} axisLeft={layout.scales.axisLeft} />}
        {/* Keyed on its region, so a new box opens a new inset, placed afresh */}
        {analysing && inset && layout.scales && (
          <AnalysisInset
            key={`${inset.x}|${inset.y}`}
            region={inset}
            scales={layout.scales}
            nodes={nodes}
            edges={edges}
            colors={colors}
            metric={analysisMetric}
            roleOf={roleOf}
            dominatorOf={dominatorOf}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            onClose={() => setInset(null)}
          />
        )}
        {/* Out of the way of the axes, which take the canvas's left and bottom edges in analysis mode */}
        <Controls position={analysing ? "bottom-right" : "bottom-left"} />
        {/*<MiniMap nodeStrokeWidth={3} />*/}
      </ReactFlow>
    </div>
  );
}
