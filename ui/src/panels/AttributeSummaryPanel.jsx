import React, { useEffect, useMemo, useState, useRef } from "react";

import { queryAttributeSummaries } from "../utils/serverCalls.jsx";
import { ERROR_TYPES, ERROR_DIMENSIONS, errorColors } from "../store/errorColors.js";
import { truncateText } from "../utils/textUtils.js";
import CollapsiblePanel from "../elements/CollapsiblePanel.jsx";
import { RotatedButton, StandardButton } from "../elements/Buttons.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { useLoading } from "../store/LoadingContext.jsx";
import { usePgraph } from "../store/PGraphContext.jsx";

import "../styles/AttributeSummaryPanel.css";
import FilterModal from "../elements/FilterModal.jsx";



function GroupByButton({ attr, groupByAttribute, handleToggleGroupBy, selectedAttributes, handleToggleSelect, showFilter }) {
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
    <div className="popupMenuWrapper" ref={ref}>
      <StandardButton
        isSelected={open}
        onClick={() => setOpen((prev) => !prev)}
        className="standardButton--menu-trigger"
      ><span className="groupby-dots">...</span></StandardButton>

      <RotatedButton
        isSelected={isSelected}
        onClick={() => handleToggleSelect(attr)}
        className="rotatedButton--select-toggle"
      >
        {isSelected ? "Selected" : "Select"}
      </RotatedButton>

      {open && (
        <div className="popupMenu">
          <RotatedButton isSelected={groupByAttribute === attr} className="rotatedButton--popup-item" onClick={() => handleToggleGroupBy(attr)}>Group By</RotatedButton>
          <RotatedButton className="rotatedButton--popup-item" onClick={() => showFilter(attr)}>Filter</RotatedButton>
          <RotatedButton className="rotatedButton--popup-item" onClick={() => setOpen(false)}>Delete</RotatedButton>
        </div>
      )}
    </div>
  );
}

