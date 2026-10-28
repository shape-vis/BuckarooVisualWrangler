import { useCallback, useContext } from "react";
import { useTableName } from "./TableNameContext.jsx";
import { SelectionContext } from "./SelectionContext.jsx";

/**
 * Moving the session onto another table, the way a wrangle always lands: the current table changes, the
 * selection - made on the old table's rows - is cleared, and the page is told to re-fetch its views.
 *
 * Undo, redo, and accepting or declining a candidate all land this way.
 */
export function useMoveToTable(onWrangleExecuted) {
    const { setTableName } = useTableName();
    const { clearHighlight } = useContext(SelectionContext);

    return useCallback((table) => {
        setTableName(table);
        clearHighlight();
        onWrangleExecuted?.();
    }, [setTableName, clearHighlight, onWrangleExecuted]);
}
