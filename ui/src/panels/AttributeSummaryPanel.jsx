import React, { useEffect, useMemo, useState, useRef } from "react";

import { queryAttributeSummaries } from "../utils/serverCalls.jsx";
import { ERROR_TYPES, errorColors } from "../store/errorColors.js";
import { truncateText } from "../utils/textUtils.js";
import CollapsiblePanel from "../elements/CollapsiblePanel.jsx";
import { RotatedButton, StandardButton } from "../elements/Buttons.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { useLoading } from "../store/LoadingContext.jsx";
import { useAttributeSelection } from "../store/AttributeSelectionContext.jsx";

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

function DiffSpan({ a, b, formatter = (v) => v.toFixed(2), suffix = "" }) {
  if (a == null || b == null || Number.isNaN(Number(a)) || Number.isNaN(Number(b))) return null;
  const diff = Number(b) - Number(a);
  if (diff === 0) return <span className="diff diff--neutral">±0{suffix}</span>;
  const sign = diff > 0 ? "+" : "";
  const className = diff > 0 ? "diff diff--worse" : "diff diff--better";
  return <span className={className}>{sign}{formatter(diff)}{suffix}</span>;
}

function classifyDiffs(baseValue, cmpValues) {
  const base = Number.isFinite(baseValue) ? baseValue : 0;
  const diffs = cmpValues.map(v => v == null ? null : v - base);
  const decreases = diffs.filter(d => d != null && d < 0);
  const largest = decreases.length ? Math.min(...decreases) : null;
  return diffs.map(d => {
    if (d == null) return 'na';
    if (d > 0) return 'red';
    if (d === 0) return 'neutral';
    if (d === largest) return 'green';
    return 'yellow';
  });
}

