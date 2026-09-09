import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { aiStatus, requestAiSuggestions, acceptAiSuggestion } from "../utils/serverCalls.jsx";
import { prospectiveId } from "../utils/graphTopology.js";
import { useTableName } from "./TableNameContext.jsx";
import { useLoading } from "./LoadingContext.jsx";
import { usePgraph } from "./PGraphContext.jsx";

const AISuggestionsContext = createContext(null);

/**
 * The request lifecycle for AI suggestions. PGraphContext owns the nodes themselves; this owns
 * asking for them, accepting one, and declining one.
 *
 * Accepting deliberately runs the same sequence RepairContext runs after a manual wrangle -
 * refresh the graph, move the current table, clear the selection, tell the page to re-fetch -
 * so a suggestion that is accepted lands exactly like a wrangle the user performed by hand.
 */
export function AISuggestionsProvider({ onWrangleExecuted, children }) {
    const { setTableName } = useTableName();
    const { addLoader, removeLoader } = useLoading();
    const { refreshGraph, prospectiveNodes, setProspectiveNodes, clearProspectiveNodes } = usePgraph();

    const [configured, setConfigured] = useState(false);
    const [busy, setBusy] = useState(false);
    const [busySuggestionId, setBusySuggestionId] = useState(null);
    const [pendingNode, setPendingNode] = useState(null);   // node whose request is in flight
    const [error, setError] = useState(null);
    const [notice, setNotice] = useState(null);             // the model's "nothing to repair"

    // Only the newest request may write state; an aborted one must not resurrect stale nodes.
    const requestRef = useRef(null);
    const revisionRef = useRef(0);

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
        const revision = ++revisionRef.current;

        dismissMessages();
        clearProspectiveNodes();
        setPendingNode(nodeTable);
        setBusy(true);
        addLoader();

        try {
            const result = await requestAiSuggestions(nodeTable, controller.signal);
            if (revision !== revisionRef.current) return;

            if (!result?.success) {
                setError(result?.error || "Could not get suggestions.");
                return;
            }
            if (result.no_suggestions) {
                setNotice(result.no_suggestions);
                return;
            }

            setProspectiveNodes((result.suggestions || []).map((s, index) => ({
                id: prospectiveId(nodeTable, index),
                parent: nodeTable,
                op: s.op.startsWith("delete") ? "delete" : "impute",
                label: s.label,
                reason: s.reason,
                rowCount: s.row_count,
                errorType: s.error_type,
                // Posted back verbatim on accept. The server re-derives everything from it, so
                // it is a convenience rather than something trusted.
                suggestion: {
                    op: s.op,
                    columns: s.columns,
                    target: s.target,
                    error_type: s.error_type,
                },
            })));
        } catch (e) {
            if (e.name === "AbortError") return;
            setError(String(e.message || e));
        } finally {
            if (revision === revisionRef.current) {
                setBusy(false);
                setPendingNode(null);
            }
            removeLoader();
        }
    }, [addLoader, removeLoader, clearProspectiveNodes, setProspectiveNodes, dismissMessages]);

    const acceptSuggestion = useCallback(async (suggestionNodeId) => {
        const entry = prospectiveNodes.find((s) => s.id === suggestionNodeId);
        if (!entry) return;

        dismissMessages();
        setBusy(true);
        setBusySuggestionId(suggestionNodeId);
        addLoader();

        const result = await acceptAiSuggestion(entry.parent, entry.suggestion);

        if (result?.success) {
            // Drop just this one. The rest still hang off the same parent, whose table the
            // wrangle never touched, so they stay valid and can be taken in any order.
            setProspectiveNodes((current) => current.filter((s) => s.id !== suggestionNodeId));
            await refreshGraph();
            if (result.table) setTableName(result.table);
            onWrangleExecuted?.();
        } else {
            setError(result?.error || "Could not run that wrangle.");
        }

        setBusy(false);
        setBusySuggestionId(null);
        removeLoader();
        return result;
    }, [prospectiveNodes, setProspectiveNodes, refreshGraph, setTableName,
        onWrangleExecuted, addLoader, removeLoader, dismissMessages]);

    const declineSuggestion = useCallback((suggestionNodeId) => {
        // Purely local - nothing was ever created for this, so there is nothing to undo
        setProspectiveNodes((current) => current.filter((s) => s.id !== suggestionNodeId));
        dismissMessages();
    }, [setProspectiveNodes, dismissMessages]);

    /* Suggestions describe a node as it was when they were asked for. Undo, redo, a reset, a new
       upload and a column deletion all move that ground, so drop them rather than leave the user
       looking at advice about a table that has changed underneath it. */
    const invalidate = useCallback(() => {
        requestRef.current?.abort();
        revisionRef.current += 1;
        clearProspectiveNodes();
        dismissMessages();
    }, [clearProspectiveNodes, dismissMessages]);

    return (
        <AISuggestionsContext.Provider value={{
            configured,
            busy, busySuggestionId, pendingNode,
            error, notice, dismissMessages,
            requestSuggestions, acceptSuggestion, declineSuggestion, invalidate,
        }}>
            {children}
        </AISuggestionsContext.Provider>
    );
}

export function useAISuggestions() {
    return useContext(AISuggestionsContext);
}
