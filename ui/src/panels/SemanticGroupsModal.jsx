import { useEffect, useState } from "react";

import { querySemanticGroups } from "../utils/serverCalls.jsx";
import { useSelection } from "../store/SelectionContext.jsx";
import { useTableName } from "../store/TableNameContext.jsx";

import "../styles/SemanticGroupsModal.css";

// These are the strategy options shown in the Semantic Groups dropdown.
// `value` is the internal API name. `label` is the user-facing text.
const SEMANTIC_STRATEGIES = [
  { value: "meta", label: "Meta" },
  { value: "auto", label: "Auto" },
  { value: "cluster_first", label: "All Rows" },
  { value: "error_first", label: "Errors" },
  { value: "exact_slices", label: "Slices" },
];

// Short explanations shown beside the selected strategy.
// They are written for users, not developers, so they avoid implementation details.
const STRATEGY_DESCRIPTIONS = {
  meta: "Scores multiple candidate groupings and shows the strongest result.",
  auto: "Chooses Buckaroo's default semantic strategy for the current dataset.",
  cluster_first: "Clusters all rows first, then ranks clusters by error concentration.",
  error_first: "Clusters only rows that already have detector errors into diagnostic themes.",
  exact_slices: "Finds exact value/bin slices, then ranks them by error concentration.",
};

// The Meta strategy is a small selector: it runs several concrete strategies,
// scores each result, rejects obviously weak outputs, and shows the best result.
// `clusterCount` is the `k` value for clustering. Higher k creates more groups,
// which can be more specific but can also split related rows too aggressively.
const META_SELECTOR_CANDIDATES = [
  { id: "cluster_first_k4", label: "All Rows k=4", strategy: "cluster_first", options: { clusterCount: 4 } },
  { id: "cluster_first_k8", label: "All Rows k=8", strategy: "cluster_first", options: { clusterCount: 8 } },
  { id: "error_first_k4", label: "Errors k=4", strategy: "error_first", options: { clusterCount: 4 } },
  { id: "error_first_k8", label: "Errors k=8", strategy: "error_first", options: { clusterCount: 8 } },
  { id: "exact_slices", label: "Slices", strategy: "exact_slices", options: {} },
];

// The selector uses a sample so the UI stays responsive on large datasets.
const META_SELECTOR_SAMPLE_ROWS = 1500;

// Convert a decimal like 0.271 into a display value like "27.1%".
function formatPercent(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

// Convert a lift value like 3.687 into a display value like "3.69x".
function formatLift(value) {
  return `${Number(value || 0).toFixed(2)}x`;
}

// Turn detector issue keys into readable text.
// Example: "missing:workclass" becomes "missing in workclass".
function formatIssue(issue) {
  if (!issue || issue === "none") return "No dominant issue";
  return issue.replace(":", " in ");
}

// Small helper for averaging numeric values. Empty lists return 0 so scoring
// does not crash when a strategy returns no groups.
function average(values) {
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + Number(value || 0), 0) / values.length;
}

