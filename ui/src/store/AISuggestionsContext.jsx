import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { aiStatus, requestAiSuggestions } from "../utils/serverCalls.jsx";
import { useLoading } from "./LoadingContext.jsx";
import { usePgraph } from "./PGraphContext.jsx";

const AISuggestionsContext = createContext(null);

/**
 * Asking the AI for repairs. The server stages each repair it suggests as a candidate - a provisional node
 * under the node asked about, built exactly as a repair of the user's selection is - and this pulls the graph
 * where they appear. Accepting and declining them is CandidatesContext's, the same for both sources.
 *
 * Nothing can be wrangled from a candidate until it is accepted, so the server refuses to suggest for one.
 */
export function AISuggestionsProvider({ children }) {
    const { addLoader, removeLoader } = useLoading();
    const { refreshGraph } = usePgraph();

    const [configured, setConfigured] = useState(false);
    const [busy, setBusy] = useState(false);
    const [pendingNode, setPendingNode] = useState(null);   // node whose request is in flight
    const [error, setError] = useState(null);
    const [notice, setNotice] = useState(null);             // the model's "nothing to repair"

    /* The newest request's AbortController. Only that request may write state; an aborted one must not report
       on a node it was not asked about. */
    const requestRef = useRef(null);

    useEffect(() => {
        let stale = false;
        aiStatus().then((result) => {
            if (!stale) setConfigured(Boolean(result?.configured));
        });
        return () => { stale = true; };
    }, []);

    const dismissMessages = useCallback(() => {
        setError(null);
        setNotice(null);
    }, []);

    const requestSuggestions = useCallback(async (nodeTable) => {
        if (!nodeTable) return;
        requestRef.current?.abort();
        const controller = new AbortController();
        requestRef.current = controller;
        const isNewest = () => requestRef.current === controller;

        dismissMessages();
        setPendingNode(nodeTable);
        setBusy(true);
        addLoader();

        try {
            const result = await requestAiSuggestions(nodeTable, controller.signal);
            if (!isNewest()) return;
            if (!result?.success) {
                setError(result?.error || "Could not get suggestions.");
                return;
            }
            if (result.no_suggestions) {
                setNotice(result.no_suggestions);
                return;
            }
            // The suggestions are staged on the server as candidates, which arrive with the graph
            await refreshGraph();
        } catch (e) {
            if (e.name === "AbortError") return;
            setError(String(e.message || e));
        } finally {
            if (isNewest()) {
                setBusy(false);
                setPendingNode(null);
            }
            removeLoader();
        }
    }, [addLoader, removeLoader, refreshGraph, dismissMessages]);

    return (
        <AISuggestionsContext.Provider value={{
            configured,
            busy, pendingNode,
            error, notice, dismissMessages,
            requestSuggestions,
        }}>
            {children}
        </AISuggestionsContext.Provider>
    );
}

export function useAISuggestions() {
    return useContext(AISuggestionsContext);
}
