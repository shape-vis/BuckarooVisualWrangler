// serverCalls.jsx

/* The row range a plot covers when the user has not asked for one in Settings - see RowRangeContext */
const DEFAULT_MIN_ID = 0;
const DEFAULT_MAX_ID = 10000;

/* Sends a request and reads the JSON reply. A failure - the server unreachable, a reply that is not JSON, or
   an aborted request - is thrown to the caller. */
async function fetchJson(url, options) {
    const response = await fetch(url, options);
    return await response.json();
}

/* What most calls here return when the request fails: nothing, once the failure is logged. */
function returnNothing() {
    return undefined;
}

/* What the calls whose callers show the failure return instead: the same shape a refusing server sends. */
function failureResult(error) {
    return { success: false, error: error.message };
}

/* Sends a request and reads the JSON reply. A failure is logged under the url and never thrown: the call
   returns whatever onFailure makes of the error instead. */
async function requestJson(url, options, onFailure = returnNothing) {
    try {
        return await fetchJson(url, options);
    } catch (error) {
        console.error(`[${url}]`, error.message);
        return onFailure(error);
    }
}

/* GET, with params as the query string when there are any */
function getJson(path, params, onFailure) {
    let url = path;
    if (params) {
        url = `${path}?${new URLSearchParams(params)}`;
    }
    return requestJson(url, { method: "GET" }, onFailure);
}

/* POST, with body sent as JSON when there is one. Undo, redo and reset send nothing at all. */
function postJson(url, body, onFailure) {
    const options = { method: "POST" };
    if (body !== undefined) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(body);
    }
    return requestJson(url, options, onFailure);
}


export function queryHistogram1dRange(tableName, columnName, binCount, minId = DEFAULT_MIN_ID, maxId = DEFAULT_MAX_ID) {
    return getJson("/api/plots/1-d-histogram", {
        column: columnName,
        tablename: tableName,
        min_id: minId,
        max_id: maxId,
        bins: binCount,
    });
}

export function queryHistogram1d(tableName, columnName, binCount) {
    return queryHistogram1dRange(tableName, columnName, binCount);
}

export function queryHistogram2dRange(tableName, columnX, columnY, bins, minId = DEFAULT_MIN_ID, maxId = DEFAULT_MAX_ID) {
    return getJson("/api/plots/2-d-histogram", {
        column_x: columnX,
        column_y: columnY,
        tablename: tableName,
        min_id: minId,
        max_id: maxId,
        x_bins: bins,
        y_bins: bins,
    });
}

export function queryHistogram2d(tableName, columnX, columnY, bins) {
    return queryHistogram2dRange(tableName, columnX, columnY, bins);
}

export function querySample2dRange(tableName, xColumn, yColumn, errorSamples, totalSamples,
                                   minId = DEFAULT_MIN_ID, maxId = DEFAULT_MAX_ID) {
    return getJson("/api/plots/scatterplot", {
        x_column: xColumn,
        y_column: yColumn,
        tablename: tableName,
        min_id: minId,
        max_id: maxId,
        error_sample_count: errorSamples,
        total_sample_count: totalSamples,
    });
}

export function querySample2d(tableName, xColumn, yColumn, errorSamples, totalSamples) {
    return querySample2dRange(tableName, xColumn, yColumn, errorSamples, totalSamples);
}

export function queryAttributeSummaries(table_name) {
    return getJson("/api/plots/summaries", { tablename: table_name });
}

export function queryTopErrorRows(numRows) {
    return getJson("/api/plots/top-error-rows", { num_rows: numRows });
}

/**
 * POST /api/plots/rows-in-bin
 * Get row IDs inside a clicked histogram bin or heatmap tile.
 *
 * For 1-D:  { type:"1d", column, bin, bin_count }
 * For 2-D:  { type:"2d", column_x, column_y, x_bin, y_bin, x_bins, y_bins }
 */
export function queryRowsInBin(params) {
    return postJson("/api/plots/rows-in-bin", params);
}

/**
 * POST /api/plots/update-backend-attributes
 * When attributes are changed on the frontend, make sure associated active attributes are reflected on the backend.
 *
 * params: {list of removed attributes}
 *
 * Fire and forget: nothing waits on it, and its reply is never read.
 */
export function updateBackendAttributes(params) {
    fetch("/api/plots/update-backend-attributes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params)
    }).catch(error => {
        console.error("[updateBackendAttributes]", error.message);
    });
}

/**
 * POST /api/plots/bins-for-rows
 * Given row IDs, find which bins contain them.
 *
 * For 1-D:  { type:"1d", column, row_ids, bin_count }
 * For 2-D:  { type:"2d", column_x, column_y, row_ids, x_bins, y_bins }
 */
export function queryBinsForRows(params) {
    return postJson("/api/plots/bins-for-rows", params);
}