// Score one Meta candidate. The candidate is one strategy/settings pair, such as
// "All Rows k=8". The response is what the backend returned for that candidate.
// The result of this function lets all candidates be compared on one scale.
function scoreMetaCandidate(candidate, response, durationMs) {
  // If the backend failed or returned no data, keep a record of the failure and
  // assign a very low score so this candidate cannot win.
  if (!response?.success || !response?.data) {
    return {
      candidate,
      response,
      durationMs,
      accepted: false,
      selectorScore: -1000000,
      rejectionReason: response?.error || "Request failed",
    };
  }

  const data = response.data;
  const groups = data.groups || [];

  // The backend returns groups sorted from strongest to weakest. Scoring uses
  // the top few groups so one lucky group does not decide the whole strategy.
  const topGroups = groups.slice(0, 5);
  const top = groups[0];
  const rejectionReasons = [];
  const sampledRows = Number(data.sampleRows || 0);

  // A useful grouping should not be one huge group containing almost every row.
  // This fraction measures how much of the sample is covered by the top group.
  const largestReturnedFraction = sampledRows && top ? Number(top.rows || 0) / sampledRows : 0;

  // Mean top score asks: are the best few groups strong overall?
  const meanTopScore = average(topGroups.map(group => group.score));

  // Lift asks: are errors more concentrated in these groups than in the table
  // overall? A lift near 1.0 means the group is not much better than random.
  const meanTopLift = average(topGroups.map(group => group.lift));

  // Coverage asks: how much of the table's detected error mass is explained by
  // the best groups? High lift with tiny coverage can still be unhelpful.
  const top5Coverage = topGroups.reduce((sum, group) => sum + Number(group.errorCoverage || 0), 0);

  // Slow strategies are still allowed to win, but they lose a small amount of
  // score so the UI prefers faster strategies when quality is similar.
  const runtimePenalty = Math.min(Number(durationMs || 0) / 30000, 1.5) * 0.25;

  // Penalize overly broad top groups. The penalty starts after 55% of the sample
  // because broad groups are usually harder for users to interpret.
  const dominancePenalty = Math.max(0, largestReturnedFraction - 0.55) * 1.4;

  // If the whole table is not already mostly errors, weak lift should count
  // against the candidate. When baseline errors are near 100%, lift is less
  // meaningful because every group naturally has lift close to 1.
  const lowLiftPenalty = data.baselineErrorRate < 0.95 ? Math.max(0, 1.05 - meanTopLift) * 1.2 : 0;

  // Hard rejection rules remove outputs that are technically valid but not
  // useful enough to show as the selected Meta result.
  if (!groups.length) rejectionReasons.push("No groups");
  if (top && Number(top.errorRows || 0) < 2) rejectionReasons.push("Too few error rows");
  if (largestReturnedFraction >= 0.9) rejectionReasons.push("Dominant group");

  const accepted = rejectionReasons.length === 0;

  // Accepted candidates get a positive quality score. Rejected candidates keep
  // their mean score for debugging, but the -1000 offset keeps them below any
  // accepted candidate unless every candidate is rejected.
  const selectorScore = accepted
    ? meanTopScore
      + (Number(top?.score || 0) * 0.25)
      + (Math.max(0, meanTopLift - 1) * 1.4)
      + (Math.min(top5Coverage, 1.5) * 2.0)
      - dominancePenalty
      - lowLiftPenalty
      - runtimePenalty
    : -1000 + meanTopScore;

  // Return both the final score and the supporting metrics so the UI can show
  // why a candidate won or why it was rejected.
  return {
    candidate,
    response,
    durationMs,
    accepted,
    selectorScore,
    rejectionReason: accepted ? "accepted" : rejectionReasons.join(", "),
    meanTopScore,
    meanTopLift,
    top5Coverage,
    largestReturnedFraction,
    groupCount: groups.length,
    topDescription: top?.description || "No group",
  };
}

