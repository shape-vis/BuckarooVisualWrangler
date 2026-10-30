import React, { useCallback, useEffect, useMemo, useState, useRef } from "react";
import { createPortal } from "react-dom";

import {
  addDataFilter,
  clearDataFilters,
  deleteColumn,
  deleteProfileRoleOverride,
  getPGraph,
  queryAttributeSummaries,
  saveProfileRoleOverride,
} from "../utils/serverCalls.jsx";
import { ERROR_TYPES, errorColors } from "../store/errorColors.js";
import { truncateText } from "../utils/textUtils.js";
import CollapsiblePanel from "../elements/CollapsiblePanel.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { useLoading } from "../store/LoadingContext.jsx";
import { useRepair } from "../store/RepairContext.jsx";
import { usePgraph } from "../store/PGraphStore.jsx";
import { useSelection } from "../store/SelectionContext.jsx";

import "../styles/AttributeSummaryPanel.css";
import FilterModal from "../elements/FilterModal.jsx";
import Modal from "../elements/Modal.jsx";

const COLUMN_FILTER_SESSION_KEY = "buckarooActiveColumnFilters";

function ColumnActionsMenu({ attr, selectedAttributes, handleToggleSelect, showFilter, onDeleteAttribute }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const isSelected = selectedAttributes.includes(attr);

  return (
    <div className="popupMenuWrapper attribute-card-actions" ref={ref} onClick={(event) => event.stopPropagation()}>
      <button
        type="button"
        className={`attribute-card-select ${isSelected ? "attribute-card-select--active" : ""}`}
        aria-pressed={isSelected}
        aria-label={isSelected ? `Deselect ${attr}` : `Select ${attr}`}
        title={isSelected ? "Remove column from plots" : "Select column for plots"}
        onClick={() => handleToggleSelect(attr)}
      >
        <span aria-hidden="true">{isSelected ? "✓" : ""}</span>
      </button>

      <button
        type="button"
        className={`attribute-card-menu ${open ? "attribute-card-menu--active" : ""}`}
        aria-expanded={open}
        aria-label={`Column actions for ${attr}`}
        title="Column actions"
        onClick={() => setOpen((prev) => !prev)}
      >
        <span aria-hidden="true">...</span>
      </button>

      {open && (
        <div className="popupMenu">
          <button type="button" onClick={() => { showFilter(attr); setOpen(false); }}>Filter rows by this column</button>
          <div className="popupMenuDivider" role="separator" />
          <button
            type="button"
            className="popupMenuItem--danger"
            disabled={attr === "ID"}
            title={attr === "ID" ? "Buckaroo requires the ID column." : undefined}
            onClick={() => { setOpen(false); onDeleteAttribute(attr); }}
          >
            Delete column
          </button>
        </div>
      )}
    </div>
  );
}

function DeleteColumnDialog({ attribute, busy, onCancel, onConfirm }) {
  if (!attribute) return null;
  return createPortal(
    <Modal visible>
      <div className="delete-column-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-column-title">
        <h2 id="delete-column-title">Delete {attribute}?</h2>
        <p>The column will be removed in a new provenance step. You can restore it with Undo.</p>
        <div className="delete-column-dialog-actions">
          <button type="button" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className="delete-column-confirm" onClick={onConfirm} disabled={busy}>
            {busy ? "Deleting..." : "Delete column"}
          </button>
        </div>
      </div>
    </Modal>,
    document.body,
  );
}

function formatConfidence(score, fallback) {
  const numericScore = Number(score);
  if (Number.isFinite(numericScore)) {
    return `${Math.round(numericScore * 100)}%`;
  }
  return fallback ? fallback : "unknown";
}

function confidenceTone(score, confidence) {
  const numericScore = Number(score);
  if (Number.isFinite(numericScore)) {
    if (numericScore >= 0.85) return "high";
    if (numericScore >= 0.65) return "medium";
    return "low";
  }
  return (confidence || "unknown").toLowerCase();
}

function formatEvidencePercent(score) {
  const numericScore = Number(score);
  if (!Number.isFinite(numericScore)) return "unknown";
  return `${Math.round(numericScore * 100)}%`;
}

function formatRowCount(value) {
  const count = Number(value);
  if (!Number.isFinite(count) || count < 0) return null;
  if (count >= 1000000) return `${(count / 1000000).toFixed(count % 1000000 === 0 ? 0 : 1)}M`;
  if (count >= 1000) return `${(count / 1000).toFixed(count % 1000 === 0 ? 0 : 1)}K`;
  return String(Math.round(count));
}

function profileSampleContext(profileContext = {}) {
  const totalRows = Number(profileContext.totalRows);
  const requestedSampleRows = Number(profileContext.profileSampleRows);
  const hasTotalRows = Number.isFinite(totalRows) && totalRows >= 0;
  const sampled = Boolean(profileContext.profilesSampled) && Number.isFinite(requestedSampleRows) && requestedSampleRows > 0;
  const profiledRows = sampled ? Math.min(requestedSampleRows, totalRows) : totalRows;

  if (!hasTotalRows || !Number.isFinite(profiledRows)) {
    return { compact: "profile scope unknown", detail: "Profile row scope was not returned by the server." };
  }

  const compactProfiled = formatRowCount(profiledRows);
  const compactTotal = formatRowCount(totalRows);
  const detailedProfiled = Math.round(profiledRows).toLocaleString();
  const detailedTotal = Math.round(totalRows).toLocaleString();

  if (sampled && profiledRows < totalRows) {
    return {
      compact: `${compactProfiled} / ${compactTotal} rows`,
      detail: `Based on ${detailedProfiled} of ${detailedTotal} table rows.`,
    };
  }

  return {
    compact: `${compactTotal} rows`,
    detail: `Based on all ${detailedTotal} table rows.`,
  };
}

