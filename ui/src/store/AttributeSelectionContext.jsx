import { createContext, useContext, useEffect, useState } from "react";
import { queryAttributeSummaries } from "../utils/serverCalls.jsx";

export const AttributeSelectionContext = createContext(null);

const MAX_COMPARISONS = 4;

export function AttributeSelectionProvider({ children }) {
  const [selectedAttributes, setSelectedAttributes] = useState([]);
  const [sortedAttributes, setSortedAttributes] = useState([]);

  const [comparisonNodeIds, setComparisonNodeIds] = useState([]);
  const [comparisonSummaries, setComparisonSummaries] = useState({});
  const [comparisonLoading, setComparisonLoading] = useState({});
  const [comparisonMode, setComparisonMode] = useState("single");

  useEffect(() => {
    let cancelled = false;

    if (comparisonNodeIds.length === 0) {
      setComparisonSummaries({});
      setComparisonLoading({});
      return;
    }

    const idsToFetch = comparisonNodeIds.filter(id => !(id in comparisonSummaries));

    if (idsToFetch.length === 0) {
      setComparisonSummaries(prev => {
        const next = {};
        let changed = false;
        for (const id of comparisonNodeIds) if (id in prev) next[id] = prev[id];
        for (const id of Object.keys(prev)) if (!(id in next)) { changed = true; break; }
        return changed ? next : prev;
      });
      return;
    }

    setComparisonLoading(prev => {
      const next = { ...prev };
      for (const id of idsToFetch) next[id] = true;
      return next;
    });

    Promise.all(idsToFetch.map(id =>
      queryAttributeSummaries(id).then(r => [id, r?.data ?? null])
    )).then(pairs => {
      if (cancelled) return;
      setComparisonSummaries(prev => {
        const next = { ...prev };
        for (const [id, data] of pairs) next[id] = data;
        for (const id of Object.keys(next)) {
          if (!comparisonNodeIds.includes(id)) delete next[id];
        }
        return next;
      });
      setComparisonLoading(prev => {
        const next = { ...prev };
        for (const [id] of pairs) delete next[id];
        return next;
      });
    });

    return () => { cancelled = true; };
  }, [comparisonNodeIds]);

  const comparisonNodeId = comparisonNodeIds[0] ?? null;
  const comparisonSummary = comparisonNodeId ? (comparisonSummaries[comparisonNodeId] ?? null) : null;
  const setComparisonNodeId = (id) => setComparisonNodeIds(id ? [id] : []);

  return (
    <AttributeSelectionContext.Provider value={{
      selectedAttributes, setSelectedAttributes,
      sortedAttributes, setSortedAttributes,
      comparisonNodeIds, setComparisonNodeIds,
      comparisonSummaries, comparisonLoading,
      comparisonMode, setComparisonMode,
      MAX_COMPARISONS,
      comparisonNodeId, setComparisonNodeId, comparisonSummary,
    }}>
      {children}
    </AttributeSelectionContext.Provider>
  );
}

export function useAttributeSelection() {
  return useContext(AttributeSelectionContext);
}
