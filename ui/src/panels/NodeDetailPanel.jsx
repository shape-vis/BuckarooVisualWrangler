import { useMemo, useState } from "react";

import { NavButton } from "../elements/Buttons.jsx";
import Sparkline from "../visualizations/Sparkline.jsx";
import { ERROR_TYPES, ERROR_DIMENSIONS } from "../store/errorColors.js";
import { branchColor } from "../store/branchColors.js";
import { truncateText } from "../utils/textUtils.js";
import { usePgraph } from "../store/PGraphContext.jsx";

import "../styles/NodeDetailPanel.css";

const asPercent = (rate) => `${((rate ?? 0) * 100).toFixed(2)}%`;
const asPoints = (delta) => `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(2)} pts`;
const asShare = (contribution) => `${contribution > 0 ? "+" : ""}${(contribution * 100).toFixed(0)}%`;

const shareClass = (contribution) =>
  contribution < 0 ? "contribution-share--improved"
    : contribution > 0 ? "contribution-share--worsened"
      : "";

/* ── Shaping the trajectory into what the views render ──────────────────────────────────────── */

/**
 * Give every branch the identity it is drawn with: a color, and a label naming where it ends.
 * The color is the same one PGraphContext paints that branch's graph edges with.
 */
function decorateBranches(trajectory) {
  return (trajectory?.branches ?? []).map((branch, index) => ({
    ...branch,
    color: branchColor(index),
    label: branch.leaf_op || `branch ${index + 1}`,
  }));
}

/** One entry per branch, in the shape Sparkline draws. */
function seriesForDimension(branches, dimension) {
  return branches.map((branch) => ({
    values: branch.dimensions[dimension].values,
    deltas: branch.dimensions[dimension].deltas,
    nodeIds: branch.nodes,
    color: branch.color,
    label: branch.label,
  }));
}

/**
 * Every step that moved this dimension, flattened across branches into rows ready to render.
 * Branches reported as unchanged contribute nothing, so a flat dimension yields no rows at all.
 */
function contributionRows(branches, dimension) {
  return branches
    .filter((branch) => !branch.dimensions[dimension].no_change)
    .flatMap((branch) => {
      const { deltas, contributions } = branch.dimensions[dimension];

      return contributions.map((contribution, step) => ({
        key: `${branch.leaf}-${step}`,
        color: branch.color,
        node: branch.nodes[step + 1],
        contribution,
        delta: deltas[step],
      }));
    });
}

/**
 * The headline rate for a dimension. Branches all begin at the selected node, so that shared first
 * value is the one number that describes the node itself rather than one arbitrary branch's end.
 */
function selectedNodeRate(branches, dimension) {
  return branches[0]?.dimensions[dimension]?.values[0];
}

/** The columns view's rows, ordered by whichever dimension is being sorted on. */
function columnRows(metrics, sortBy) {
  return Object.entries(metrics?.columns ?? {})
    .map(([name, rates]) => ({ name, rates }))
    .sort((a, b) => (b.rates[sortBy] ?? 0) - (a.rates[sortBy] ?? 0));
}

/* ── Views ─────────────────────────────────────────────────────────────────────────────────── */

/**
 * How each wrangling step contributed to its branch's overall quality change.
 *
 * A contribution is signed: positive means that step drove the error rate up. Its magnitude is the
 * share of that branch's total absolute change attributable to the step.
 */
function ContributionList({ rows }) {
  if (rows.length === 0) {
    return <div className="node-detail-nochange">no change along any branch</div>;
  }

  return (
    <ul className="contribution-list">
      {rows.map((row) => (
        <li key={row.key} className="contribution-row">
          <span className="contribution-branch" style={{ backgroundColor: row.color }} />
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

/** Ties each line's color to the branch it traces, matching the edges lit up in the graph. */
function BranchLegend({ branches }) {
  if (branches.length < 2) return null;

  return (
    <div className="branch-legend">
      {branches.map((branch) => (
        <span key={branch.leaf} className="branch-legend-item" title={branch.leaf}>
          <span className="branch-legend-swatch" style={{ backgroundColor: branch.color }} />
          {branch.label}
        </span>
      ))}
      <span className="branch-legend-note">dashed = got worse</span>
    </div>
  );
}

function TrajectoryView({ branches }) {
  if (branches.length === 0) return <div className="node-detail-empty">No downstream branch.</div>;

  return (
    <div className="node-detail-body">
      <BranchLegend branches={branches} />

      {ERROR_DIMENSIONS.map((dimension) => (
        <div key={dimension} className="node-detail-dimension">
          <div className="node-detail-dimension-header">
            <span className="node-detail-swatch" data-error-type={dimension} />
            <span className="node-detail-dimension-name">{ERROR_TYPES[dimension]}</span>
            <span className="node-detail-dimension-value">
              {asPercent(selectedNodeRate(branches, dimension))}
            </span>
          </div>

          <Sparkline series={seriesForDimension(branches, dimension)} />

          <ContributionList rows={contributionRows(branches, dimension)} />
        </div>
      ))}
    </div>
  );
}

/** The selected node's per-column error rates, straight from the metrics already in the graph. */
function ColumnsView({ metrics }) {
  const [sortBy, setSortBy] = useState("total");
  const rows = useMemo(() => columnRows(metrics, sortBy), [metrics, sortBy]);

  if (rows.length === 0) return <div className="node-detail-empty">No column metrics.</div>;

  return (
    <div className="node-detail-body">
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
                <span className="node-detail-swatch" data-error-type={dimension} />
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

export default function NodeDetailPanel() {
  // The trajectory is fetched in PGraphContext because the graph needs it too, to color each
  // branch's edges to match its line here
  const { nodes, detailNodeId, trajectory, trajectoryLoading } = usePgraph();

  const [view, setView] = useState("trajectory");

  const metrics = nodes.find((node) => node.id === detailNodeId)?.data?.metrics;
  const branches = useMemo(() => decorateBranches(trajectory), [trajectory]);

  // The dock owns the panel chrome - tab strip, collapsing and resizing - so this renders bare content
  return (
      <div id="node-detail-root">
        <div className="node-detail-title" title={detailNodeId ?? ""}>
          {detailNodeId ? truncateText(detailNodeId, 20) : "No node selected"}
        </div>

        {!detailNodeId && (
          <div className="node-detail-empty">
            Open a node's chart button in the graph to inspect it.
          </div>
        )}

        {detailNodeId && (
          <>
            <div className="navButtonContainer node-detail-views">
              <NavButton isSelected={view === "trajectory"} onClick={() => setView("trajectory")}>
                Trajectory
              </NavButton>
              <NavButton isSelected={view === "columns"} onClick={() => setView("columns")}>
                Columns
              </NavButton>
            </div>

            {trajectoryLoading && <div className="node-detail-empty">Loading…</div>}
            {!trajectoryLoading && view === "trajectory" && <TrajectoryView branches={branches} />}
            {!trajectoryLoading && view === "columns" && <ColumnsView metrics={metrics} />}
          </>
        )}
      </div>
  );
}