/**
 * POST /api/wrangle/create-previews
 * Stage every way of repairing the current node's selected rows as a candidate - a provisional node under the
 * current node, its wrangle already run on a copy of its table. See app/server_utils/candidates.py.
 *
 * source is the plot a two-column selection was made on, which its candidates' preview charts draw as.
 * Returns { success, candidates: [{table, parent, op, source, label, reason, row_count, cols, chart_type}] }.
 */
export function createPreviews(rowIds, cols, source = null) {
    return postJson("/api/wrangle/create-previews", { row_ids: rowIds, cols, source }, failureResult);
}

/**
 * GET /api/plots/preview-histogram
 * Fetch histogram data for a graph node's table - a candidate's preview chart draws from this.
 *
 * params shape:
 *   { type:"1d", tablename, column, bins }
 *   { type:"2d", tablename, column_x, column_y, x_bins, y_bins }
 */
export function queryPreviewHistogram(params) {
    return getJson("/api/plots/preview-histogram", params);
}

/**
 * GET /api/plots/preview-scatterplot
 * Fetch scatterplot data for a graph node's table, as queryPreviewHistogram does.
 *
 * params shape:
 *   { tablename, x_column, y_column, error_sample_count, total_sample_count }
 */
export function queryPreviewScatterplot(params) {
    return getJson("/api/plots/preview-scatterplot", params);
}

export function undoWrangle() {
    return postJson("/api/undo");
}

export function setGraphToClickedNode(nodeId) {
    return postJson("/api/setGraphToClickedNode", { nodeId });
}

export function redoWrangle() {
    return postJson("/api/redo");
}

export function getPGraph() {
    return getJson("/api/routes/update_pgraph");
}

export function getBranchTrajectory(source, target, destination) {
    return getJson("/api/pgraph/branch_trajectory", { source, target, destination });
}

/**
 * GET /api/pgraph/compare
 * Plot data for two nodes' tables, binned on axes they share so a bin means the same range on both
 * sides. kind is "histogram" | "heatmap"; y is only sent for a heatmap. The bin count is the server's
 * default.
 *
 * Takes an AbortSignal so a superseded request - the user switching attribute mid-flight - is
 * dropped rather than raced. Rejects with an AbortError when that happens.
 */
export function getNodeComparison({ a, b, kind, x, y }, signal) {
    const params = new URLSearchParams({ a, b, kind, x });
    if (y) params.set("y", y);
    return fetchJson(`/api/pgraph/compare?${params}`, { method: "GET", signal });
}

/**
 * GET /api/pgraph/drift_detail
 * What the compare panel's Drift views draw for one node and one column: the ridgeline curves or the
 * Sankey flows, and an annotation. Takes an AbortSignal, as getNodeComparison does.
 */
export function getDriftDetail({ node, column, keep, base }, signal) {
    const params = new URLSearchParams({ node, column });
    // The categories to keep out of the Sankey's catch-all, when the panel has been told to keep any
    keep?.forEach((category) => params.append("keep", category));
    // The ancestor to measure from instead of root, when the panel has been told to use one
    if (base) params.append("base", base);
    return fetchJson(`/api/pgraph/drift_detail?${params}`, { method: "GET", signal });
}

export function resetApp() {
    return postJson("/api/reset");
}

/* What aiStatus returns when the server cannot be asked: not configured, so the AI buttons stay hidden */
function aiNotConfigured() {
    return { success: false, configured: false };
}

/**
 * GET /api/ai/status
 * Whether AI suggestions are configured at all, so the AI buttons can be hidden rather than
 * offered on every node only to fail the same way each time.
 */
export function aiStatus() {
    return getJson("/api/ai/status", undefined, aiNotConfigured);
}

/**
 * POST /api/ai/suggest
 * Ask the model what it would repair on one node, and stage each repair it suggests as a candidate under
 * that node - the same as a repair of a selection is. It does not move the session off whatever table is
 * current.
 *
 * Returns { success, candidates: [{table, parent, op, source, label, reason, row_count, error_type, cols,
 * chart_type}] } or { success, no_suggestions: "<why>" }.
 *
 * Takes an AbortSignal so a superseded request can be dropped rather than raced.
 */
export function requestAiSuggestions(nodeTable, signal) {
    return fetchJson("/api/ai/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_table: nodeTable }),
        signal,
    });
}

/**
 * POST /api/candidates/accept
 * Accept a staged candidate - a repair or an AI suggestion - into the graph for good, moving the session onto
 * it. Nothing is renamed: it keeps its table and gets its label.
 *
 * Returns { success, table, label, parent } or { success: false, error }.
 */
export function acceptCandidate(table) {
    return postJson("/api/candidates/accept", { table }, failureResult);
}

/**
 * POST /api/candidates/discard
 * Decline candidates: drop their nodes and tables. Returns { success, current } - current is the table the
 * session moved to when it was on one of them, else null.
 */
export function discardCandidates(tables) {
    return postJson("/api/candidates/discard", { tables }, failureResult);
}
