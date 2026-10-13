import { createContext, useCallback, useContext, useState } from "react";
import { acceptCandidate as acceptOnServer, discardCandidates } from "../utils/serverCalls.jsx";
import { useLoading } from "./LoadingContext.jsx";
import { usePgraph } from "./PGraphContext.jsx";
import { useMoveToTable } from "./useMoveToTable.js";

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
    const { addLoader, removeLoader } = useLoading();
    const { refreshGraph, candidates, removeSupportNodesOf } = usePgraph();
    const moveToTable = useMoveToTable(onWrangleExecuted);

    const [busy, setBusy] = useState(false);
    const [busyId, setBusyId] = useState(null);
    const [error, setError] = useState(null);

    const dismissError = useCallback(() => setError(null), []);

    /* Runs one accept or decline, with the candidate it is about marked busy - or none, for several declined
       at once - and any earlier error cleared. Returns what work returns. */
    const runBusy = useCallback(async (id, work) => {
        setError(null);
        setBusy(true);
        setBusyId(id);
        addLoader();

        const result = await work();

        setBusy(false);
        setBusyId(null);
        removeLoader();
        return result;
    }, [addLoader, removeLoader]);

    const acceptCandidate = useCallback((table) => {
        async function accept() {
            const result = await acceptOnServer(table);
            if (!result?.success) {
                setError(result?.error || "Could not accept that candidate.");
                return result;
            }

            await refreshGraph();
            moveToTable(result.table);
            return result;
        }

        return runBusy(table, accept);
    }, [runBusy, refreshGraph, moveToTable]);

    const declineCandidates = useCallback(async (tables) => {
        if (tables.length === 0) return null;

        async function decline() {
            const result = await discardCandidates(tables);
            if (!result?.success) {
                setError(result?.error || "Could not decline that candidate.");
                return result;
            }

            removeSupportNodesOf(tables);
            await refreshGraph();
            // The session was on one of them, and the server moved it to the parent
            if (result.current) {
                moveToTable(result.current);
            }
            return result;
        }

        const busyTable = tables.length === 1 ? tables[0] : null;
        return runBusy(busyTable, decline);
    }, [runBusy, refreshGraph, removeSupportNodesOf, moveToTable]);

    const declineCandidate = useCallback((table) => declineCandidates([table]), [declineCandidates]);

    /** Decline every candidate staged under one node. */
    const declineAll = useCallback((parent) => {
        const tablesUnder = candidates
            .filter((node) => node.data?.parent === parent)
            .map((node) => node.id);
        return declineCandidates(tablesUnder);
    }, [candidates, declineCandidates]);

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
