import { useMemo, useState } from "react";

import { NavButton, StandardButton } from "../elements/Buttons.jsx";
import Sparkline from "../visualizations/Sparkline.jsx";
import DriftFlag from "../elements/DriftFlag.jsx";
import { ERROR_TYPES, ERROR_DIMENSIONS, errorColors, DRIFT_COLOR } from "../store/errorColors.js";
import { formatDrift, useDriftNull } from "../utils/drift.js";
import { describeWrangle, nodeName } from "../utils/comparison.js";
import { truncateText } from "../utils/textUtils.js";
import { usePgraph } from "../store/PGraphContext.jsx";
import { collapsedNodeIds } from "../utils/graphTopology.js";
import { useTableName } from "../store/TableNameContext.jsx";

import "../styles/QualityPanel.css";

const asPercent = (rate) => `${((rate ?? 0) * 100).toFixed(2)}%`;
const asPoints = (delta) => `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(2)} pts`;
const asShare = (contribution) => `${contribution > 0 ? "+" : ""}${(contribution * 100).toFixed(0)}%`;

const shareClass = (contribution) =>
  contribution < 0 ? "contribution-share--improved"
    : contribution > 0 ? "contribution-share--worsened"
      : "";

/* ── Shaping the trajectory into what the views render ──────────────────────────────────────── */

/**
 * Every step of the branch that moved this dimension, as rows ready to render.
 * A dimension reported unchanged yields no rows at all.
 */
function contributionRows(trajectory, dimension) {
  const series = trajectory?.dimensions?.[dimension];
  if (!series || series.no_change) return [];

  return series.contributions.map((contribution, step) => ({
    key: `${dimension}-${step}`,
    node: trajectory.nodes[step + 1],
    contribution,
    delta: series.deltas[step],
  }));
}

/** The columns view's rows, ordered by whichever error dimension - or drift - is being sorted on. */
function columnRows(metrics, distortion, sortBy) {
  // A column with no drift value sorts below every column that has one
  const driftOf = (row) => row.drift?.value ?? -1;

  return Object.entries(metrics?.columns ?? {})
    .map(([name, rates]) => ({ name, rates, drift: distortion?.columns?.[name] }))
    .sort((a, b) => (sortBy === "drift"
      ? driftOf(b) - driftOf(a)
      : (b.rates[sortBy] ?? 0) - (a.rates[sortBy] ?? 0)));
}

/* ── Branch selection ──────────────────────────────────────────────────────────────────────── */

/**
 * Walks the user through naming a branch: an edge fixes where it starts and which way it leaves that
 * node, then a node fixes where it ends. Both are picked by clicking the graph, so this reports the
 * state and prompts for the next click rather than offering its own controls.
 */
function BranchPicker({ selection, stage, eligibleCount, onReset }) {
  const steps = [
    {
      label: "Start edge",
      done: Boolean(selection.target),
      value: selection.target
        ? `${truncateText(selection.source, 9)} → ${truncateText(selection.target, 9)}`
        : null,
      prompt: "Click an edge in the graph",
    },
    {
      label: "End node",
      done: Boolean(selection.destination),
      value: selection.destination ? truncateText(selection.destination, 14) : null,
      prompt: stage === "edge"
        ? "Pick a start edge first"
        : `Click one of the ${eligibleCount} highlighted nodes`,
    },
  ];

  return (
    <div className="branch-picker">
      {steps.map((step, index) => (
        <div
          key={step.label}
          className={`branch-picker-step ${step.done ? "branch-picker-step--done" : ""}`}
        >
          <span className="branch-picker-index">{index + 1}</span>
          <span className="branch-picker-label">{step.label}</span>
          <span className={`branch-picker-value ${step.done ? "" : "branch-picker-value--pending"}`}>
            {step.value ?? step.prompt}
          </span>
        </div>
      ))}

      {selection.target && (
        <StandardButton onClick={onReset} className="standardButton--branch-reset">
          Start over
        </StandardButton>
      )}
    </div>
  );
}

