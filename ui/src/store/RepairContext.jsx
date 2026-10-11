import { createContext, useContext, useState, useCallback, useEffect, useMemo } from "react";
import { undoWrangle, redoWrangle, createPreviews, executeWrangle } from "../utils/serverCalls.jsx";
import { prospectiveId } from "../utils/graphTopology.js";
import { useTableName } from "./TableNameContext.jsx";
import { useLoading } from "./LoadingContext.jsx";
import { SelectionContext } from "./SelectionContext.jsx";
import { usePgraph } from "./PGraphContext.jsx";
import { useAISuggestions } from "./AISuggestionsContext.jsx";
import { useDock } from "./DockContext.jsx";
import { ViewContext } from "../pages/Buckaroo.jsx";

const RepairContext = createContext(null);

/* The ways a selection can be repaired, as the server previews them - see create-previews. Deleting removes
   the selected rows; imputing fills a column in them with its mean, or its most common value if it is
   categorical. A two-column selection can be imputed on either column. */
function repairCandidates(result, cols, selectionSource, parent, rowCount) {
    const rows = rowCount === 1 ? "the selected row" : `the ${rowCount.toLocaleString()} selected rows`;
    const fill = (column) => `Fill ${column} in ${rows} with its mean, or its most common value if it is categorical`;

    const options = result.dims === 1
        ? [
            { op: "delete", previewTable: result.preview_delete, label: "Delete rows", reason: `Remove ${rows}` },
            { op: "impute", previewTable: result.preview_impute, column: cols[0], label: `Impute ${cols[0]}`, reason: fill(cols[0]) },
        ]
        : [
            { op: "delete", previewTable: result.preview_delete, label: "Delete rows", reason: `Remove ${rows}` },
            { op: "impute", previewTable: result.preview_impute_x, column: cols[0], label: `Impute ${cols[0]}`, reason: fill(cols[0]) },
            { op: "impute", previewTable: result.preview_impute_y, column: cols[1], label: `Impute ${cols[1]}`, reason: fill(cols[1]) },
        ];

    // The preview charts draw what the selection was made on: a histogram for one column, else its 2D view
    const chartType = result.dims === 1 ? "histogram" : (selectionSource || "heatmap");

    return options.map((option, index) => ({
        ...option,
        id: prospectiveId(parent, index, "repair"),
        source: "repair",
        parent,
        rowCount,
        errorType: null,
        cols,
        chartType,
    }));
}

/**
 * Repairing a selection: undo and redo, previewing the repairs of the rows selected in the plots, and
 * running one.
 *
 * The previews are the server's - real tables, one per way of repairing the selection. Asking for them draws
 * them in the graph, as prospective nodes hanging off the current node, without opening the Repair panel;
 * the panel shows the same candidates as preview charts if the user opens it. Both read the same entries,
 * which live in the graph's prospective layer with source "repair", so accepting or declining in either is
 * seen by the other.
 *
 * A repair always runs on the current node: the server previews and promotes against its main table. So the
 * candidates are only good while the node they were made for is current, and go when it stops being.
 */
export function RepairProvider({ onWrangleExecuted, children }) {
    const { tableName, setTableName } = useTableName();
    const { addLoader, removeLoader } = useLoading();
    const { highlightedRowIds, highlightedCols, selectionSource, clearHighlight } =
        useContext(SelectionContext);
    // Undo and redo move the current node, so the rendered graph has to be re-pulled too
    const { refreshGraph, prospectiveNodes, setProspectiveNodes } = usePgraph();
    // Only one set of prospective nodes at a time, so asking for repairs retires any AI request and suggestions
    const ai = useAISuggestions();

    // Showing and hiding the repair panel is a dock concern now that it is one of the dock's tabs
    const { hideDock } = useDock();
    // The candidates are drawn in the graph, so asking for them opens the graph if it is closed
    const { openView } = useContext(ViewContext);

    const [busy, setBusy] = useState(false);
    const [busyRepairId, setBusyRepairId] = useState(null);
    const [repairError, setRepairError] = useState(null);

    const repairEntries = useMemo(
        () => prospectiveNodes.filter((entry) => entry.source === "repair"),
        [prospectiveNodes]);

    const dropRepairs = useCallback(() => {
        setProspectiveNodes((current) => current.filter((entry) => entry.source !== "repair"));
    }, [setProspectiveNodes]);

    /* Previews are of the current node's table, and running one promotes it against whatever is current at the
       time - so once the current node moves, the candidates describe a table that is no longer the one a
       repair would run on. */
    useEffect(() => {
        setProspectiveNodes((current) => (current.some((entry) => entry.source === "repair" && entry.parent !== tableName)
            ? current.filter((entry) => entry.source !== "repair" || entry.parent === tableName)
            : current));
    }, [tableName, setProspectiveNodes]);

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

    /* Preview every repair of the current selection and hang them off the current node. Replaces whatever
       prospective nodes are there - suggestions included - since only one set shows at a time. */
    const requestRepairs = useCallback(async () => {
        if (!highlightedRowIds || highlightedRowIds.length === 0 || !tableName) return;
        setRepairError(null);
        ai?.invalidate();
        dropRepairs();
        setBusy(true);
        addLoader();

        const cols = highlightedCols || [];
        const result = await createPreviews(highlightedRowIds, cols);

        setBusy(false);
        removeLoader();
        if (!result?.success) {
            setRepairError(result?.error || "Preview generation failed.");
            return;
        }
        setProspectiveNodes(repairCandidates(result, cols, selectionSource, tableName, highlightedRowIds.length));
    }, [highlightedRowIds, highlightedCols, selectionSource, tableName, ai, dropRepairs, setProspectiveNodes,
        addLoader, removeLoader]);

    /* The header's Repair button: preview the repairs into the graph. The panel is not opened - the graph is
       where the candidates are chosen - but shows them too whenever the user opens it. */
    const triggerRepairSelection = useCallback(() => {
        openView("graph");
        requestRepairs();
    }, [openView, requestRepairs]);

    /* Run one candidate. The server promotes its preview and deletes the others, so every candidate goes,
       not just this one - unlike AI suggestions, whose siblings stay valid. */
    const acceptRepair = useCallback(async (entryId) => {
        const entry = repairEntries.find((candidate) => candidate.id === entryId);
        if (!entry) return;

        setRepairError(null);
        setBusy(true);
        setBusyRepairId(entryId);
        addLoader();

        // The columns the selection was made on, so the new node's edge can name them
        const result = await executeWrangle(entry.previewTable, entry.cols ?? []);
        // The wrangle added a node, so pull the graph back down and re-layout it
        await refreshGraph();

        setBusy(false);
        setBusyRepairId(null);
        removeLoader();
        // The dock is left as the user has it: repairing no longer opens it, so running one does not close it
        if (result?.success) {
            dropRepairs();
            if (result.table) setTableName(result.table);
            clearHighlight();
            onWrangleExecuted?.();
        } else {
            setRepairError(result?.error || "Execute wrangle failed.");
        }
        return result;
    }, [repairEntries, refreshGraph, dropRepairs, setTableName, clearHighlight,
        onWrangleExecuted, addLoader, removeLoader]);

    // Purely local: the preview table stays on the server until the next preview replaces it
    const declineRepair = useCallback((entryId) => {
        setProspectiveNodes((current) => current.filter((entry) => entry.id !== entryId));
    }, [setProspectiveNodes]);

    return (
        <RepairContext.Provider value={{
            busy, setBusy, busyRepairId,
            handleUndo, handleRedo,
            requestRepairs, triggerRepairSelection,
            repairEntries, acceptRepair, declineRepair,
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