// Run all Meta candidates in parallel, score them, and return the selected
// candidate's backend data plus selector metadata for debugging/explanation.
async function queryMetaSemanticGroups(tableName) {
  const results = await Promise.all(
    META_SELECTOR_CANDIDATES.map(async (candidate) => {
      const started = performance.now();
      const response = await querySemanticGroups(tableName, candidate.strategy, {
        limit: 8,
        sampleRows: META_SELECTOR_SAMPLE_ROWS,
        minGroupSize: 12,
        minErrorRows: 2,
        ...candidate.options,
      });
      return scoreMetaCandidate(candidate, response, performance.now() - started);
    })
  );

  // If every backend request failed, the Meta selector itself fails.
  const successful = results.filter(result => result.response?.success && result.response?.data);
  if (!successful.length) {
    return {
      success: false,
      error: results.find(result => result.rejectionReason)?.rejectionReason || "Meta selector failed.",
    };
  }

  // Prefer accepted candidates. If all candidates were rejected, fall back to
  // the best successful candidate so the user still gets a diagnostic result.
  const accepted = successful.filter(result => result.accepted);
  const pool = accepted.length ? accepted : successful;
  const selected = [...pool].sort((a, b) => b.selectorScore - a.selectorScore)[0];
  const ranked = [...results].sort((a, b) => b.selectorScore - a.selectorScore);
  const selectedData = selected.response.data;

  // Preserve the selected strategy's normal response, then attach Meta metadata
  // so the modal can explain which candidate was chosen.
  return {
    success: true,
    data: {
      ...selectedData,
      strategy: "meta",
      effectiveStrategy: selectedData.effectiveStrategy,
      metaSelector: {
        selectedCandidateId: selected.candidate.id,
        selectedCandidateLabel: selected.candidate.label,
        selectedStrategy: selected.candidate.strategy,
        selectedClusterCount: selected.candidate.options.clusterCount || null,
        selectorScore: selected.selectorScore,
        acceptedCount: accepted.length,
        candidateCount: results.length,
        selectionBasis: accepted.length ? "accepted" : "fallback",
        candidates: ranked.map((result, index) => ({
          id: result.candidate.id,
          label: result.candidate.label,
          rank: index + 1,
          accepted: result.accepted,
          selectorScore: result.selectorScore,
          groups: result.groupCount || 0,
          meanTopLift: result.meanTopLift || 0,
          top5Coverage: result.top5Coverage || 0,
          rejectionReason: result.rejectionReason,
        })),
      },
    },
  };
}