/* ── Views ─────────────────────────────────────────────────────────────────────────────────── */

/**
 * How each wrangling step contributed to the branch's overall quality change.
 *
 * A contribution is signed: positive means that step drove the error rate up. Its magnitude is the
 * share of the branch's total absolute change attributable to the step.
 */
function ContributionList({ rows }) {
  if (rows.length === 0) {
    return <div className="quality-nochange">no change along this branch</div>;
  }

  return (
    <ul className="contribution-list">
      {rows.map((row) => (
        <li key={row.key} className="contribution-row">
          <span className="contribution-step" title={row.node}>{truncateText(row.node, 10)}</span>
          <span className={`contribution-share ${shareClass(row.contribution)}`}>
            {asShare(row.contribution)}
          </span>
          <span className="contribution-delta">{asPoints(row.delta)}</span>
        </li>
      ))}
    </ul>
  );
}

function TrajectoryView({ trajectory, stage, loading, foldedNodeIds }) {
  if (loading) return <div className="quality-empty">Loading…</div>;

  if (stage !== "complete" || !trajectory) {
    return (
      <div className="quality-empty">
        Pick a start edge and an end node in the graph to measure a branch.
      </div>
    );
  }

  return (
    <div className="quality-body">
      <div className="branch-summary">
        {trajectory.nodes.length - 1} step{trajectory.nodes.length === 2 ? "" : "s"}:{" "}
        {trajectory.nodes.map((node) => truncateText(node, 6)).join(" → ")}
      </div>

      {ERROR_DIMENSIONS.map((dimension) => {
        const series = trajectory.dimensions[dimension];

        return (
          <div key={dimension} className="quality-dimension">
            <div className="quality-dimension-header">
              <span className="quality-swatch" data-error-type={dimension} />
              <span className="quality-dimension-name">{ERROR_TYPES[dimension]}</span>
              <span className="quality-dimension-value">
                {asPercent(series.values[0])} → {asPercent(series.values[series.values.length - 1])}
              </span>
            </div>

            <Sparkline
              values={series.values}
              deltas={series.deltas}
              nodeIds={trajectory.nodes}
              color={errorColors(dimension)}
              collapsedNodeIds={foldedNodeIds}
            />

            <ContributionList rows={contributionRows(trajectory, dimension)} />
          </div>
        );
      })}

      {trajectory.distortion && (
        <DriftCard series={trajectory.distortion} nodeIds={trajectory.nodes} foldedNodeIds={foldedNodeIds} />
      )}
    </div>
  );
}

/**
 * Drift from root along the branch, ruled off below the error cards because it is not one of them.
 * Every value is measured from root and each step is the difference of two of them. It is a cost to be
 * spent knowingly: zero means nothing was done, not that the data is clean, so it is never colored as
 * better or worse - see app/pgraph/distortion.py.
 */
function DriftCard({ series, nodeIds, foldedNodeIds }) {
  const measured = series.values.every((value) => value != null);

  return (
    <div className="quality-dimension quality-drift">
      <div className="quality-dimension-header">
        <span className="quality-swatch quality-swatch--drift" />
        <span className="quality-dimension-name">Drift from root</span>
        {measured && (
          <span className="quality-dimension-value">
            {formatDrift(series.values[0])} → {formatDrift(series.values[series.values.length - 1])}
          </span>
        )}
      </div>

      {measured ? (
        <Sparkline
          values={series.values}
          deltas={series.deltas}
          nodeIds={nodeIds}
          color={DRIFT_COLOR}
          polarity="neutral"
          format="drift"
          collapsedNodeIds={foldedNodeIds}
        />
      ) : (
        <div className="quality-nochange">not measured on every node of this branch</div>
      )}

      <div className="quality-drift-note">A cost, not an error: how far the data has moved from the upload.</div>
    </div>
  );
}

