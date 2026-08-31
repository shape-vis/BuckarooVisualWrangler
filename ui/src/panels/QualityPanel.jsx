import { useMemo, useState } from "react";

import { NavButton, StandardButton } from "../elements/Buttons.jsx";
import Sparkline from "../visualizations/Sparkline.jsx";
import { ERROR_TYPES, ERROR_DIMENSIONS, errorColors } from "../store/errorColors.js";
import { truncateText } from "../utils/textUtils.js";
import { usePgraph } from "../store/PGraphContext.jsx";
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

/** The columns view's rows, ordered by whichever dimension is being sorted on. */
function columnRows(metrics, sortBy) {
  return Object.entries(metrics?.columns ?? {})
    .map(([name, rates]) => ({ name, rates }))
    .sort((a, b) => (b.rates[sortBy] ?? 0) - (a.rates[sortBy] ?? 0));
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

function TrajectoryView({ trajectory, stage, loading }) {
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
            />

            <ContributionList rows={contributionRows(trajectory, dimension)} />
          </div>
        );
      })}
    </div>
  );
}

/** Per-column error rates for one node, straight from the metrics already in the graph. */
function ColumnsView({ metrics, nodeId }) {
  const [sortBy, setSortBy] = useState("total");
  const rows = useMemo(() => columnRows(metrics, sortBy), [metrics, sortBy]);

  if (rows.length === 0) return <div className="quality-empty">No column metrics.</div>;

  return (
    <div className="quality-body">
      <div className="columns-node" title={nodeId}>{truncateText(nodeId, 22)}</div>

      <div className="columns-sort">
        <span className="columns-sort-label">Sort by</span>
        {["total", ...ERROR_DIMENSIONS].map((dimension) => (
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
          </tr>
        </thead>
        <tbody>
          {rows.map(({ name, rates }) => (
            <tr key={name}>
              <td className="columns-table-name" title={name}>{truncateText(name, 12)}</td>
              {ERROR_DIMENSIONS.map((dimension) => (
                <td key={dimension} className={rates[dimension] ? "" : "columns-table-zero"}>
                  {rates[dimension] ? asPercent(rates[dimension]) : "—"}
                </td>
              ))}
              <td className="columns-table-total">{asPercent(rates.total)}</td>
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
    branchTrajectory, branchTrajectoryLoading, resetBranchSelection,
  } = usePgraph();
  const { tableName } = useTableName();

  const [view, setView] = useState("trajectory");

  // Columns describe wherever the branch ends, falling back to the node currently loaded
  const columnsNodeId = branchSelection.destination ?? tableName;
  const metrics = nodes.find((node) => node.id === columnsNodeId)?.data?.metrics;

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
          />
        </>
      )}

      {view === "columns" && <ColumnsView metrics={metrics} nodeId={columnsNodeId} />}
    </div>
  );
}