function formatCandidateReason(candidate) {
  if (!candidate.reason) return "";
  return truncateText(candidate.reason, 90);
}

function userSafeSamplingText(profile) {
  if (profile?.samplingExhausted) {
    return "Ambiguous after examining all available rows. No more rows are available to sample.";
  }
  if (profile?.needsMoreSampling && profile?.moreRowsAvailable !== false) {
    return "Decision made from a partial sample; confidence may improve with more data.";
  }
  return "";
}

const REVIEW_FILTERS = [
  { id: "all", group: "view", label: "All", title: "Show every column card. This does not select columns for plotting." },
  { id: "review", group: "view", label: "Review", title: "Needs review means Buckaroo is uncertain, changed after more sampling, or found identity-like evidence in a semantically sensitive field. Ordinary geography is not flagged." },
  { id: "warnings", group: "view", label: "Warnings", title: "Warnings mean Buckaroo found a data-quality signal such as missing, mismatched, incomplete, or anomalous values." },
  { id: "possibleKeys", group: "focus", label: "Keys", title: "Columns selected as identifier-like or carrying strong key evidence." },
  { id: "changed", group: "focus", label: "Changed", title: "Columns whose decision changed after Buckaroo inspected more rows." },
];

const REVIEW_FILTER_GROUPS = [
  { id: "view", label: "View" },
  { id: "focus", label: "Focus" },
];

const PROFILE_ROLE_OPTIONS = [
  ["identifier", "primary-key candidate"],
  ["primary_key", "primary key"],
  ["quasi_identifier", "possible identifier"],
  ["datetime", "date/time field"],
  ["datetime_high_uniqueness", "high-uniqueness timestamp"],
  ["datetime_identifier", "timestamp-like identifier"],
  ["datetime_category", "date/time category"],
  ["numeric_measure", "numeric measure"],
  ["numeric_code_category", "numeric code category"],
  ["binary_category", "binary category"],
  ["categorical", "categorical field"],
  ["free_text", "free-text field"],
  ["vector_blob", "vector/blob text"],
  ["geographic_coordinate", "geographic coordinate"],
  ["geography_location", "geography/location field"],
  ["high_uniqueness_location_field", "high-uniqueness location field"],
  ["location_name", "location name"],
  ["postal_code", "postal code"],
  ["airport_code", "airport code"],
  ["country_code", "country code"],
];

const PROFILE_ROLE_OPTION_VALUES = new Set(PROFILE_ROLE_OPTIONS.map(([value]) => value));

function isUncertainProfile(profile) {
  // Buckaroo's synthetic ID column intentionally has no semantic profile; it
  // should not inflate the user's review workload.
  if (!profile) return false;
  const confidence = Number(profile?.confidenceScore);
  return Boolean(
    !Number.isFinite(confidence)
    || confidence < 0.65
    || profile?.classificationAmbiguous
    || profile?.needsMoreSampling
  );
}

