import { createContext, useContext, useState, useCallback } from "react";
import { undoWrangle, redoWrangle, createPreviews } from "../utils/serverCalls.jsx";
import { useTableName } from "./TableNameContext.jsx";
import { useLoading } from "./LoadingContext.jsx";
import { SelectionContext } from "./SelectionContext.jsx";
import { usePgraph } from "./PGraphContext.jsx";
import { useDock } from "./DockContext.jsx";
import { ViewContext } from "../pages/Buckaroo.jsx";

const RepairContext = createContext(null);

// Why nothing can be repaired from the current node while it is a staged candidate
export const CANDIDATE_LOCKED = "Accept this candidate before wrangling from it";

/**
 * Repairing a selection: undo and redo, and asking for the ways the rows selected in the plots could be
 * repaired.
 *
 * Asking stages each repair as a candidate on the server - a provisional node under the current node, its
 * wrangle already run on a copy of the table - and pulls the graph, where they appear. They are accepted and
 * declined through CandidatesContext, the same as the AI's suggestions; the Repair panel lists them all.
 *
 * Nothing can be repaired from a candidate until it is accepted, so asking is refused while one is current.
 */
export function RepairProvider({ onWrangleExecuted, children }) {
    const { setTableName } = useTableName();
    const { addLoader, removeLoader } = useLoading();
    const { highlightedRowIds, highlightedCols, selectionSource, clearHighlight } =
        useContext(SelectionContext);
    // Undo and redo move the current node, so the rendered graph has to be re-pulled too
    const { refreshGraph, currentIsCandidate } = usePgraph();

    // Showing and hiding the repair panel is a dock concern now that it is one of the dock's tabs
    const { hideDock } = useDock();
    // The candidates are drawn in the graph, so asking for them opens the graph if it is closed
    const { openView } = useContext(ViewContext);

    const [busy, setBusy] = useState(false);
    const [repairError, setRepairError] = useState(null);

    const closeRepairPanel = useCallback(() => {
        hideDock();
    }, [hideDock]);

    const dismissRepairError = useCallback(() => setRepairError(null), []);

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

    const hasSelection = !!(highlightedRowIds && highlightedRowIds.length > 0);

    /* Stage every repair of the current selection as a candidate under the current node, alongside any
       candidates already staged anywhere - they stay until each is accepted or declined. */
    const requestRepairs = useCallback(async () => {
        if (!highlightedRowIds || highlightedRowIds.length === 0 || currentIsCandidate) return;
        setRepairError(null);
        setBusy(true);
        addLoader();

        const result = await createPreviews(highlightedRowIds, highlightedCols || [], selectionSource);
        if (result?.success) await refreshGraph();
        else setRepairError(result?.error || "Preview generation failed.");

        setBusy(false);
        removeLoader();
    }, [highlightedRowIds, highlightedCols, selectionSource, currentIsCandidate, refreshGraph, addLoader, removeLoader]);

    /* The header's Repair button: stage the repairs into the graph. The panel is not opened - the graph is
       where the candidates are chosen - but lists them too whenever the user opens it. */
    const triggerRepairSelection = useCallback(() => {
        openView("graph");
        requestRepairs();
    }, [openView, requestRepairs]);

    return (
        <RepairContext.Provider value={{
            busy, setBusy,
            handleUndo, handleRedo,
            requestRepairs, triggerRepairSelection,
            // Repairing is off while the current node is a candidate, and says why
            repairLocked: currentIsCandidate,
            repairError, dismissRepairError,
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