/** One column's drift, with the null test's flag when it fired. A column with no value says why. */
function DriftCell({ drift, nullResult }) {
  if (!drift) return <td className="columns-table-drift columns-table-zero">—</td>;
  if (drift.degenerate) {
    return <td className="columns-table-drift columns-table-reason" title={drift.reason}>{drift.reason}</td>;
  }

  return (
    <td
      className="columns-table-drift"
      title={drift.low_confidence ? "Fewer than 30 values on one side, so this is a noisy estimate" : undefined}
    >
      {formatDrift(drift.value)}
      <DriftFlag result={nullResult} />
    </td>
  );
}

/**
 * Per-column error rates and drift for one node, straight from what the graph already carries. Drift has
 * its own column, ruled off from the error rates.
 */
function ColumnsView({ metrics, distortion, nodeId }) {
  const [sortBy, setSortBy] = useState("total");
  const rows = useMemo(() => columnRows(metrics, distortion, sortBy), [metrics, distortion, sortBy]);
  const nullResults = useDriftNull(nodeId, distortion?.facts?.rows_removed);

  if (rows.length === 0) return <div className="quality-empty">No column metrics.</div>;

  return (
    <div className="quality-body">
      <div className="columns-node" title={nodeId}>{truncateText(nodeId, 22)}</div>

      <div className="columns-sort">
        <span className="columns-sort-label">Sort by</span>
        {["total", ...ERROR_DIMENSIONS, "drift"].map((dimension) => (
          <NavButton
            key={dimension}
            isSelected={sortBy === dimension}
            onClick={() => setSortBy(dimension)}
            className="navButton--column-sort"
          >
            {dimension}
          </NavButton>
        ))}
      </div>

      <table className="columns-table">
        <thead>
          <tr>
            <th>column</th>
            {ERROR_DIMENSIONS.map((dimension) => (
              <th key={dimension} title={ERROR_TYPES[dimension]}>
                <span className="quality-swatch" data-error-type={dimension} />
              </th>
            ))}
            <th>total</th>
            <th className="columns-table-drift" title="Drift from root - a cost, not an error">drift</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ name, rates, drift }) => (
            <tr key={name}>
              <td className="columns-table-name" title={name}>{truncateText(name, 12)}</td>
              {ERROR_DIMENSIONS.map((dimension) => (
                <td key={dimension} className={rates[dimension] ? "" : "columns-table-zero"}>
                  {rates[dimension] ? asPercent(rates[dimension]) : "—"}
                </td>
              ))}
              <td className="columns-table-total">{asPercent(rates.total)}</td>
              <DriftCell drift={drift} nullResult={nullResults[name]} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The graph's leaves on error and drift together. A leaf another leaf beats on both is ruled out whatever
 * the analyst values, so it is struck through, names what beats it, and cannot be picked. The rest - the
 * frontier - are deliberately not ranked against each other: whether fewer errors or less drift matters
 * more is the analyst's call. The same verdict greys the dominated nodes in the graph itself.
 */
function TradeoffView({ pareto, nodesById, currentNode, onUse }) {
  const rows = useMemo(() => (pareto?.scored ?? [])
    .map((id) => {
      const data = nodesById?.[id]?.data;
      return {
        id,
        wrangle: describeWrangle(data?.wrangle),
        error: data?.metrics?.totals?.total,
        drift: data?.distortion?.overall,
        rows: data?.metrics?.row_count,
        dominator: pareto.dominated?.[id] ?? null,
      };
    })
    // The frontier first, then the dominated; within each, fewest errors first
    .sort((a, b) => (Number(Boolean(a.dominator)) - Number(Boolean(b.dominator))) || ((a.error ?? 0) - (b.error ?? 0))),
  [pareto, nodesById]);

  if (rows.length === 0) return <div className="quality-empty">No finished branches to weigh up yet.</div>;

  return (
    <div className="quality-body">
      <div className="tradeoff-note">
        Every leaf of the graph, on error and drift together. A struck-through leaf is beaten on both by
        another, so it is never the better choice.
      </div>

      <table className="columns-table tradeoff-table">
        <thead>
          <tr>
            <th>node</th>
            <th className="tradeoff-wrangle">wrangle</th>
            <th>error</th>
            <th className="columns-table-drift">drift</th>
            <th>rows</th>
            <th aria-label="Use" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className={row.dominator ? "tradeoff-row--dominated" : ""}>
              <td className="columns-table-name" title={row.id}>
                {nodeName(row.id)}
                {row.dominator && (
                  <span
                    className="tradeoff-beaten"
                    title={`Dominated by ${nodeName(row.dominator)}: no worse on error or drift, and better on at least one`}
                  >
                    beaten by {nodeName(row.dominator)}
                  </span>
                )}
              </td>
              <td className="tradeoff-wrangle" title={row.wrangle ?? ""}>{row.wrangle ?? "—"}</td>
              <td>{asPercent(row.error)}</td>
              <td className="columns-table-drift">{formatDrift(row.drift)}</td>
              <td>{row.rows?.toLocaleString() ?? "—"}</td>
              <td>
                <button
                  type="button"
                  className="tradeoff-use"
                  disabled={Boolean(row.dominator) || row.id === currentNode}
                  onClick={() => onUse(row.id)}
                  title={row.id === currentNode ? "This is the current node" : "Make this the current node"}
                >
                  Use
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function QualityPanel() {
  const {
    nodes, branchSelection, selectionStage, eligibleDestinations,
    branchTrajectory, branchTrajectoryLoading, resetBranchSelection, collapsedRuns, serverNodesById,
    pareto, onNodeDoubleClick,
  } = usePgraph();
  const { tableName } = useTableName();

  const [view, setView] = useState("trajectory");

  // Columns describe wherever the branch ends, falling back to the node currently loaded
  const columnsNodeId = branchSelection.destination ?? tableName;
  // Read by the real table, so a node folded into a collapsed run still has its numbers
  const columnsData = (serverNodesById?.[columnsNodeId] ?? nodes.find((node) => node.id === columnsNodeId))?.data;

  /* Which of the branch's nodes the graph currently has folded away. The trajectory itself is
     unchanged - this only lets the chart mark the points you cannot see in the graph. */
  const foldedNodeIds = useMemo(() => collapsedNodeIds(collapsedRuns), [collapsedRuns]);

  // The dock owns the panel chrome - tab strip, collapsing and resizing - so this renders bare content
  return (
    <div id="quality-root">
      <div className="navButtonContainer quality-views">
        <NavButton isSelected={view === "trajectory"} onClick={() => setView("trajectory")}>
          Trajectory
        </NavButton>
        <NavButton isSelected={view === "columns"} onClick={() => setView("columns")}>
          Columns
        </NavButton>
        <NavButton isSelected={view === "tradeoff"} onClick={() => setView("tradeoff")}>
          Trade-off
        </NavButton>
      </div>

      {view === "trajectory" && (
        <>
          <BranchPicker
            selection={branchSelection}
            stage={selectionStage}
            eligibleCount={eligibleDestinations.size}
            onReset={resetBranchSelection}
          />
          <TrajectoryView
            trajectory={branchTrajectory}
            stage={selectionStage}
            loading={branchTrajectoryLoading}
            foldedNodeIds={foldedNodeIds}
          />
        </>
      )}

      {view === "columns" && (
        <ColumnsView metrics={columnsData?.metrics} distortion={columnsData?.distortion} nodeId={columnsNodeId} />
      )}

      {view === "tradeoff" && (
        <TradeoffView
          pareto={pareto}
          nodesById={serverNodesById}
          currentNode={tableName}
          // The same navigation as double-clicking the node in the graph
          onUse={(id) => onNodeDoubleClick(null, { id })}
        />
      )}
    </div>
  );
}
