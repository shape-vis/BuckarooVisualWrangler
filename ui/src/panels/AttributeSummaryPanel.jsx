import React, { useEffect, useMemo, useState, useRef } from "react";
import * as d3 from "d3";

import { queryAttributeSummaries } from "../utils/serverCalls.jsx";
import CollapsiblePanel from "../elements/CollapsiblePanel.jsx";
import { RotatedButton, StandardButton } from "../elements/Buttons.jsx";

import "./AttributeSummaryPanel.css";
import FilterModal from "../elements/FilterModal.jsx";

// Utility: truncate text to given length (preserve whole words if possible)
function truncateText(text, maxLen) {
  if (!text) return "";
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 1) + "…";
}

// Moved outside component so it's a stable reference and doesn't
// cause useMemo(errorColors) to recompute on every render
const ERROR_TYPES = {
  total: "Total Error %",
  missing: "Missing Values",
  mismatch: "Data Type Mismatch",
  anomaly: "Average Anomalies (Outliers)",
  incomplete: "Incomplete Data (< 3 points)",
  none: "None",
};

function AttributeRow({ attr, setGroupByAttribute, groupByAttribute, selectedAttributes, setSelectedAttributes, summaryData, errorColors, handleToggleSelect, showFilter }) {
  const columnErrors = summaryData?.columnErrors?.[attr] || {};
  const attrDist = summaryData?.attributeDistributions?.[attr] || {};

  const errorEntries = Object.entries(columnErrors);
  const errorSum = errorEntries.reduce((s, [_, pct]) => s + pct, 0);
  // const cleanPct = Math.max(0, 1 - errorSum);


  function handleToggleGroupBy(attr) {
    setGroupByAttribute(prev => {
      return prev === attr ? null : attr;
    });
  }  

function GroupByButton({ attr, groupByAttribute, handleToggleGroupBy, selectedAttributes, handleToggleSelect }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  // Close popup when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleOptionClick = (value) => {
    console.log("Selected:", value);
    setOpen(false);
  };

    const isSelected = selectedAttributes.includes(attr);

  return (
    <div className="popupMenuWrapper" ref={ref} >
      <StandardButton
        isSelected={open}
        onClick={() => setOpen((prev) => !prev)}
        style={{ width: "10px", height: "6px", fontSize: 14 }}
      ><span style={{position: "relative", top: "-8px"}}>...</span></StandardButton>

      <RotatedButton
        isSelected={isSelected}
        onClick={() => handleToggleSelect(attr)}
        style={{fontSize: 10, height: "34px", marginTop: "4px"}}
      >
        {isSelected ? "Selected" : "Select"}
      </RotatedButton>      

      {open && (
        <div className="popupMenu">
          <RotatedButton isSelected={groupByAttribute === attr} style={{width: "8px", height: "34px", fontSize: 9}} onClick={() => handleToggleGroupBy(attr)}>Group By</RotatedButton>
          <RotatedButton style={{width: "8px", height: "34px", fontSize: 9}} onClick={() => showFilter(attr)}>Filter</RotatedButton>
          <RotatedButton style={{width: "8px", height: "34px", fontSize: 9}} onClick={() => handleOptionClick("option3")}>Delete</RotatedButton>
        </div>
      )}
    </div>
  );
}  

  return (
    <li style={{display: "flex", flexDirection: "row", gap: 8, marginBottom: 8}} key={attr}>
      <GroupByButton attr={attr} groupByAttribute={groupByAttribute} handleToggleGroupBy={handleToggleGroupBy} selectedAttributes={selectedAttributes} handleToggleSelect={handleToggleSelect} />

      <div style={{display: "flex", flexDirection: "column", gap: 4, flexGrow: 1}}>
        <div style={{display: "flex", alignItems: "center", gap: 6}}>
          <span title={attr} style={{fontSize: 16, fontWeight: 700, marginRight: 6}}>{truncateText(attr.toLowerCase(), Math.max(5, 18 - errorEntries.length * 3))}</span>

          {errorEntries.map(([type, pct]) => (
            <span
              key={type}
              title={`${type}: ${(pct * 100).toFixed(1)}% of entries`}
              className="error-scent"
              style={{backgroundColor: errorColors(type)}}
            >
              {Math.round(pct * 100)}%
            </span>
          ))}
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



export default function AttributeSummaryView({ table_name, setSelectedAttributes, selectedAttributes, setSortedAttributes }) {
  const [groupByAttribute, setGroupByAttribute] = useState(null);
  const [sortBy, setSortBy] = useState("total");
  const [summaryData, setSummaryData] = useState(null);
  const [loading, setLoading] = useState(false);

  // // Error type labels
  // const errorTypes = {
  //   total: "Total Error %",
  //   missing: "Missing Values",
  //   mismatch: "Data Type Mismatch",
  //   anomaly: "Average Anomalies (Outliers)",
  //   incomplete: "Incomplete Data (< 3 points)",
  //   none: "None",
  // };

 // errorTypes is now ERROR_TYPES (module-level constant),
  // so this useMemo has a stable dependency and never needlessly recomputes
  const errorColors = useMemo(() => {
    return d3.scaleOrdinal()
      .domain(Object.keys(ERROR_TYPES))
      .range(["#00000000", "saddlebrown", "hotpink", "red", "gray", "steelblue"]);
  }, []);

  // Fetch summary data from server (mirrors populateDropdownFromTable)
  async function fetchSummaryData() {
    setLoading(true);
    try {
      const response = await queryAttributeSummaries( table_name );
      const data = response?.data ?? null;

      // initialize selectedAttributes from server defaults if provided
      if (data) {
        setSummaryData(data);
        const sorted = sortAttributes(data.attributes || [], data.columnErrors || {} , sortBy);
        const defaults = data.defaultAttributes && data.defaultAttributes.length > 0
          ? data.defaultAttributes
          : sorted.slice(0, 3);
        setSelectedAttributes(defaults);
      }

    } catch (err) {
      console.error(err.message || err);
    } 
    finally {
      setLoading(false);
    }
  }

  // Run on mount or when table changes
  useEffect(() => {
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

      // trigger controller update
      // controller.updateGrouping(next, groupByAttribute);
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
    <CollapsiblePanel collapsed={"Attribute Summaries"} direction="left" defaultOpen={true} style={{height: "calc(100vh - 52px)"}}>
    <div id="attribute-summary-root">
      <div id="attribute-sorting">
        <div className="attribute-sorting-title">Sort Attributes By</div>
        <div style={{display: "flex", gap: 0, marginTop: 8, flexWrap: "wrap"}}>
          {Object.keys(ERROR_TYPES).map(error => {
            const selected = sortBy === error;
            return (
              <div key={error} className="attribute-sorting-item" onClick={() => handleSortClick(error)} style={{width: "100%", alignItems: "center", cursor: "pointer"}}>
                <span
                  className={selected ? "attribute-sorting-item-color-selected" : "attribute-sorting-item-color"}
                  style={{backgroundColor: errorColors(error), width: 18, height: 18, display: "inline-block", borderRadius: 3}}
                />
                <span>{ERROR_TYPES[error]}</span>
              </div>
            );
          })}
        </div>
      </div>

      <FilterModal visible={filterVisible} attribute={filterAttribute} onClose={() => setFilterVisible(false)} onApply={() => setFilterVisible(false)} table_name={table_name} errorColors={errorColors} />

      <div className="attribute-list">
        <ul className="attribute-summary-list">
          {loading && <li>Loading attribute summaries…</li>}
          {!loading && summaryData && sortedAttributes.map(attr => (
            <AttributeRow key={attr} attr={attr} handleToggleSelect={handleToggleSelect} selectedAttributes={selectedAttributes} setSelectedAttributes={setSelectedAttributes} summaryData={summaryData} errorColors={errorColors} setGroupByAttribute={setGroupByAttribute} showFilter={() => { setFilterAttribute(attr); setFilterVisible(true); }} />
          ))}
        </ul>
      </div>
    </div>
      </CollapsiblePanel>
  );
}