function SemanticGroupRow({ group, selected, onToggle, onSelectRows }) {
  return (
    <>
      <tr className={selected ? "semantic-modal-row semantic-modal-row--open" : "semantic-modal-row"}>
        <td>
          <button
            type="button"
            className="semantic-modal-row-toggle"
            onClick={onToggle}
            title={selected ? "Hide group details" : "Show group details"}
          >
            {selected ? "v" : ">"}
          </button>
        </td>
        <td className="semantic-modal-description-cell">
          <div className="semantic-modal-description">{group.description}</div>
          <div className="semantic-modal-subtext">{formatIssue(group.mainIssue)}</div>
        </td>
        <td>{group.errorRows}/{group.rows}</td>
        <td>{formatPercent(group.errorRate)}</td>
        <td>{formatLift(group.lift)}</td>
        <td>{formatPercent(group.errorCoverage)}</td>
        <td className="semantic-modal-action-cell">
          <button
            type="button"
            className="semantic-modal-select"
            onClick={() => onSelectRows(group)}
          >
            Select Rows
          </button>
        </td>
      </tr>
      {selected && (
        <tr className="semantic-modal-details-row">
          <td />
          <td colSpan={6}>
            <div className="semantic-modal-details">
              <div>
                <span className="semantic-modal-detail-label">Group ID</span>
                <span>{group.group}</span>
              </div>
              <div>
                <span className="semantic-modal-detail-label">Main columns</span>
                <span>{(group.mainErrorColumns || []).join(", ") || "None"}</span>
              </div>
              {(group.featureHighlights || []).length > 0 && (
                <div>
                  <span className="semantic-modal-detail-label">Why grouped</span>
                  <ul>
                    {group.featureHighlights.map((feature, index) => (
                      <li key={`${group.id}-feature-${index}`}>{feature}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function SemanticGroupsModal({ visible, onClose, refreshKey = 0 }) {
  const { tableName } = useTableName();
  const { setHighlightedRowIds } = useSelection();
  const [strategy, setStrategy] = useState("meta");
  const [semanticData, setSemanticData] = useState(null);
  const [openGroupId, setOpenGroupId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingText, setLoadingText] = useState("Finding semantic groups...");
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!visible || !tableName) return undefined;

    let cancelled = false;
    async function fetchSemanticGroups() {
      setLoading(true);
      setLoadingText(strategy === "meta" ? "Running meta selector..." : "Finding semantic groups...");
      setError(null);
      try {
        const response = strategy === "meta"
          ? await queryMetaSemanticGroups(tableName)
          : await querySemanticGroups(tableName, strategy);
        if (cancelled) return;
        if (!response?.success) {
          setError(response?.error || "Semantic grouping failed.");
          setSemanticData(null);
          return;
        }
        setSemanticData(response.data);
        setOpenGroupId(response.data?.groups?.[0]?.id || null);
      } catch (err) {
        if (!cancelled) {
          setError(err.message || "Semantic grouping failed.");
          setSemanticData(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchSemanticGroups();
    return () => {
      cancelled = true;
    };
  }, [visible, tableName, strategy, refreshKey]);

  useEffect(() => {
    if (!visible) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [visible, onClose]);

  if (!visible) return null;

  function handleSelectRows(group) {
    setHighlightedRowIds(group.rowIds || [], group.mainErrorColumns || [], "semantic_group", {
      action: "semantic_group_select",
      group: group.group,
      strategy: group.strategy,
      rowIdsTruncated: group.rowIdsTruncated,
    });
  }

  const groups = semanticData?.groups || [];
  const metaSelector = semanticData?.metaSelector;
  const sampledLabel = semanticData
    ? `${semanticData.sampleRows.toLocaleString()} sampled rows`
    : "No sample loaded";

  return (
    <div className="semantic-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="semantic-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="semantic-modal-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="semantic-modal-header">
          <div>
            <h2 id="semantic-modal-title">Semantic Groups</h2>
            <p>
              {semanticData
                ? `${semanticData.errorRows.toLocaleString()} error rows, baseline ${formatPercent(semanticData.baselineErrorRate)}, ${sampledLabel}`
                : sampledLabel}
            </p>
          </div>
          <div className="semantic-modal-controls">
            <label>
              <span>Strategy</span>
              <select value={strategy} onChange={(event) => setStrategy(event.target.value)}>
                {SEMANTIC_STRATEGIES.map(option => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <button type="button" className="semantic-modal-close" onClick={onClose} aria-label="Close semantic groups">
              x
            </button>
          </div>
        </header>

        <div className="semantic-modal-tool-note">
          <strong>{SEMANTIC_STRATEGIES.find(item => item.value === strategy)?.label}</strong>
          <span>{STRATEGY_DESCRIPTIONS[strategy]}</span>
          {metaSelector && (
            <span>
              Selected {metaSelector.selectedCandidateLabel} from {metaSelector.candidateCount} candidates
              {" "}({metaSelector.acceptedCount} accepted).
            </span>
          )}
          {semanticData?.similarityDescription && <span>{semanticData.similarityDescription}</span>}
        </div>

        {metaSelector && (
          <div className="semantic-modal-meta-strip">
            {metaSelector.candidates.slice(0, 5).map(candidate => (
              <span
                key={candidate.id}
                className={candidate.id === metaSelector.selectedCandidateId
                  ? "semantic-modal-candidate semantic-modal-candidate--selected"
                  : "semantic-modal-candidate"}
                title={candidate.rejectionReason}
              >
                {candidate.rank}. {candidate.label} · {formatLift(candidate.meanTopLift)}
              </span>
            ))}
          </div>
        )}

        {loading && <div className="semantic-modal-state">{loadingText}</div>}
        {error && <div className="semantic-modal-state semantic-modal-state--error">Error: {error}</div>}
        {!loading && !error && groups.length === 0 && (
          <div className="semantic-modal-state">No concentrated semantic groups found.</div>
        )}

        {!loading && !error && groups.length > 0 && (
          <div className="semantic-modal-table-wrap">
            <table className="semantic-modal-table">
              <thead>
                <tr>
                  <th aria-label="Details" />
                  <th>Group</th>
                  <th>Error Rows</th>
                  <th>Error Rate</th>
                  <th>Lift</th>
                  <th>Coverage</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {groups.map(group => (
                  <SemanticGroupRow
                    key={group.id}
                    group={group}
                    selected={openGroupId === group.id}
                    onToggle={() => setOpenGroupId(openGroupId === group.id ? null : group.id)}
                    onSelectRows={handleSelectRows}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
