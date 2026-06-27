import React, { useEffect, useMemo, useState, useRef } from "react";

import { deleteColumn, getPGraph, queryAttributeSummaries } from "../utils/serverCalls.jsx";
import { ERROR_TYPES, errorColors } from "../store/errorColors.js";
import { truncateText } from "../utils/textUtils.js";
import CollapsiblePanel from "../elements/CollapsiblePanel.jsx";
import { RotatedButton, StandardButton } from "../elements/Buttons.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { useLoading } from "../store/LoadingContext.jsx";
import { useRepair } from "../store/RepairContext.jsx";
import { usePgraph } from "../store/PGraphContext.jsx";

import "../styles/AttributeSummaryPanel.css";
import FilterModal from "../elements/FilterModal.jsx";

function GroupByButton({ attr, groupByAttribute, handleToggleGroupBy, selectedAttributes, handleToggleSelect, showFilter, onDeleteAttribute }) {
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
          <RotatedButton className="rotatedButton--popup-item" onClick={() => { setOpen(false); onDeleteAttribute(attr); }}>Delete</RotatedButton>
        </div>
      )}
    </div>
  );
}

function AttributeRow({ attr, setGroupByAttribute, groupByAttribute, selectedAttributes, summaryData, handleToggleSelect, showFilter, onDeleteAttribute }) {
  const columnErrors = summaryData?.columnErrors?.[attr] || {};
  const attrDist = summaryData?.attributeDistributions?.[attr] || {};

  const errorEntries = Object.entries(columnErrors);

  function handleToggleGroupBy(attr) {
    setGroupByAttribute(prev => prev === attr ? null : attr);
  }

  return (
    <li className="attribute-row" key={attr}>
      <GroupByButton attr={attr} groupByAttribute={groupByAttribute} handleToggleGroupBy={handleToggleGroupBy} selectedAttributes={selectedAttributes} handleToggleSelect={handleToggleSelect} showFilter={showFilter} onDeleteAttribute={onDeleteAttribute} />

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
              </span>
            ))
          : <span className="error-scent error-scent--ok">✓</span>
        }
        </div>

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



export default function AttributeSummaryView({ setSelectedAttributes, selectedAttributes, setSortedAttributes, refreshKey = 0 }) {
  const { tableName: table_name, setTableName } = useTableName();
  const { addLoader, removeLoader } = useLoading();
  const { onWrangleExecuted } = useRepair();
  const { getLayoutedElements, setNodes, setEdges } = usePgraph();
  const [groupByAttribute, setGroupByAttribute] = useState(null);
  const [sortBy, setSortBy] = useState("total");
  const [summaryData, setSummaryData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [deleteError, setDeleteError] = useState(null);

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
  }, [table_name, refreshKey]);

  
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

  async function handleDeleteAttribute(attr) {
    setDeleteError(null);
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
      if (result.table_name) {
        setTableName(result.table_name);
      }
      onWrangleExecuted?.();
    } catch (err) {
      setDeleteError(err.message || "Delete column failed.");
    } finally {
      removeLoader();
    }
  }

  const [filterVisible, setFilterVisible] = useState(false);
  const [filterAttribute, setFilterAttribute] = useState(null);

  return (
    <CollapsiblePanel collapsed={"Attribute Summaries"} direction="left" defaultOpen={true} className="panel--attribute-summary">
    <div id="attribute-summary-root">
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
          {deleteError && <li className="attribute-delete-error">Error: {deleteError}</li>}
          {loading && <li>Loading attribute summaries…</li>}
          {!loading && summaryData && sortedAttributes.map(attr => (
            <AttributeRow key={attr} attr={attr} handleToggleSelect={handleToggleSelect} selectedAttributes={selectedAttributes} summaryData={summaryData} groupByAttribute={groupByAttribute} setGroupByAttribute={setGroupByAttribute} showFilter={() => { setFilterAttribute(attr); setFilterVisible(true); }} onDeleteAttribute={handleDeleteAttribute} />
          ))}
        </ul>
      </div>
    </div>
      </CollapsiblePanel>
  );
}