function formatRate(rate) {
  // null means the column does not exist on that side of the comparison, which is different from
  // existing with no errors
  if (rate === null || rate === undefined) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

/**
 * Per-error-type before/after pairs against the baseline node. Only error types that appear on at
 * least one side are listed, so a clean column stays quiet.
 */
function DeltaList({ columnErrors, baselineErrors }) {
  const rows = ERROR_DIMENSIONS
    .map(type => ({
      type,
      before: baselineErrors ? (baselineErrors[type] ?? 0) : null,
      after: columnErrors[type] ?? 0,
    }))
    .filter(({ before, after }) => before > 0 || after > 0);

  if (rows.length === 0) {
    return <div className="delta-list delta-list--clean">no errors either side</div>;
  }

  return (
    <div className="delta-list">
      {rows.map(({ type, before, after }) => {
        const change = before === null ? 0 : after - before;
        const direction = change < 0 ? "delta-after--improved"
          : change > 0 ? "delta-after--worsened"
          : "delta-after--flat";

        return (
          <div
            className="delta-pair"
            key={type}
            title={`${ERROR_TYPES[type]}: ${formatRate(before)} → ${formatRate(after)}`}
          >
            {/* .delta-type is a fixed width with an ellipsis, so let CSS do the truncating */}
            <span className="delta-type" data-error-type={type}>{type}</span>
            <span className="delta-before">{formatRate(before)}</span>
            <span className="delta-arrow">→</span>
            <span className={`delta-after ${direction}`}>{formatRate(after)}</span>
          </div>
        );
      })}
    </div>
  );
}

function AttributeRow({ attr, setGroupByAttribute, groupByAttribute, selectedAttributes, setSelectedAttributes, summaryData, handleToggleSelect, showFilter, hasBaseline, baselineErrors }) {
  const columnErrors = summaryData?.columnErrors?.[attr] || {};
  const attrDist = summaryData?.attributeDistributions?.[attr] || {};

  const errorEntries = Object.entries(columnErrors);

  function handleToggleGroupBy(attr) {
    setGroupByAttribute(prev => prev === attr ? null : attr);
  }

  return (
    <li className="attribute-row" key={attr}>
      <GroupByButton attr={attr} groupByAttribute={groupByAttribute} handleToggleGroupBy={handleToggleGroupBy} selectedAttributes={selectedAttributes} handleToggleSelect={handleToggleSelect} showFilter={showFilter} />

      <div className="attribute-row-details">
        <div className="attribute-row-header">
          <span title={attr} className="attribute-row-name">{truncateText(attr.toLowerCase(), hasBaseline ? 20 : Math.max(5, 18 - errorEntries.length * 3))}</span>

          {/* Without a baseline there is nothing to compare, so the row keeps its single-value badges */}
          {!hasBaseline && (errorEntries.length > 0
              ? errorEntries.map(([type, pct]) => (
              <span
                  key={type}
                  title={`${type}: ${(pct * 100).toFixed(1)}% of entries`}
                  className="error-scent"
                  data-error-type={type}
                >
                  {(pct * 100).toFixed(2)}%
              </span>
            ))
          : <span className="error-scent error-scent--ok">✓</span>
        )}
        </div>

        {hasBaseline && <DeltaList columnErrors={columnErrors} baselineErrors={baselineErrors} />}

        <div className="column-stats">
          {attrDist.numeric && (
              <div>Num. Mean: {Number(attrDist.numeric.mean).toFixed(2)}</div>
          )}
          {attrDist.numeric && (
              <div>Num. Range: {attrDist.numeric.min} - {attrDist.numeric.max}</div>
          )}
          {attrDist.categorical && (
              <div>Cat. Mode: <span title={attrDist.categorical.mode}>{truncateText(attrDist.categorical.mode, 13)}</span></div>
          )}
          {attrDist.categorical && (
              <div>Cat. Count: {attrDist.categorical.categories}</div>
          )}
        </div>

      </div>
    </li>
  );
}



/**
 * Says which node the deltas are measured against, and how the row count changed on the way there.
 * The row count matters: a delete wrangle drops error counts simply by dropping rows, so a big
 * improvement next to a big row loss is a different story from one at the same row count.
 */
function BaselineStrip({ baselineId, currentId, baselineRows, currentRows, isPinned, onReset }) {
  if (!baselineId) {
    return (
      <div className="baseline-strip baseline-strip--empty">
        No baseline — shift-click a node to compare
      </div>
    );
  }

  const rowChange = (baselineRows != null && currentRows != null) ? currentRows - baselineRows : null;

  return (
    <div className="baseline-strip">
      <div className="baseline-strip-line">
        <span className="baseline-strip-label">Baseline node:</span>
        <span className="baseline-strip-node" title={baselineId}>{truncateText(baselineId, 14)}</span>
        {isPinned && (
          <button className="baseline-strip-reset" onClick={onReset} title="Compare against the parent again">
            reset
          </button>
        )}
      </div>
      <div className="baseline-strip-line">
        <span className="baseline-strip-label">Comparator node:</span>
        <span className="baseline-strip-node baseline-strip-node--current" title={currentId}>
          {truncateText(currentId, 14)}
        </span>
      </div>
      {rowChange !== null && (
        <div className="baseline-strip-rows">
          {baselineRows.toLocaleString()} → {currentRows.toLocaleString()} rows
          {rowChange !== 0 && (
            <span className="baseline-strip-rowdelta">
              {" "}({rowChange > 0 ? "+" : ""}{rowChange.toLocaleString()})
            </span>
          )}
        </div>
      )}
    </div>
  );
}


export default function AttributeSummaryView({ setSelectedAttributes, selectedAttributes, setSortedAttributes }) {
  const { tableName: table_name } = useTableName();
  const { addLoader, removeLoader } = useLoading();
  const { nodes, baselineNodeId, setBaselineNodeId, resolvedBaselineId } = usePgraph();
  const [groupByAttribute, setGroupByAttribute] = useState(null);
  const [sortBy, setSortBy] = useState("total");
  const [summaryData, setSummaryData] = useState(null);
  const [loading, setLoading] = useState(false);

  // Every node's metrics ride along with the graph, so comparing two nodes is a lookup rather than a
  // request. "after" still comes from the summaries endpoint, which computes the same rate the same
  // way, so the two sides agree.
  const nodesById = useMemo(
    () => Object.fromEntries((nodes || []).map(node => [node.id, node])),
    [nodes]
  );

  const currentNode = nodesById[table_name];

  // resolvedBaselineId is shared with the graph, so the pair marked there is the pair reported here
  const baselineNode = resolvedBaselineId ? nodesById[resolvedBaselineId] : null;
  const baselineColumns = baselineNode?.data?.metrics?.columns ?? null;
  const hasBaseline = !!baselineColumns;

  // Fetch summary data from server
  async function fetchSummaryData() {
    setLoading(true);
    addLoader();
    try {
      const response = await queryAttributeSummaries( table_name );
      const data = response?.data ?? null;

      // initialize selectedAttributes from server defaults if provided
      if (data) {
        setSummaryData(data);
        const sorted = sortAttributes(data.attributes || [], data.columnErrors || {} , sortBy);
        setSelectedAttributes(prev => {
          if (prev.length > 0) return prev;
          return data.defaultAttributes && data.defaultAttributes.length > 0
            ? data.defaultAttributes
            : sorted.slice(0, 3);
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
    fetchSummaryData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table_name]);

  
  // sortAttributes is now a pure function — no setSortedAttributes call inside.
  //  Calling setState during render (even indirectly via useMemo) caused the
  //  "Cannot update Buckaroo while rendering AttributeSummaryView" error and
  //  triggered an infinite re-render loop that crashed the app.
  function sortAttributes(attributes = [], columnErrors = {}, currentSortBy = sortBy) {
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
  }

  // Derived sorted attributes when summaryData or sortBy changes
  const sortedAttributes = useMemo(() => {
    if (!summaryData) return [];
    return sortAttributes(summaryData.attributes || [], summaryData.columnErrors || {}, sortBy);
  }, [summaryData, sortBy]);

  useEffect(() => {
    setSortedAttributes(sortedAttributes);
}, [sortedAttributes]);

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

  const [filterVisible, setFilterVisible] = useState(false);
  const [filterAttribute, setFilterAttribute] = useState(null);

  return (
    <CollapsiblePanel collapsed={"Attribute Summaries"} direction="left" defaultOpen={true} className="panel--attribute-summary">
    <div id="attribute-summary-root">
      <BaselineStrip
        baselineId={hasBaseline ? resolvedBaselineId : null}
        currentId={table_name}
        baselineRows={baselineNode?.data?.metrics?.row_count}
        currentRows={currentNode?.data?.metrics?.row_count}
        isPinned={!!baselineNodeId}
        onReset={() => setBaselineNodeId(null)}
      />

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

      <FilterModal visible={filterVisible} attribute={filterAttribute} onClose={() => setFilterVisible(false)} onApply={() => setFilterVisible(false)} errorColors={errorColors} />

      <div className="attribute-list">
        <ul className="attribute-summary-list">
          {loading && <li>Loading attribute summaries…</li>}
          {!loading && summaryData && sortedAttributes.map(attr => (
            <AttributeRow key={attr} attr={attr} handleToggleSelect={handleToggleSelect} selectedAttributes={selectedAttributes} setSelectedAttributes={setSelectedAttributes} summaryData={summaryData} groupByAttribute={groupByAttribute} setGroupByAttribute={setGroupByAttribute} showFilter={() => { setFilterAttribute(attr); setFilterVisible(true); }} hasBaseline={hasBaseline} baselineErrors={baselineColumns?.[attr]} />
          ))}
        </ul>
      </div>
    </div>
      </CollapsiblePanel>
  );
}
