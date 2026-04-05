import { createContext, useContext, useState, useCallback, useRef } from "react";
import { undoWrangle, redoWrangle, createPreviews } from "./serverCalls.jsx";
import { useTableName } from "./TableNameContext.jsx";
import { useLoading } from "./LoadingContext.jsx";
import { SelectionContext } from "./SelectionContext.jsx";

const RepairContext = createContext(null);

export function RepairProvider({ onWrangleExecuted, children }) {
    const { setTableName } = useTableName();
    const { addLoader, removeLoader } = useLoading();
    const { highlightedRowIds, highlightedCols, selectionSource, clearHighlight } =
        useContext(SelectionContext);

    const [busy, setBusy] = useState(false);
    const [repairPanelOpenTrigger, setRepairPanelOpenTrigger] = useState(0);
    const [repairPanelCloseTrigger, setRepairPanelCloseTrigger] = useState(0);

    const closeRepairPanel = useCallback(() => {
        setRepairPanelCloseTrigger(c => c + 1);
    }, []);

    // Ref-based callback so the header can trigger RepairPanel's local handler
    const repairHandlerRef = useRef(null);

    const registerRepairHandler = useCallback((fn) => {
        repairHandlerRef.current = fn;
    }, []);

    const triggerRepairSelection = useCallback(() => {
        setRepairPanelOpenTrigger(c => c + 1);
        repairHandlerRef.current?.();
    }, []);

    const handleUndo = useCallback(async () => {
        setBusy(true);
        addLoader();
        const result = await undoWrangle();
        setBusy(false);
        removeLoader();
        if (result?.success) {
            setTableName(result.table_name);
            clearHighlight();
            closeRepairPanel();
            onWrangleExecuted?.();
        }
        return result;
    }, [addLoader, removeLoader, setTableName, clearHighlight, closeRepairPanel, onWrangleExecuted]);

    const handleRedo = useCallback(async () => {
        setBusy(true);
        addLoader();
        const result = await redoWrangle();
        setBusy(false);
        removeLoader();
        if (result?.success) {
            setTableName(result.table_name);
            clearHighlight();
            closeRepairPanel();
            onWrangleExecuted?.();
        }
        return result;
    }, [addLoader, removeLoader, setTableName, clearHighlight, closeRepairPanel, onWrangleExecuted]);

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
            repairPanelOpenTrigger,
            repairPanelCloseTrigger,
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
