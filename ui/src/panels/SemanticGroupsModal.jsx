import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { querySemanticGroups } from "../utils/serverCalls.jsx";
import { useSelection } from "../store/SelectionContext.jsx";
import { useTableName } from "../store/TableNameContext.jsx";

import "../styles/SemanticGroupsModal.css";

function formatPercent(value, digits = 0) {
  return `${(Number(value || 0) * 100).toFixed(digits)}%`;
}

function titleCase(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function ExampleRows({ groupId, examples, boundary = false }) {
  if (!examples?.length) return null;
  return (
    <div className={boundary ? "semantic-example-list semantic-example-list--boundary" : "semantic-example-list"}>
      {examples.map((example, index) => (
        <div className="semantic-example-row" key={`${groupId}-example-${example.rowId}-${index}`}>
          <div className="semantic-example-row-heading">
            <strong>Row {example.rowId}</strong>
            <span>{example.reason}</span>
          </div>
          <dl>
            {Object.entries(example.values || {}).map(([column, value]) => (
              <div key={`${groupId}-${example.rowId}-${column}`}>
                <dt>{column}</dt>
                <dd title={String(value)}>{String(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  );
}

function Metric({ label, value, title }) {
  return (
    <div className="semantic-group-metric" title={title}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function GroupCard({ group, expanded, onToggle, onSelectRows }) {
  return (
    <article className="semantic-group-card">
      <div className="semantic-group-card-main">
        <div className="semantic-group-card-copy">
          <div className="semantic-group-eyebrow">
            <span className={`semantic-view-badge semantic-view-badge--${group.view}`}>
              {group.viewLabel}
            </span>
            <span>{group.rows.toLocaleString()} rows in this group</span>
            <span>{formatPercent(group.coverage, 1)} of sample</span>
            {group.errorRows > 0 && (
              <span
                className="semantic-group-error-count"
                title="How many of this group's rows have at least one detected data-quality issue — not the same number as the group's total row count."
              >
                {group.errorRows.toLocaleString()} with a detected issue
              </span>
            )}
          </div>
          <h3>{group.semanticCohort || group.description}</h3>
          <p className="semantic-group-quality-summary">
            <strong>Quality pattern:</strong> {group.qualityPattern || "No unusual concentration of data-quality issues in this group."}
          </p>
        </div>
        <div className="semantic-group-card-actions">
          <button
            type="button"
            className="semantic-group-select"
            onClick={() => onSelectRows(group)}
          >
            Select rows
          </button>
          <button
            type="button"
            className="semantic-group-details-toggle"
            onClick={onToggle}
            aria-expanded={expanded}
          >
            {expanded ? "Hide details" : "View details"}
          </button>
        </div>
      </div>

      <div className="semantic-group-metrics" aria-label="Group evidence">
        <Metric
          label="Semantic rank"
          value={formatPercent(group.semanticScore)}
          title="How specific and meaningful this group's description is, paired with whether it also carries a real quality issue. This is the primary sort key across all groups — a rank, not a probability of correctness."
        />
        <Metric
          label="Stable"
          value={formatPercent(group.stability)}
          title="How closely this group matched a repeated clustering run."
        />
        <Metric
          label="Cohesive"
          value={formatPercent(group.coherence)}
          title="How similar the rows are inside this group."
        />
        <Metric
          label="Profile confidence"
          value={formatPercent(group.profileConfidence)}
          title="Average profiler confidence for the columns used in this view."
        />
      </div>

      {expanded && (
        <div className="semantic-group-details">
          <section className="semantic-group-explanation-summary">
            <div>
              <h4>Semantic cohort</h4>
              <p>{group.semanticCohort || group.description}</p>
            </div>
            <div>
              <h4>Quality pattern</h4>
              <p>{group.qualityPattern || "No unusual concentration of data-quality issues in this group."}</p>
            </div>
          </section>

          {(group.supportingFields || []).length > 0 && (
            <section className="semantic-group-support">
              <h4>Important supporting fields</h4>
              <div className="semantic-group-support-list">
                {group.supportingFields.map((field, index) => (
                  <div key={`${group.id}-support-${field.kind}-${field.column}-${index}`}>
                    <span>{titleCase(field.kind)}</span>
                    <strong>{field.column}</strong>
                    <p>{field.evidence}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {(group.representativeExamples || []).length > 0 && (
            <section className="semantic-group-examples">
              <h4>Typical rows from this group</h4>
              <p className="semantic-group-section-help">
                These sampled rows are nearest to the group center and best illustrate the description.
              </p>
              <ExampleRows groupId={group.id} examples={group.representativeExamples} />
            </section>
          )}

          {(group.contradictoryExamples || []).length > 0 && (
            <section className="semantic-group-examples semantic-group-examples--boundary">
              <h4>Boundary rows worth checking</h4>
              <p className="semantic-group-section-help">
                These rows still belong to the group, but fit its center least closely. They show where the summary may be too broad.
              </p>
              <ExampleRows groupId={group.id} examples={group.contradictoryExamples} boundary />
            </section>
          )}

          <section>
            <h4>Columns used in similarity</h4>
            <div className="semantic-group-column-list">
              {(group.columnsUsed || []).map(column => <span key={`${group.id}-${column}`}>{column}</span>)}
            </div>
          </section>

          {(group.featureHighlights || []).length > 0 && (
            <section>
              <h4>Additional rule evidence</h4>
              <ul className="semantic-group-highlight-list">
                {group.featureHighlights.map((highlight, index) => (
                  <li key={`${group.id}-highlight-${index}`}>{highlight}</li>
                ))}
              </ul>
            </section>
          )}

          {(group.caveats || []).length > 0 && (
            <section className="semantic-group-caveats">
              <h4>Check before acting</h4>
              <ul>
                {group.caveats.map((caveat, index) => (
                  <li key={`${group.id}-caveat-${index}`}>{caveat}</li>
                ))}
              </ul>
            </section>
          )}

          <section className="semantic-group-method">
            <h4>Method details</h4>
            <p>
              {group.algorithm}. Distinctiveness {formatPercent(group.distinctiveness)};
              explainability {formatPercent(group.explainability)}.
            </p>
            <p>{group.whyUseful}</p>
          </section>
        </div>
      )}
    </article>
  );
}

export default function SemanticGroupsModal({ visible, onClose, refreshKey = 0 }) {
  const { tableName } = useTableName();
  const { setHighlightedRowIds } = useSelection();
  const [semanticData, setSemanticData] = useState(null);
  const [openGroupId, setOpenGroupId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!visible || !tableName) return undefined;
    let cancelled = false;

    async function discoverGroups() {
      setLoading(true);
      setError(null);
      try {
        const response = await querySemanticGroups(tableName, "semantic_quality", {
          limit: 18,
        });
        if (cancelled) return;
        if (!response?.success) {
          throw new Error(response?.error || "Buckaroo could not discover useful groups.");
        }
        setSemanticData(response.data);
        setOpenGroupId(null);
      } catch (requestError) {
        if (!cancelled) {
          setError(requestError.message || "Buckaroo could not discover useful groups.");
          setSemanticData(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    discoverGroups();
    return () => {
      cancelled = true;
    };
  }, [visible, tableName, refreshKey]);

  useEffect(() => {
    if (!visible) return undefined;
    const onKeyDown = event => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [visible, onClose]);

  const groups = semanticData?.groups || [];
  const visibleGroups = groups;
  const adaptivePolicy = semanticData?.adaptivePolicy;
  const representation = semanticData?.representation;
  const sampleDescription = semanticData
    ? semanticData.sampleRows === semanticData.totalRows
      ? `all ${semanticData.sampleRows.toLocaleString()} rows`
      : `${semanticData.sampleRows.toLocaleString()} randomly sampled rows from ${semanticData.totalRows.toLocaleString()}`
    : "";

  if (!visible) return null;

  function handleSelectRows(group) {
    setHighlightedRowIds(group.rowIds || [], group.columnsUsed || [], "semantic_group", {
      action: "profiler_guided_group_select",
      group: group.id,
      view: group.view,
      algorithm: group.algorithm,
      rowIdsTruncated: group.rowIdsTruncated,
    });
    onClose();
  }

  return createPortal((
    <div className="semantic-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="semantic-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="semantic-modal-title"
        onMouseDown={event => event.stopPropagation()}
      >
        <header className="semantic-modal-header">
          <div>
            <span className="semantic-modal-kicker">Profiler-guided discovery</span>
            <h2 id="semantic-modal-title">Useful row groups</h2>
            <p>
              {semanticData
                ? `${groups.length} groups, ranked by semantic meaningfulness, based on ${sampleDescription}.`
                : "Buckaroo is combining profiler-guided semantic and quality evidence."}
            </p>
          </div>
          <button type="button" className="semantic-modal-close" onClick={onClose} aria-label="Close useful groups">
            x
          </button>
        </header>

        {semanticData && (
          <div className="semantic-modal-profile-note">
            <strong>Profiler guardrails</strong>
            <span>
              {(semanticData.profileSummary?.excludedIdentifierColumns || []).length} identifier columns excluded
              {"; "}{(semanticData.profileSummary?.excludedLowConfidenceColumns || []).length} low-confidence columns held back.
            </span>
            {adaptivePolicy && (
              <span title={adaptivePolicy.confidence_source}>
                Profile-confidence gate: {formatPercent(adaptivePolicy.profile_confidence_cutoff)} from this dataset.
              </span>
            )}
            {adaptivePolicy && (
              <span title={adaptivePolicy.min_group_source}>
                Repeated-group support: {adaptivePolicy.min_group_size.toLocaleString()} rows from observed frequencies.
              </span>
            )}
            {representation?.activeBlocks?.length > 0 && (
              <span title="Each block is normalized before all blocks enter one clustering matrix.">
                Combined evidence: {representation.activeBlocks.map(titleCase).join(", ")}.
              </span>
            )}
            <span>All active evidence blocks feed one clustering decision; algorithms and cluster counts are compared using repeated-run evidence.</span>
          </div>
        )}

        {loading && (
          <div className="semantic-modal-state">
            <strong>Discovering useful groups...</strong>
            <span>Transforming semantic fields, adding quality evidence, and checking partition stability.</span>
          </div>
        )}
        {error && <div className="semantic-modal-state semantic-modal-state--error">{error}</div>}
        {!loading && !error && visibleGroups.length === 0 && (
          <div className="semantic-modal-state">
            <strong>No useful groups passed the safeguards for this sample.</strong>
            <span>Buckaroo suppresses tiny, unstable, dominant, or identifier-driven results.</span>
          </div>
        )}

        {!loading && !error && visibleGroups.length > 0 && (
          <div className="semantic-group-list">
            {visibleGroups.map(group => (
              <GroupCard
                key={group.id}
                group={group}
                expanded={openGroupId === group.id}
                onToggle={() => setOpenGroupId(openGroupId === group.id ? null : group.id)}
                onSelectRows={handleSelectRows}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  ), document.body);
}