function MatrixView({ summaryData, sortedAttributes, comparisonNodeIds, comparisonSummaries,
                     comparisonLoading, showMoreInfo, groupByAttribute, setGroupByAttribute,
                     selectedAttributes, handleToggleSelect, showFilter, mainNodeId }) {
  return (
    <table className="comparison-matrix">
      <thead>
        <tr>
          <th className="comparison-matrix__attr">Attribute</th>
          <th title={mainNodeId}>{truncateText(mainNodeId ?? '', 10)}</th>
          {comparisonNodeIds.map((id, i) => (
            <th key={id} title={id}>{truncateText(id, 10)}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sortedAttributes.flatMap(attr => {
          const baseErrors = summaryData?.columnErrors?.[attr] || {};
          const errorTypes = Object.keys(baseErrors);
          const baseDist = summaryData?.attributeDistributions?.[attr] || {};
          const cmpDist = (id) => comparisonSummaries[id]?.attributeDistributions?.[attr] || {};

          const errorRows = errorTypes.map((etype, rowIdx) => {
            const baseVal = (baseErrors[etype] ?? 0) * 100;
            const cmpVals = comparisonNodeIds.map(id => {
              const summary = comparisonSummaries[id];
              if (summary == null) return null;
              const e = summary.columnErrors?.[attr];
              return e == null ? 0 : (e[etype] ?? 0) * 100;
            });
            const colors = classifyDiffs(baseVal, cmpVals);
            return (
              <tr key={`${attr}-${etype}`}>
                <td className="comparison-matrix__attr">
                  {rowIdx === 0 && (
                    <GroupByButton
                      attr={attr}
                      groupByAttribute={groupByAttribute}
                      handleToggleGroupBy={(a) => setGroupByAttribute(prev => prev === a ? null : a)}
                      selectedAttributes={selectedAttributes}
                      handleToggleSelect={handleToggleSelect}
                      showFilter={showFilter}
                    />
                  )}
                  <span className="error-scent comparison-matrix__swatch" data-error-type={etype} />
                  {rowIdx === 0
                    ? <span title={attr} className="attribute-row-name">{truncateText(attr.toLowerCase(), 14)}</span>
                    : <span className="comparison-matrix__etype">{etype}</span>}
                </td>
                <td className="cell--baseline">{baseVal.toFixed(2)}%</td>
                {cmpVals.map((v, i) => {
                  const id = comparisonNodeIds[i];
                  if (comparisonLoading[id]) return <td key={i} className="cell--loading">…</td>;
                  if (v == null) return <td key={i} className="cell--na">—</td>;
                  const becameClean = v === 0 && baseVal > 0;
                  const delta = v - baseVal;
                  const deltaText = delta === 0
                    ? '±0%'
                    : `${delta > 0 ? '+' : '−'}${Math.abs(delta).toFixed(2)}%`;
                  return (
                    <td
                      key={i}
                      className={`cell cell--${colors[i]}${becameClean ? ' cell--clean' : ''}`}
                      title={becameClean ? `Cleaned (was ${baseVal.toFixed(2)}%, now 0%)` : `Δ ${deltaText}`}
                    >
                      {becameClean && <span className="cell--clean-check">✓</span>}
                      {becameClean ? ' ' : ''}{v.toFixed(2)}%
                      <span className="cell--delta"> ({deltaText})</span>
                    </td>
                  );
                })}
              </tr>
            );
          });

          const infoRows = [];
          if (showMoreInfo) {
            const infoRow = (label, baseText, cmpTexts) => (
              <tr key={`${attr}-info-${label}`} className="comparison-matrix__info">
                <td className="comparison-matrix__attr">
                  <span className="comparison-matrix__info-label">{label}</span>
                </td>
                <td className="cell--info">{baseText}</td>
                {cmpTexts.map((t, i) => {
                  const id = comparisonNodeIds[i];
                  if (comparisonLoading[id]) return <td key={i} className="cell--loading">…</td>;
                  return <td key={i} className="cell--info">{t}</td>;
                })}
              </tr>
            );
            if (baseDist.numeric) {
              infoRows.push(infoRow("Num. Mean",
                Number(baseDist.numeric.mean).toFixed(2),
                comparisonNodeIds.map(id => {
                  const d = cmpDist(id).numeric;
                  return d ? Number(d.mean).toFixed(2) : "—";
                })));
              infoRows.push(infoRow("Num. Range",
                `${baseDist.numeric.min} – ${baseDist.numeric.max}`,
                comparisonNodeIds.map(id => {
                  const d = cmpDist(id).numeric;
                  return d ? `${d.min} – ${d.max}` : "—";
                })));
            }
            if (baseDist.categorical) {
              infoRows.push(infoRow("Cat. Count",
                String(baseDist.categorical.categories),
                comparisonNodeIds.map(id => {
                  const d = cmpDist(id).categorical;
                  return d ? String(d.categories) : "—";
                })));
              infoRows.push(infoRow("Cat. Mode",
                truncateText(String(baseDist.categorical.mode), 13),
                comparisonNodeIds.map(id => {
                  const d = cmpDist(id).categorical;
                  return d ? truncateText(String(d.mode), 13) : "—";
                })));
            }
          }

          if (errorRows.length === 0 && infoRows.length === 0) return [];
          return [...errorRows, ...infoRows];
        })}
      </tbody>
    </table>
  );
}

function AttributeRow({ attr, setGroupByAttribute, groupByAttribute, selectedAttributes, setSelectedAttributes, summaryData, comparisonSummary, handleToggleSelect, showFilter }) {
  const columnErrors = summaryData?.columnErrors?.[attr] || {};
  const attrDist = summaryData?.attributeDistributions?.[attr] || {};
  const cmpColumnErrors = comparisonSummary?.columnErrors?.[attr] || {};
  const cmpAttrDist = comparisonSummary?.attributeDistributions?.[attr] || {};
  const showDiff = !!comparisonSummary;

  const errorEntries = Object.entries(columnErrors);

  function handleToggleGroupBy(attr) {
    setGroupByAttribute(prev => prev === attr ? null : attr);
  }

  return (
    <li className="attribute-row" key={attr}>
      <GroupByButton attr={attr} groupByAttribute={groupByAttribute} handleToggleGroupBy={handleToggleGroupBy} selectedAttributes={selectedAttributes} handleToggleSelect={handleToggleSelect} showFilter={showFilter} />

      <div className="attribute-row-details">
        <div className="attribute-row-header">
          <span title={attr} className="attribute-row-name">{truncateText(attr.toLowerCase(), Math.max(5, 18 - errorEntries.length * 3))}</span>

          {errorEntries.length > 0
              ? errorEntries.map(([type, pct]) => (
              <span
                  key={type}
                  title={`${type}: ${(pct * 100).toFixed(1)}% of entries`}
                  className="error-scent"
                  data-error-type={type}
                >
                  {(pct * 100).toFixed(2)}%
                  {showDiff && (
                    <DiffSpan
                      a={pct * 100}
                      b={(cmpColumnErrors[type] ?? 0) * 100}
                      formatter={(v) => v.toFixed(2)}
                      suffix="%"
                    />
                  )}
              </span>
            ))
          : <span className="error-scent error-scent--ok">✓</span>
        }
        </div>

        <div className="column-stats">
          {attrDist.numeric && (
              <div>
                Num. Mean: {Number(attrDist.numeric.mean).toFixed(2)}
                {showDiff && cmpAttrDist.numeric && (
                  <DiffSpan a={attrDist.numeric.mean} b={cmpAttrDist.numeric.mean} />
                )}
              </div>
          )}
          {attrDist.numeric && (
              <div>
                Num. Range: {attrDist.numeric.min} - {attrDist.numeric.max}
                {showDiff && cmpAttrDist.numeric && (
                  <>
                    <DiffSpan a={attrDist.numeric.min} b={cmpAttrDist.numeric.min} />
                    <DiffSpan a={attrDist.numeric.max} b={cmpAttrDist.numeric.max} />
                  </>
                )}
              </div>
          )}
          {attrDist.categorical && (
              <div>Cat. Mode: <span title={attrDist.categorical.mode}>{truncateText(attrDist.categorical.mode, 13)}</span></div>
          )}
          {attrDist.categorical && (
              <div>
                Cat. Count: {attrDist.categorical.categories}
                {showDiff && cmpAttrDist.categorical && (
                  <DiffSpan
                    a={attrDist.categorical.categories}
                    b={cmpAttrDist.categorical.categories}
                    formatter={(v) => v.toString()}
                  />
                )}
              </div>
          )}
        </div>

      </div>
    </li>
  );
}



export default function AttributeSummaryView() {
  const { tableName: table_name } = useTableName();
  const { addLoader, removeLoader } = useLoading();
  const {
    selectedAttributes, setSelectedAttributes, setSortedAttributes,
    comparisonSummary,
    comparisonNodeIds, comparisonSummaries, comparisonLoading,
    comparisonMode, setComparisonMode,
  } = useAttributeSelection();
  const [showMoreInfo, setShowMoreInfo] = useState(false);
  const [groupByAttribute, setGroupByAttribute] = useState(null);
  const [sortBy, setSortBy] = useState("total");
  const [summaryData, setSummaryData] = useState(null);
  const [loading, setLoading] = useState(false);

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

  const [panelWidth, setPanelWidth] = useState(280);
  const rootRef = useRef(null);

  const handleResizeMouseDown = (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = rootRef.current?.getBoundingClientRect().width ?? panelWidth;

    const onMove = (ev) => {
      const next = Math.max(220, Math.min(800, startWidth + (ev.clientX - startX)));
      setPanelWidth(next);
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  return (
    <CollapsiblePanel collapsed={"Attribute Summaries"} direction="left" defaultOpen={true} className="panel--attribute-summary">
    <div id="attribute-summary-root" ref={rootRef} style={{ flex: `0 0 ${panelWidth}px`, width: panelWidth, position: "relative" }}>
      <div className="comparison-mode-toggle">
        <span className="comparison-mode-title">Node Attribute Comparison</span>
        <div className="comparison-mode-tabs">
          <button
            type="button"
            className={`comparison-mode-tab ${comparisonMode === 'single' ? 'comparison-mode-tab--active' : ''}`}
            onClick={() => setComparisonMode('single')}
          >Single</button>
          <button
            type="button"
            className={`comparison-mode-tab ${comparisonMode === 'multi' ? 'comparison-mode-tab--active' : ''}`}
            onClick={() => setComparisonMode('multi')}
          >Multi</button>
        </div>
      </div>

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
        {comparisonMode === 'multi' && (
          <button
            type="button"
            className={`more-info-toggle ${showMoreInfo ? 'more-info-toggle--active' : ''}`}
            onClick={() => setShowMoreInfo(v => !v)}
          >{showMoreInfo ? '− More Info' : '+ More Info'}</button>
        )}
        {comparisonMode === 'single' ? (
          <ul className="attribute-summary-list">
            {loading && <li>Loading attribute summaries…</li>}
            {!loading && summaryData && sortedAttributes.map(attr => (
              <AttributeRow key={attr} attr={attr} handleToggleSelect={handleToggleSelect} selectedAttributes={selectedAttributes} setSelectedAttributes={setSelectedAttributes} summaryData={summaryData} comparisonSummary={comparisonSummary} groupByAttribute={groupByAttribute} setGroupByAttribute={setGroupByAttribute} showFilter={() => { setFilterAttribute(attr); setFilterVisible(true); }} />
            ))}
          </ul>
        ) : (
          <>
            {loading && <div>Loading attribute summaries…</div>}
            {!loading && summaryData && (
              <MatrixView
                summaryData={summaryData}
                sortedAttributes={sortedAttributes}
                comparisonNodeIds={comparisonNodeIds}
                comparisonSummaries={comparisonSummaries}
                comparisonLoading={comparisonLoading}
                showMoreInfo={showMoreInfo}
                groupByAttribute={groupByAttribute}
                setGroupByAttribute={setGroupByAttribute}
                selectedAttributes={selectedAttributes}
                handleToggleSelect={handleToggleSelect}
                showFilter={(a) => { setFilterAttribute(a); setFilterVisible(true); }}
                mainNodeId={table_name}
              />
            )}
          </>
        )}
      </div>

      <div
        className="attribute-summary-resize-handle"
        onMouseDown={handleResizeMouseDown}
        title="Drag to resize"
      />
    </div>
      </CollapsiblePanel>
  );
}
