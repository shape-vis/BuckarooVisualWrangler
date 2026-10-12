import { createContext, useCallback, useContext, useState } from "react";
import { acceptCandidate as acceptOnServer, discardCandidates } from "../utils/serverCalls.jsx";
import { useTableName } from "./TableNameContext.jsx";
import { useLoading } from "./LoadingContext.jsx";
import { SelectionContext } from "./SelectionContext.jsx";
import { usePgraph } from "./PGraphContext.jsx";

const CandidatesContext = createContext(null);

/**
 * Accepting and declining candidates: wrangles staged as provisional nodes of the graph, whether a way of
 * repairing the user's selection (RepairContext asks for those) or a repair the AI suggested
 * (AISuggestionsContext). Both are staged, accepted and declined the same way - see
 * app/server_utils/candidates.py - and only where they came from differs.
 *
 * Accepting runs the same sequence a manual wrangle always has - refresh the graph, move the current table,
 * clear the selection, tell the page to re-fetch - so a candidate that is accepted lands exactly like one. It
 * keeps its table name, so the sub-nodes added to it while it was staged stay with it. Declining drops the
 * node and its sub-nodes; if the session was on it, the server moves it to the parent.
 */
export function CandidatesProvider({ onWrangleExecuted, children }) {
    const { setTableName } = useTableName();
    const { addLoader, removeLoader } = useLoading();
    const { clearHighlight } = useContext(SelectionContext);
    const { refreshGraph, candidates, removeSupportNodesOf } = usePgraph();

    const [busy, setBusy] = useState(false);
    const [busyId, setBusyId] = useState(null);
    const [error, setError] = useState(null);

    const dismissError = useCallback(() => setError(null), []);

    const acceptCandidate = useCallback(async (table) => {
        setError(null);
        setBusy(true);
        setBusyId(table);
        addLoader();
        const result = await acceptOnServer(table);
        if (result?.success) {
            await refreshGraph();
            setTableName(result.table);
            clearHighlight();
            onWrangleExecuted?.();
        } else {
            setError(result?.error || "Could not accept that candidate.");
        }
        setBusy(false);
        setBusyId(null);
        removeLoader();
        return result;
    }, [refreshGraph, setTableName, clearHighlight, onWrangleExecuted, addLoader, removeLoader]);

    const declineCandidates = useCallback(async (tables) => {
        if (tables.length === 0) return null;
        setError(null);
        setBusy(true);
        setBusyId(tables.length === 1 ? tables[0] : null);
        addLoader();
        const result = await discardCandidates(tables);
        if (result?.success) {
            removeSupportNodesOf(tables);
            await refreshGraph();
            // The session was on one of them, and the server moved it to the parent
            if (result.current) {
                setTableName(result.current);
                clearHighlight();
                onWrangleExecuted?.();
            }
        } else {
            setError(result?.error || "Could not decline that candidate.");
        }
        setBusy(false);
        setBusyId(null);
        removeLoader();
        return result;
    }, [refreshGraph, removeSupportNodesOf, setTableName, clearHighlight, onWrangleExecuted, addLoader, removeLoader]);

    const declineCandidate = useCallback((table) => declineCandidates([table]), [declineCandidates]);

    /** Decline every candidate staged under one node. */
    const declineAll = useCallback((parent) => declineCandidates(
        candidates.filter((node) => node.data?.parent === parent).map((node) => node.id),
    ), [candidates, declineCandidates]);

    return (
        <CandidatesContext.Provider value={{
            candidates, busy, busyId, error, dismissError,
            acceptCandidate, declineCandidate, declineAll,
        }}>
            {children}
        </CandidatesContext.Provider>
    );
}

export function useCandidates() {
    return useContext(CandidatesContext);
}
