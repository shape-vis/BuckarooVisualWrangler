import { createContext, useContext, useState, useCallback } from "react";
import { undoWrangle, redoWrangle, createPreviews } from "../utils/serverCalls.jsx";
import { useLoading } from "./LoadingContext.jsx";
import { SelectionContext } from "./SelectionContext.jsx";
import { usePgraph } from "./PGraphContext.jsx";
import { useMoveToTable } from "./useMoveToTable.js";
import { ViewContext } from "../pages/Buckaroo.jsx";

const RepairContext = createContext(null);

// Why nothing can be repaired from the current node while it is a staged candidate
export const CANDIDATE_LOCKED = "Accept this candidate before wrangling from it";

/**
 * Repairing a selection: undo and redo, and asking for the ways the rows selected in the plots could be
 * repaired.
 *
 * Asking stages each repair as a candidate on the server - a provisional node under the current node, its
 * wrangle already run on a copy of the table - and pulls the graph, where they appear as prospective nodes. They
 * are accepted and declined there, through CandidatesContext, the same as the AI's suggestions.
 *
 * Nothing can be repaired from a candidate until it is accepted, so asking is refused while one is current.
 */
export function RepairProvider({ onWrangleExecuted, children }) {
    const { addLoader, removeLoader } = useLoading();
    const { highlightedRowIds, highlightedCols, selectionSource } = useContext(SelectionContext);
    // Undo and redo move the current node, so the rendered graph has to be re-pulled too
    const { refreshGraph, currentIsCandidate } = usePgraph();
    const moveToTable = useMoveToTable(onWrangleExecuted);

    // The candidates are drawn in the graph, so asking for them opens the graph if it is closed
    const { openView } = useContext(ViewContext);

    const [busy, setBusy] = useState(false);
    const [repairError, setRepairError] = useState(null);

    const dismissRepairError = useCallback(() => setRepairError(null), []);

    /* Undo and redo alike: ask the server to step through the history, re-pull the graph, and land on the node
       it stepped to. serverCall is undoWrangle or redoWrangle. */
    const stepHistory = useCallback(async (serverCall) => {
        setBusy(true);
        addLoader();
        const result = await serverCall();
        await refreshGraph();
        setBusy(false);
        removeLoader();

        if (result?.success) {
            moveToTable(result.table_name);
        }
        return result;
    }, [addLoader, removeLoader, refreshGraph, moveToTable]);

    const handleUndo = useCallback(() => stepHistory(undoWrangle), [stepHistory]);
    const handleRedo = useCallback(() => stepHistory(redoWrangle), [stepHistory]);

    const hasSelection = Boolean(highlightedRowIds && highlightedRowIds.length > 0);

    /* Stage every repair of the current selection as a candidate under the current node, alongside any
       candidates already staged anywhere - they stay until each is accepted or declined. */
    const requestRepairs = useCallback(async () => {
        if (!hasSelection || currentIsCandidate) return;
        setRepairError(null);
        setBusy(true);
        addLoader();

        const result = await createPreviews(highlightedRowIds, highlightedCols || [], selectionSource);
        if (result?.success) {
            await refreshGraph();
        } else {
            setRepairError(result?.error || "Preview generation failed.");
        }

        setBusy(false);
        removeLoader();
    }, [hasSelection, highlightedRowIds, highlightedCols, selectionSource, currentIsCandidate, refreshGraph,
        addLoader, removeLoader]);

    /* The header's Repair button, and an error-plot sub-node's Repair selection: stage the repairs into the
       graph, where the candidates are chosen. */
    const triggerRepairSelection = useCallback(() => {
        openView("graph");
        requestRepairs();
    }, [openView, requestRepairs]);

    return (
        <RepairContext.Provider value={{
            busy,
            handleUndo, handleRedo,
            triggerRepairSelection,
            // Repairing is off while the current node is a candidate, and says why
            repairLocked: currentIsCandidate,
            repairError, dismissRepairError,
            hasSelection,
        }}>
            {children}
        </RepairContext.Provider>
    );
}

export function useRepair() {
    return useContext(RepairContext);
}
