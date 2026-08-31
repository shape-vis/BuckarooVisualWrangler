import { createContext, useContext, useState, useCallback, useRef } from "react";
import { undoWrangle, redoWrangle, createPreviews } from "../utils/serverCalls.jsx";
import { useTableName } from "./TableNameContext.jsx";
import { useLoading } from "./LoadingContext.jsx";
import { SelectionContext } from "./SelectionContext.jsx";
import { usePgraph } from "./PGraphContext.jsx";
import { useDock } from "./DockContext.jsx";

const RepairContext = createContext(null);

export function RepairProvider({ onWrangleExecuted, children }) {
    const { setTableName } = useTableName();
    const { addLoader, removeLoader } = useLoading();
    const { highlightedRowIds, highlightedCols, selectionSource, clearHighlight } =
        useContext(SelectionContext);
    // Undo and redo move the current node, so the rendered graph has to be re-pulled too
    const { refreshGraph } = usePgraph();

    // Showing and hiding the repair panel is a dock concern now that it is one of the dock's tabs
    const { revealTab, hideDock } = useDock();

    const [busy, setBusy] = useState(false);

    const closeRepairPanel = useCallback(() => {
        hideDock();
    }, [hideDock]);

    // Ref-based callback so the header can trigger RepairPanel's local handler
    const repairHandlerRef = useRef(null);

    const registerRepairHandler = useCallback((fn) => {
        repairHandlerRef.current = fn;
    }, []);

    const triggerRepairSelection = useCallback(() => {
        revealTab("repair");
        repairHandlerRef.current?.();
    }, [revealTab]);

    const handleUndo = useCallback(async () => {
        setBusy(true);
        addLoader();
        const result = await undoWrangle();
        await refreshGraph();
        setBusy(false);
        removeLoader();
        if (result?.success) {
            setTableName(result.table_name);
            clearHighlight();
            closeRepairPanel();
            onWrangleExecuted?.();
        }
        return result;
    }, [addLoader, removeLoader, setTableName, clearHighlight, closeRepairPanel, onWrangleExecuted, refreshGraph]);

    const handleRedo = useCallback(async () => {
        setBusy(true);
        addLoader();
        const result = await redoWrangle();
        await refreshGraph();
        setBusy(false);
        removeLoader();
        if (result?.success) {
            setTableName(result.table_name);
            clearHighlight();
            closeRepairPanel();
            onWrangleExecuted?.();
        }
        return result;
    }, [addLoader, removeLoader, setTableName, clearHighlight, closeRepairPanel, onWrangleExecuted, refreshGraph]);

    // Returns the raw server result so RepairPanel can set local preview state
    const requestPreviews = useCallback(async () => {
        if (!highlightedRowIds || highlightedRowIds.length === 0) return null;
        setBusy(true);
        addLoader();
        const cols = highlightedCols || [];
        const result = await createPreviews(highlightedRowIds, cols);
        setBusy(false);
        removeLoader();
        return { result, cols, selectionSource };
    }, [highlightedRowIds, highlightedCols, selectionSource, addLoader, removeLoader]);

    const hasSelection = !!(highlightedRowIds && highlightedRowIds.length > 0);

    return (
        <RepairContext.Provider value={{
            busy, setBusy,
            handleUndo, handleRedo,
            requestPreviews,
            triggerRepairSelection,
            registerRepairHandler,
            closeRepairPanel,
            hasSelection,
            onWrangleExecuted,
        }}>
            {children}
        </RepairContext.Provider>
    );
}

export function useRepair() {
    return useContext(RepairContext);
}