function splitProfileMessage(message) {
  return String(message || "")
    .split(";")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function dataWarningMessages(profile, columnErrors = {}) {
  const explicitWarnings = splitProfileMessage(profile?.dataWarning);
  const detectorWarnings = Object.entries(columnErrors || {})
    .filter(([type, value]) => (
      type !== "total"
      && type !== "none"
      && Number.isFinite(Number(value))
      && Number(value) > 0
    ))
    .map(([type]) => `${ERROR_TYPES[type] || type} was detected.`);

  return [...new Set([...explicitWarnings, ...detectorWarnings])].slice(0, 4);
}

function hasDataWarning(profile, columnErrors = {}) {
  return dataWarningMessages(profile, columnErrors).length > 0;
}

function profileReviewReasons(profile) {
  const hasStructuredReviewReasons = Array.isArray(profile?.reviewReasons);
  const reasons = hasStructuredReviewReasons
    ? profile.reviewReasons.filter(Boolean)
    : [];

  // The legacy profiler used `warning` and `adaptiveWarning` for semantic
  // uncertainty. Treat these as review cues while older API responses exist.
  if (!hasStructuredReviewReasons) {
    reasons.push(...splitProfileMessage(profile?.adaptiveWarning || profile?.warning));
  }
  if (profile?.changedAfterMoreSampling) {
    reasons.push("Buckaroo changed this decision after examining more rows.");
  }
  if (profile?.isSemanticallySensitive && reasons.length === 0) {
    reasons.push("This is semantically sensitive data and should be reviewed before it is used as an identity or join key.");
  }
  return [...new Set(reasons)].slice(0, 4);
}

function isPossibleKey(profile) {
  const role = String(profile?.profileRole || "").toLowerCase();
  if (["identifier", "primary_key", "quasi_identifier"].includes(role)) return true;

  return Array.isArray(profile?.candidateRoles) && profile.candidateRoles.some((candidate) => {
    const candidateRole = String(candidate?.role || candidate?.label || "").toLowerCase();
    const confidence = Number(candidate?.confidence);
    const isKeyRole = candidateRole.includes("primary") || candidateRole.includes("identifier");
    return isKeyRole && Number.isFinite(confidence) && confidence >= 0.8;
  });
}

function needsProfileReview(profile) {
  return Boolean(
    isUncertainProfile(profile)
    || profile?.isSemanticallySensitive
    || profileReviewReasons(profile).length > 0
    || profile?.changedAfterMoreSampling
  );
}

function matchesReviewFilter(profile, filterId, columnErrors = {}) {
  if (filterId === "all") return true;
  if (filterId === "review") return needsProfileReview(profile);
  if (filterId === "warnings") return hasDataWarning(profile, columnErrors);
  if (filterId === "possibleKeys") return isPossibleKey(profile);
  if (filterId === "changed") return Boolean(profile?.changedAfterMoreSampling);
  return true;
}

function EvidenceList({ title, items = [], tone }) {
  const visibleItems = Array.isArray(items) ? items.filter(Boolean).slice(0, 6) : [];
  if (visibleItems.length === 0) return null;

  return (
    <div className={`attribute-profile-evidence-list attribute-profile-evidence-list--${tone}`}>
      <div className="attribute-profile-detail-label">{title}</div>
      <ul>
        {visibleItems.map((item, index) => (
          <li key={`${tone}-${index}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function ExampleValues({ title, items = [], tone, emptyText }) {
  const visibleItems = Array.isArray(items) ? items.filter(Boolean).slice(0, 4) : [];

  return (
    <div className={`attribute-profile-examples attribute-profile-examples--${tone}`}>
      <div className="attribute-profile-detail-label">{title}</div>
      {visibleItems.length > 0 ? (
        <div className="attribute-profile-example-chips">
          {visibleItems.map((item, index) => (
            <span className="attribute-profile-example-chip" key={`${tone}-${index}`} title={item}>
              {item}
            </span>
          ))}
        </div>
      ) : (
        <p className="attribute-profile-example-empty">{emptyText}</p>
      )}
    </div>
  );
}

function AttributeProfileSummary({ profile, columnErrors = {} }) {
  if (!profile) {
    return (
      <div className="attribute-profile-summary attribute-profile-summary--empty">
        <span className="attribute-profile-role attribute-profile-role--unknown">No role yet</span>
      </div>
    );
  }

  const tone = confidenceTone(profile.confidenceScore, profile.confidence);
  const roleLabel = profile.userOverrideLabel || profile.roleLabel || profile.profileRole || profile.role || "unknown role";
  const overrideTitle = profile.userOverrideRole
    ? `User correction. Buckaroo originally suggested ${profile.roleLabel || profile.profileRole || "an unknown role"}.`
    : profile.profileRole;
  const dataWarnings = dataWarningMessages(profile, columnErrors);
  const reviewReasons = profileReviewReasons(profile);
  const needsReview = needsProfileReview(profile);

  return (
    <div className="attribute-profile-summary">
      <div className="attribute-profile-heading">
        <span className={`attribute-profile-role attribute-profile-role--${tone} ${profile.userOverrideRole ? "attribute-profile-role--overridden" : ""}`} title={overrideTitle}>
          {roleLabel}
        </span>
        <span className="attribute-profile-confidence" title={profile.sampleReliability || undefined}>
          {formatConfidence(profile.confidenceScore, profile.confidence)}
        </span>
        {dataWarnings.length > 0 && (
          <span className="attribute-profile-warning-icon" title={`Warning: Buckaroo found a possible data-quality issue. ${dataWarnings.join(" ")}`} aria-label={`Data warning: ${dataWarnings.join(" ")}`}>
            !
          </span>
        )}
        {needsReview && (
          <span
            className="attribute-profile-sampling-icon"
            title={`Needs review: the column may be valid, but Buckaroo needs a human check. ${reviewReasons.join(" ") || userSafeSamplingText(profile)}`}
            aria-label="Needs review"
          >
            ?
          </span>
        )}
      </div>
    </div>
  );
}

function ProfileCorrectionSection({ attr, profile, onSave, onClear }) {
  const suggestedRole = profile?.profileRole || "categorical";
  const defaultRole = PROFILE_ROLE_OPTION_VALUES.has(profile?.userOverrideRole)
    ? profile.userOverrideRole
    : PROFILE_ROLE_OPTION_VALUES.has(suggestedRole)
      ? suggestedRole
      : "categorical";
  const [role, setRole] = useState(defaultRole);
  const [note, setNote] = useState(profile?.userOverrideNote || "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [expanded, setExpanded] = useState(false);
  const hasOverride = Boolean(profile?.userOverrideRole);

  useEffect(() => {
    const nextSuggestedRole = profile?.profileRole || "categorical";
    setRole(
      PROFILE_ROLE_OPTION_VALUES.has(profile?.userOverrideRole)
        ? profile.userOverrideRole
        : PROFILE_ROLE_OPTION_VALUES.has(nextSuggestedRole)
          ? nextSuggestedRole
          : "categorical"
    );
    setNote(profile?.userOverrideNote || "");
    setMessage("");
    setExpanded(false);
  }, [attr, profile?.profileRole, profile?.userOverrideRole, profile?.userOverrideNote]);

  async function handleSave(event) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      await onSave(attr, role, note);
      setMessage("Correction saved.");
      setExpanded(false);
    } catch (error) {
      setMessage(error.message || "Could not save this correction.");
    } finally {
      setSaving(false);
    }
  }

  async function handleClear() {
    setSaving(true);
    setMessage("");
    try {
      await onClear(attr);
      setMessage("Correction cleared. Buckaroo's suggestion is shown again.");
      setExpanded(false);
    } catch (error) {
      setMessage(error.message || "Could not clear this correction.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="attribute-profile-drawer-section attribute-profile-correction-section">
      <div className="attribute-profile-correction-heading">
        <div>
          <div className="attribute-profile-detail-label">Your decision</div>
          <p>{hasOverride ? `Corrected to ${profile.userOverrideLabel || profile.userOverrideRole}.` : "Looks wrong? Correct the role here."}</p>
        </div>
        <button
          type="button"
          className="attribute-profile-correction-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? "Close" : (hasOverride ? "Edit" : "Correct role")}
        </button>
      </div>
      {expanded && (
        <>
          {hasOverride && (
            <div className="attribute-profile-original-role">
              Buckaroo suggested: <strong>{profile.roleLabel || profile.profileRole}</strong>
            </div>
          )}
          <form className="attribute-profile-correction-form" onSubmit={handleSave}>
            <label htmlFor={`profile-role-${attr}`}>Your corrected role</label>
            <select id={`profile-role-${attr}`} value={role} onChange={(event) => setRole(event.target.value)} disabled={saving}>
              {PROFILE_ROLE_OPTIONS.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <label htmlFor={`profile-note-${attr}`}>Review note (optional)</label>
            <textarea
              id={`profile-note-${attr}`}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Why is this correction needed?"
              maxLength={1000}
              rows={2}
              disabled={saving}
            />
            <div className="attribute-profile-correction-actions">
              <button type="submit" className="attribute-profile-correction-save" disabled={saving}>
                {saving ? "Saving..." : "Save correction"}
              </button>
              {hasOverride && (
                <button type="button" className="attribute-profile-correction-clear" onClick={handleClear} disabled={saving}>
                  Clear correction
                </button>
              )}
            </div>
          </form>
        </>
      )}
      {message && <p className="attribute-profile-correction-message" role="status">{message}</p>}
    </section>
  );
}

function AttributeProfileDrawer({ attr, profile, profileContext, attrDist = {}, columnErrors = {}, onClose, onSaveOverride, onClearOverride }) {
  const [activeTab, setActiveTab] = useState("role");

  if (!attr) return null;

  const tone = confidenceTone(profile?.confidenceScore, profile?.confidence);
  const roleLabel = profile?.roleLabel || profile?.profileRole || profile?.role || "unknown role";
  const displayRoleLabel = profile?.userOverrideLabel || roleLabel;
  const roleFamilyLabel = profile?.userOverrideFamily
    ? profile.userOverrideFamily.replaceAll("_", " ")
    : (profile?.roleFamilyLabel || profile?.roleFamily || "Unknown");
  const roleSubtypeLabel = profile?.userOverrideLabel
    || profile?.roleSubtypeLabel
    || displayRoleLabel;
  const sampleContext = profileSampleContext(profileContext);
  const candidates = Array.isArray(profile?.candidateRoles) ? profile.candidateRoles.slice(0, 6) : [];
  const safeSamplingText = userSafeSamplingText(profile);
  const errorEntries = Object.entries(columnErrors || {});
  const dataWarnings = dataWarningMessages(profile, columnErrors);
  const reviewReasons = profileReviewReasons(profile);
  const needsReview = needsProfileReview(profile);
  const hasStats = Boolean(attrDist?.numeric || attrDist?.categorical);
  const hasMetrics = Boolean(
    Number.isFinite(Number(profile?.sampleUncertaintyMargin))
    || Number.isFinite(Number(profile?.candidateConfidenceGap))
    || profile?.sampleReliability
    || profile?.adaptiveSamplingAction
    || profile?.fullDataStateLabel
  );

  return createPortal(
    <div className="attribute-profile-inspector" role="presentation">
      <button type="button" className="attribute-profile-backdrop" aria-label="Close column inspector" onClick={onClose} />
      <aside className="attribute-profile-drawer" role="dialog" aria-modal="true" aria-label={`Profile explanation for ${attr}`}>
      <div className="attribute-profile-drawer-header">
        <div>
          <div className="attribute-profile-drawer-eyebrow">Column inspector</div>
          <h3 title={attr}>{attr}</h3>
        </div>
        <button type="button" className="attribute-profile-drawer-close" aria-label="Close column inspector" onClick={onClose}>
          X
        </button>
      </div>

      {!profile ? (
        <div className="attribute-profile-drawer-section">
          <p>No profiler metadata is available for this column yet.</p>
        </div>
      ) : (
        <>
          <section className="attribute-profile-drawer-section attribute-profile-example-section">
            <div className="attribute-profile-example-heading">
              <div>
                <div className="attribute-profile-detail-label">Check the data first</div>
                <p>Representative values from the rows Buckaroo profiled.</p>
              </div>
            </div>
            <div className="attribute-profile-example-columns">
              <ExampleValues
                title={`Fits ${roleLabel}`}
                tone="supporting"
                items={profile.supportingExamples}
                emptyText="No matching example was retained from this sample."
              />
              <ExampleValues
                title="Worth checking"
                tone="conflicting"
                items={profile.conflictingExamples}
                emptyText="No direct contradiction was found in this sample."
              />
            </div>
          </section>

          <div className="attribute-profile-drawer-role-card">
            <div className="attribute-profile-role-hierarchy">
              <div>
                <span>Buckaroo chose</span>
                <b
                  className={`attribute-profile-role attribute-profile-role--${tone} ${profile.userOverrideRole ? "attribute-profile-role--overridden" : ""}`}
                  title={profile.userOverrideRole ? `User correction; Buckaroo suggested ${roleLabel}.` : profile.profileRole}
                >
                  {roleSubtypeLabel}
                </b>
              </div>
              <div>
                <span>Role family</span>
                <strong>{roleFamilyLabel}</strong>
              </div>
            </div>
            <div className="attribute-profile-drawer-confidence">
              <strong>{formatConfidence(profile.confidenceScore, profile.confidence)} confidence</strong>
            </div>
          </div>

          <ProfileCorrectionSection attr={attr} profile={profile} onSave={onSaveOverride} onClear={onClearOverride} />

          <div className="attribute-profile-tabs" role="tablist" aria-label="Column inspector sections">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "role"}
              className={activeTab === "role" ? "attribute-profile-tab--active" : ""}
              onClick={() => setActiveTab("role")}
            >
              Role decision
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "summary"}
              className={activeTab === "summary" ? "attribute-profile-tab--active" : ""}
              onClick={() => setActiveTab("summary")}
            >
              Data summary
            </button>
          </div>

          {activeTab === "role" ? (
            <div className="attribute-profile-tab-panel" role="tabpanel">
              {needsReview && (
                <div className="attribute-profile-drawer-review-notice">
                  <div className="attribute-profile-detail-label">Needs review</div>
                  <div>This does not mean the data is wrong. Buckaroo is asking for a human check because the result is uncertain or semantically sensitive.</div>
                  {reviewReasons.length > 0 && (
                    <ul className="attribute-profile-review-reason-list">
                      {reviewReasons.map((reason) => <li key={reason}>{reason}</li>)}
                    </ul>
                  )}
                  {profile.changedAfterMoreSampling && (
                  <div>
                    The initial {Number(profile.initialProfileRows).toLocaleString()}-row profile was
                    {profile.initialRoleLabel ? ` ${profile.initialRoleLabel}` : " different"}; Buckaroo changed this decision after examining more rows.
                  </div>
                  )}
                </div>
              )}

              {dataWarnings.length > 0 && (
                <div className="attribute-profile-drawer-warning" title={dataWarnings.join(" ")}>
                  <div className="attribute-profile-detail-label">Data warning</div>
                  <div>Buckaroo found a possible data-quality issue. This is separate from semantic uncertainty.</div>
                  <ul className="attribute-profile-review-reason-list">
                    {dataWarnings.map((warning) => <li key={warning}>{warning}</li>)}
                  </ul>
                </div>
              )}

              {profile.reason && (
                <section className="attribute-profile-drawer-section">
                  <div className="attribute-profile-detail-label">Why Buckaroo chose this role</div>
                  <p>{profile.reason}</p>
                </section>
              )}

              <details className="attribute-profile-details-disclosure">
                <summary>Evidence and alternatives</summary>
                <div className="attribute-profile-details-content">
                  {profile.positiveEvidence?.length > 0 && (
                    <EvidenceList title="Supports this role" tone="positive" items={profile.positiveEvidence} />
                  )}

                  {profile.negativeEvidence?.length > 0 && (
                    <EvidenceList title="Could make this uncertain" tone="negative" items={profile.negativeEvidence} />
                  )}

                  {candidates.length > 0 && (
                    <div className="attribute-profile-details-block">
                  <div className="attribute-profile-detail-label">Candidate roles</div>
                  <ul className="attribute-profile-candidate-list">
                    {candidates.map((candidate) => (
                      <li key={`${candidate.role}-${candidate.confidence}`}>
                        {(() => {
                          const supportsSelectedFamily = Boolean(
                            candidate.chosen
                            && candidate.role !== profile.roleSubtype
                            && candidate.roleFamily === profile.roleFamily
                          );
                          return (
                            <>
                              <span className="attribute-profile-candidate-role">
                                <span className="attribute-profile-candidate-role-label">
                                  {supportsSelectedFamily
                                    ? `${candidate.roleFamilyLabel || candidate.roleFamily} family`
                                    : (candidate.label || candidate.role || "unknown")}
                                </span>
                                {candidate.chosen && (
                                  <span className="attribute-profile-candidate-badge">
                                    {supportsSelectedFamily ? "family evidence" : "chosen"}
                                  </span>
                                )}
                              </span>
                              <span className="attribute-profile-candidate-score">{formatConfidence(candidate.confidence)}</span>
                              {candidate.reason && (
                                <span className="attribute-profile-candidate-reason" title={candidate.reason}>
                                  {formatCandidateReason(candidate)}
                                </span>
                              )}
                            </>
                          );
                        })()}
                      </li>
                    ))}
                  </ul>
                    </div>
                  )}

                  {hasMetrics && (
                    <div className="attribute-profile-details-block">
                  <div className="attribute-profile-detail-label">Confidence detail</div>
                  <div className="attribute-profile-evidence-grid">
                    {Number.isFinite(Number(profile.sampleUncertaintyMargin)) && (
                      <div><span>Interval width</span><strong>{formatEvidencePercent(profile.sampleUncertaintyMargin)}</strong></div>
                    )}
                    {Number.isFinite(Number(profile.candidateConfidenceGap)) && (
                      <div><span>Candidate gap</span><strong>{formatEvidencePercent(profile.candidateConfidenceGap)}</strong></div>
                    )}
                    {profile.sampleReliability && (
                      <div><span>Sample reliability</span><strong>{profile.sampleReliability}</strong></div>
                    )}
                    {profile.adaptiveSamplingAction && (
                      <div><span>Sampling action</span><strong>{profile.adaptiveSamplingAction.replaceAll("_", " ")}</strong></div>
                    )}
                    {profile.fullDataStateLabel && (
                      <div><span>Full-data state</span><strong>{profile.fullDataStateLabel}</strong></div>
                    )}
                  </div>
                  {safeSamplingText && (
                    <div className="attribute-profile-sampling" title={profile.adaptiveSamplingReason || undefined}>{safeSamplingText}</div>
                  )}
                  {profile.adaptiveSamplingReason && (
                    <p className="attribute-profile-drawer-muted">
                      <strong>{profile.samplingExhausted ? "Why ambiguity remains: " : "Sampling reason: "}</strong>
                      {profile.adaptiveSamplingReason}
                    </p>
                  )}
                    </div>
                  )}
                </div>
              </details>
            </div>
          ) : (
            <div className="attribute-profile-tab-panel" role="tabpanel">
              <section className="attribute-profile-drawer-section attribute-profile-summary-scope">
                <div className="attribute-profile-detail-label">Profile scope</div>
                <p>{sampleContext.detail}</p>
              </section>

              {hasStats && (
                <section className="attribute-profile-drawer-section">
                  <div className="attribute-profile-detail-label">Column statistics</div>
                  <div className="attribute-profile-drawer-stat-grid">
                    {attrDist.numeric && (
                      <>
                        <div><span>Numeric mean</span><strong>{Number(attrDist.numeric.mean).toFixed(2)}</strong></div>
                        <div><span>Numeric range</span><strong>{attrDist.numeric.min} - {attrDist.numeric.max}</strong></div>
                      </>
                    )}
                    {attrDist.categorical && (
                      <>
                        <div><span>Category mode</span><strong title={attrDist.categorical.mode}>{truncateText(attrDist.categorical.mode, 36)}</strong></div>
                        <div><span>Category count</span><strong>{attrDist.categorical.categories}</strong></div>
                      </>
                    )}
                  </div>
                </section>
              )}

              {errorEntries.length > 0 && (
                <section className="attribute-profile-drawer-section">
                  <div className="attribute-profile-detail-label">Current error signals</div>
                  <div className="attribute-profile-error-list">
                    {errorEntries.map(([type, pct]) => (
                      <div key={type}><span>{ERROR_TYPES[type] || type}</span><strong>{(Number(pct) * 100).toFixed(2)}%</strong></div>
                    ))}
                  </div>
                </section>
              )}

              {!hasStats && errorEntries.length === 0 && (
                <section className="attribute-profile-drawer-section">
                  <p>No additional summary statistics are available for this column.</p>
                </section>
              )}
            </div>
          )}
        </>
      )}
      </aside>
    </div>
    , document.body
  );
}

function AttributeRow({ attr, selectedAttributes, summaryData, handleToggleSelect, showFilter, onDeleteAttribute, onInspect, isInspected }) {
  const attrProfile = summaryData?.attributeProfiles?.[attr] || null;
  const columnErrors = summaryData?.columnErrors?.[attr] || {};

  function handleInspectKeyDown(event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onInspect(attr);
    }
  }

  return (
    <li className={`attribute-row ${isInspected ? "attribute-row--inspected" : ""} ${selectedAttributes.includes(attr) ? "attribute-row--selected" : ""}`} key={attr}>
      <div
        className="attribute-row-details"
        role="button"
        tabIndex={0}
        aria-label={`Explain ${attr}`}
        onClick={() => onInspect(attr)}
        onKeyDown={handleInspectKeyDown}
      >
        <div className="attribute-row-header">
          <span title={attr} className="attribute-row-name">{truncateText(attr.toLowerCase(), 22)}</span>
          <ColumnActionsMenu attr={attr} selectedAttributes={selectedAttributes} handleToggleSelect={handleToggleSelect} showFilter={showFilter} onDeleteAttribute={onDeleteAttribute} />
        </div>

        <AttributeProfileSummary profile={attrProfile} columnErrors={columnErrors} />

      </div>
    </li>
  );
}



export default function AttributeSummaryView({ setSelectedAttributes, selectedAttributes, setSortedAttributes, refreshKey = 0 }) {
  const { tableName: table_name, setTableName } = useTableName();
  const { addLoader, removeLoader } = useLoading();
  const { onWrangleExecuted } = useRepair();
  const { getLayoutedElements, setNodes, setEdges } = usePgraph();
  const { clearHighlight, clearSelection } = useSelection();
  const [sortBy, setSortBy] = useState("total");
  const [summaryData, setSummaryData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [pendingDeleteAttribute, setPendingDeleteAttribute] = useState(null);
  const [deletingAttribute, setDeletingAttribute] = useState(false);
  const [inspectedAttribute, setInspectedAttribute] = useState(null);
  const [reviewFilter, setReviewFilter] = useState("all");
  const [filterVisible, setFilterVisible] = useState(false);
  const [filterAttribute, setFilterAttribute] = useState(null);
  const [activeColumnFilters, setActiveColumnFilters] = useState([]);
  const [filterError, setFilterError] = useState("");
  const previousTableNameRef = useRef(null);

  useEffect(() => {
    try {
      const stored = JSON.parse(window.sessionStorage.getItem(COLUMN_FILTER_SESSION_KEY) || "null");
      setActiveColumnFilters(stored?.table === table_name && Array.isArray(stored.filters) ? stored.filters : []);
    } catch {
      setActiveColumnFilters([]);
    }
  }, [table_name]);

  // Fetch summary data from server
  async function fetchSummaryData() {
    setLoading(true);
    addLoader();
    try {
      const response = await queryAttributeSummaries( table_name );
      const data = response?.data ?? null;

      if (data) {
        setSummaryData(data);
        // Plot selections belong to the user. Keep an explicit selection across
        // profile refreshes only while the selected columns still exist; server
        // ranking defaults must never appear as user-made checkbox choices.
        setSelectedAttributes(prev => {
          const availableAttributes = new Set(data.attributes || []);
          return prev.filter((attribute) => (
            attribute !== "ID"
            && availableAttributes.has(attribute)
            && Boolean(data.attributeProfiles?.[attribute])
          ));
        });
      }

    } catch (err) {
      console.error(err.message || err);
    }
    finally {
      setLoading(false);
      removeLoader();
    }
  }

  // Run on mount or when table changes
  useEffect(() => {
      console.log("[AttrSummary MOUNT/table_name effect] table_name =", table_name);
    setInspectedAttribute(null);
    if (previousTableNameRef.current !== table_name) {
      setSelectedAttributes([]);
      previousTableNameRef.current = table_name;
    }
    fetchSummaryData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table_name, refreshKey]);

  
  // sortAttributes is now a pure function — no setSortedAttributes call inside.
  //  Calling setState during render (even indirectly via useMemo) caused the
  //  "Cannot update Buckaroo while rendering AttributeSummaryView" error and
  //  triggered an infinite re-render loop that crashed the app.
  const sortAttributes = useCallback((attributes = [], columnErrors = {}, currentSortBy = sortBy) => {
    return [...attributes].sort((a, b) => {
      const errorsA = columnErrors[a] || {};
      const errorsB = columnErrors[b] || {};

      const primaryA = currentSortBy === "total" ? 0 : (errorsA[currentSortBy] || 0);
      const primaryB = currentSortBy === "total" ? 0 : (errorsB[currentSortBy] || 0);

      const totalA = Object.values(errorsA).reduce((s, v) => s + v, 0);
      const totalB = Object.values(errorsB).reduce((s, v) => s + v, 0);

      if (currentSortBy === "total") return totalB - totalA;
      if (currentSortBy === "none") return totalA - totalB;

      if (primaryB !== primaryA) return primaryB - primaryA;
      return totalB - totalA;
    });
  }, [sortBy]);

  // Derived sorted attributes when summaryData or sortBy changes
  const sortedAttributes = useMemo(() => {
    if (!summaryData) return [];
    return sortAttributes(summaryData.attributes || [], summaryData.columnErrors || {}, sortBy);
  }, [summaryData, sortAttributes, sortBy]);

  const reviewCounts = useMemo(() => {
    const profiles = summaryData?.attributeProfiles || {};
    const columnErrors = summaryData?.columnErrors || {};
    const attributes = summaryData?.attributes || [];
    const counts = REVIEW_FILTERS.reduce((result, filter) => {
      result[filter.id] = attributes.filter((attribute) => matchesReviewFilter(profiles[attribute], filter.id, columnErrors[attribute])).length;
      return result;
    }, {});
    return counts;
  }, [summaryData]);

  const visibleAttributes = useMemo(
    () => sortedAttributes.filter((attribute) => matchesReviewFilter(
      summaryData?.attributeProfiles?.[attribute],
      reviewFilter,
      summaryData?.columnErrors?.[attribute]
    )),
    [reviewFilter, sortedAttributes, summaryData]
  );

  useEffect(() => {
    setSortedAttributes(sortedAttributes);
  }, [setSortedAttributes, sortedAttributes]);

  // Handlers
  function handleToggleSelect(attr) {
    setSelectedAttributes(prev => {
      const includes = prev.includes(attr);
      let next = includes ? prev.filter(a => a !== attr) : [...prev, attr];

      // keep a max of 3 as original logic
      if (next.length > 3) {
        // remove the first one
        next = next.slice(1);
      }

      return next;
    });
  }


  function handleSortClick(errorKey) {
    if (sortBy === errorKey) return;
    setSortBy(errorKey);
  }

  async function handleDeleteAttribute(attr) {
    setDeleteError(null);
    setDeletingAttribute(true);
    addLoader();
    try {
      const result = await deleteColumn(attr);
      if (!result?.success) {
        setDeleteError(result?.error || "Delete column failed.");
        return;
      }

      const pGraphResult = await getPGraph();
      if (pGraphResult?.nodes && pGraphResult?.edges) {
        const layoutNodesEdges = getLayoutedElements(pGraphResult.nodes, pGraphResult.edges);
        setNodes(layoutNodesEdges.nodes);
        setEdges(layoutNodesEdges.edges);
      }

      setSelectedAttributes(prev => prev.filter(a => a !== attr));
      setInspectedAttribute(prev => prev === attr ? null : prev);
      if (result.table_name) {
        setTableName(result.table_name);
      }
      setPendingDeleteAttribute(null);
      onWrangleExecuted?.();
    } catch (err) {
      setDeleteError(err.message || "Delete column failed.");
    } finally {
      setDeletingAttribute(false);
      removeLoader();
    }
  }

  function openColumnFilter(attr) {
    clearSelection();
    clearHighlight("open_column_filter", { column: attr });
    setFilterError("");
    setFilterAttribute(attr);
    setFilterVisible(true);
  }

  function closeColumnFilter() {
    setFilterVisible(false);
    clearSelection();
    clearHighlight("close_column_filter", { column: filterAttribute });
  }

  async function handleApplyColumnFilter(selection, selectedRows) {
    const result = await addDataFilter(table_name, selection);
    if (!result?.success) {
      throw new Error(result?.error || "Could not apply this filter.");
    }

    const nextFilters = [
      ...activeColumnFilters,
      {
        attribute: filterAttribute,
        rowCount: selectedRows,
        filterIndices: result.filterIndices || [],
      },
    ];
    setActiveColumnFilters(nextFilters);
    window.sessionStorage.setItem(
      COLUMN_FILTER_SESSION_KEY,
      JSON.stringify({ table: table_name, filters: nextFilters })
    );
    closeColumnFilter();
    onWrangleExecuted?.();
  }

  async function handleClearColumnFilters() {
    setFilterError("");
    addLoader();
    try {
      const result = await clearDataFilters([]);
      if (!result?.success) {
        setFilterError(result?.error || "Could not clear filters.");
        return;
      }
      setActiveColumnFilters([]);
      window.sessionStorage.removeItem(COLUMN_FILTER_SESSION_KEY);
      clearSelection();
      clearHighlight("clear_column_filters");
      onWrangleExecuted?.();
    } finally {
      removeLoader();
    }
  }

  async function handleSaveProfileOverride(attr, role, note) {
    const result = await saveProfileRoleOverride(attr, role, note);
    const override = result.override;
    setSummaryData((current) => {
      if (!current?.attributeProfiles?.[attr]) return current;
      return {
        ...current,
        attributeProfiles: {
          ...current.attributeProfiles,
          [attr]: {
            ...current.attributeProfiles[attr],
            userOverrideRole: override.role,
            userOverrideLabel: override.roleLabel,
            userOverrideNote: override.note,
          },
        },
      };
    });
  }

  async function handleClearProfileOverride(attr) {
    await deleteProfileRoleOverride(attr);
    setSummaryData((current) => {
      if (!current?.attributeProfiles?.[attr]) return current;
      const nextProfile = { ...current.attributeProfiles[attr] };
      delete nextProfile.userOverrideRole;
      delete nextProfile.userOverrideLabel;
      delete nextProfile.userOverrideNote;
      return {
        ...current,
        attributeProfiles: {
          ...current.attributeProfiles,
          [attr]: nextProfile,
        },
      };
    });
  }

  const inspectedProfile = inspectedAttribute ? summaryData?.attributeProfiles?.[inspectedAttribute] : null;
  const inspectedDist = inspectedAttribute ? summaryData?.attributeDistributions?.[inspectedAttribute] : null;
  const inspectedErrors = inspectedAttribute ? summaryData?.columnErrors?.[inspectedAttribute] : null;
  const profileContext = {
    totalRows: summaryData?.totalRows,
    profileSampleRows: summaryData?.attributeProfileSampleRows,
    profilesSampled: summaryData?.attributeProfilesSampled,
  };

  return (
    <CollapsiblePanel collapsed={"Attribute Summaries"} direction="left" defaultOpen={true} className="panel--attribute-summary">
    <div id="attribute-summary-root" data-tutorial-target="columns">
      <div id="attribute-sorting">
        <div className="attribute-sorting-title">Sort Attributes By</div>
        <div className="attribute-sorting-controls">
          {Object.keys(ERROR_TYPES).map(error => {
            const selected = sortBy === error;
            return (
              <div key={error} className="attribute-sorting-item" onClick={() => handleSortClick(error)}>
                <span
                  className={`attribute-sorting-swatch ${selected ? "attribute-sorting-item-color-selected" : "attribute-sorting-item-color"}`}
                  data-error-type={error}
                />
                <span>{ERROR_TYPES[error]}</span>
              </div>
            );
          })}
        </div>
      </div>

      <FilterModal
        key={`${filterAttribute || "none"}-${filterVisible ? "open" : "closed"}`}
        visible={filterVisible}
        attribute={filterAttribute}
        onClose={closeColumnFilter}
        onApply={handleApplyColumnFilter}
        errorColors={errorColors}
      />

      {activeColumnFilters.length > 0 && (
        <div className="attribute-active-filters" role="status">
          <div>
            <span>Filtered by</span>
            <strong title={activeColumnFilters.map(filter => filter.attribute).join(", ")}>
              {activeColumnFilters.map(filter => filter.attribute).join(" + ")}
            </strong>
          </div>
          <button type="button" onClick={handleClearColumnFilters}>Clear</button>
        </div>
      )}
      {filterError && <div className="attribute-filter-error" role="alert">{filterError}</div>}

      <div className="attribute-review-queue" aria-label="Profile review filters">
        {REVIEW_FILTER_GROUPS.map((group) => (
          <div className="attribute-review-filter-group" key={group.id}>
            <span className="attribute-review-filter-group-label">{group.label}</span>
            <div className="attribute-review-filter-list" role="group" aria-label={`${group.label} profiler columns`}>
              {REVIEW_FILTERS.filter((filter) => filter.group === group.id).map((filter) => (
                <button
                  key={filter.id}
                  type="button"
                  className={`attribute-review-filter attribute-review-filter--${filter.id} ${reviewFilter === filter.id ? "attribute-review-filter--active" : ""}`}
                  aria-pressed={reviewFilter === filter.id}
                  title={filter.title}
                  onClick={() => setReviewFilter(filter.id)}
                >
                  <span>{filter.label}</span>
                  <strong>{reviewCounts[filter.id] || 0}</strong>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="attribute-list">
        <ul className="attribute-summary-list">
          {deleteError && <li className="attribute-delete-error">Error: {deleteError}</li>}
          {loading && <li>Loading attribute summaries…</li>}
          {!loading && summaryData && visibleAttributes.length === 0 && (
            <li className="attribute-review-empty">No columns match this review filter.</li>
          )}
          {!loading && summaryData && visibleAttributes.map(attr => (
            <AttributeRow key={attr} attr={attr} handleToggleSelect={handleToggleSelect} selectedAttributes={selectedAttributes} summaryData={summaryData} showFilter={openColumnFilter} onDeleteAttribute={setPendingDeleteAttribute} onInspect={setInspectedAttribute} isInspected={inspectedAttribute === attr} />
          ))}
        </ul>
      </div>
    </div>
    <AttributeProfileDrawer
      key={inspectedAttribute || "no-inspected-column"}
      attr={inspectedAttribute}
      profile={inspectedProfile}
      profileContext={profileContext}
      attrDist={inspectedDist}
      columnErrors={inspectedErrors}
      onClose={() => setInspectedAttribute(null)}
      onSaveOverride={handleSaveProfileOverride}
      onClearOverride={handleClearProfileOverride}
    />
    <DeleteColumnDialog
      attribute={pendingDeleteAttribute}
      busy={deletingAttribute}
      onCancel={() => setPendingDeleteAttribute(null)}
      onConfirm={() => handleDeleteAttribute(pendingDeleteAttribute)}
    />
      </CollapsiblePanel>
  );
}
