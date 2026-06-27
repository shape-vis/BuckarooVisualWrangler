import { useEffect } from "react";
import { useSelection } from "../store/SelectionContext.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { setInteractionDebugContext } from "../utils/interactionLogger.jsx";

export default function DebugContextBridge() {
  const { tableName } = useTableName();
  const {
    highlightedRowIds,
    highlightedCols,
    selectionSource,
    highlightRevision,
  } = useSelection();

  useEffect(() => {
    setInteractionDebugContext({
      tableName,
      selection: {
        rowIds: highlightedRowIds || [],
        rowCount: highlightedRowIds?.length || 0,
        columns: highlightedCols || [],
        source: selectionSource,
        revision: highlightRevision,
      },
    });
  }, [tableName, highlightedRowIds, highlightedCols, selectionSource, highlightRevision]);

  return null;
}
