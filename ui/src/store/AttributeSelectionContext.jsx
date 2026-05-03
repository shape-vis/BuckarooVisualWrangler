import { createContext, useContext, useEffect, useState } from "react";
import { queryAttributeSummaries } from "../utils/serverCalls.jsx";

export const AttributeSelectionContext = createContext(null);

export function AttributeSelectionProvider({ children }) {
  const [selectedAttributes, setSelectedAttributes] = useState([]);
  const [sortedAttributes, setSortedAttributes] = useState([]);
  const [comparisonNodeId, setComparisonNodeId] = useState(null);
  const [comparisonSummary, setComparisonSummary] = useState(null);

  useEffect(() => {
    if (!comparisonNodeId) {
      setComparisonSummary(null);
      return;
    }
    let cancelled = false;
    (async () => {
      const response = await queryAttributeSummaries(comparisonNodeId);
      if (cancelled) return;
      setComparisonSummary(response?.data ?? null);
    })();
    return () => { cancelled = true; };
  }, [comparisonNodeId]);

  return (
    <AttributeSelectionContext.Provider value={{
      selectedAttributes, setSelectedAttributes,
      sortedAttributes, setSortedAttributes,
      comparisonNodeId, setComparisonNodeId,
      comparisonSummary,
    }}>
      {children}
    </AttributeSelectionContext.Provider>
  );
}

export function useAttributeSelection() {
  return useContext(AttributeSelectionContext);
}
