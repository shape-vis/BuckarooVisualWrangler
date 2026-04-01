// serverCalls.jsx

async function uploadFileToDB(fileToSend) {
    const url = "/api/upload";
    try {
        const response = await fetch(url, { method: "POST", body: fileToSend });
        if (!response.ok) throw new Error(`Response status: ${response.status}`);
        return response.statusText === "OK";
    } catch (error) {
        console.error(error.message);
    }
}

async function getSampleData(filename, dataSize) {
    const params = new URLSearchParams({ filename, datasize: dataSize });
    try {
        const response = await fetch(`/api/get-sample?${params}`, { method: "GET" });
        if (!response.ok) throw new Error(`Response status: ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(error.message);
    }
}

async function getErrorData(filename, dataSize) {
    const params = new URLSearchParams({ filename, datasize: dataSize });
    try {
        const response = await fetch(`/api/get-errors?${params}`, { method: "GET" });
        if (!response.ok) throw new Error(`Response status: ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(error.message);
    }
}

async function queryHistogram1d(tableName, columnName, binCount) {
    const params = new URLSearchParams({ column: columnName, tablename: tableName, min_id: 0, max_id: 10000, bins: binCount });
    try {
        const response = await fetch(`/api/plots/1-d-histogram?${params}`, { method: "GET" });
        return await response.json();
    } catch (error) {
        console.error(error.message);
    }
}

async function queryHistogram2d(tableName, columnX, columnY, bins) {
    const params = new URLSearchParams({ column_x: columnX, column_y: columnY, tablename: tableName, min_id: 0, max_id: 10000, x_bins: bins, y_bins: bins });
    try {
        const response = await fetch(`/api/plots/2-d-histogram?${params}`, { method: "GET" });
        return await response.json();
    } catch (error) {
        console.error(error.message);
    }
}

export async function queryHistogram1dRange(tableName, columnName, binCount, minId, maxId) {
    const params = new URLSearchParams({ column: columnName, tablename: tableName, min_id: minId, max_id: maxId, bins: binCount });
    try {
        const response = await fetch(`/api/plots/1-d-histogram?${params}`, { method: "GET" });
        return await response.json();
    } catch (error) {
        console.error(error.message);
    }
}

export async function queryHistogram2dRange(tableName, columnX, columnY, bins, minId, maxId) {
    const params = new URLSearchParams({ column_x: columnX, column_y: columnY, tablename: tableName, min_id: minId, max_id: maxId, x_bins: bins, y_bins: bins });
    try {
        const response = await fetch(`/api/plots/2-d-histogram?${params}`, { method: "GET" });
        return await response.json();
    } catch (error) {
        console.error(error.message);
    }
}

export async function querySample2dRange(tableName, xColumn, yColumn, errorSamples, totalSamples, minId, maxId) {
    const params = new URLSearchParams({ x_column: xColumn, y_column: yColumn, tablename: tableName, min_id: minId, max_id: maxId, error_sample_count: errorSamples, total_sample_count: totalSamples });
    try {
        const response = await fetch(`/api/plots/scatterplot?${params}`, { method: "GET" });
        return await response.json();
    } catch (error) {
        console.error(error.message);
    }
}

export async function querySample2d(tableName, xColumn, yColumn, errorSamples, totalSamples) {
    const params = new URLSearchParams({ x_column: xColumn, y_column: yColumn, tablename: tableName, min_id: 0, max_id: 10000, error_sample_count: errorSamples, total_sample_count: totalSamples });
    try {
        const response = await fetch(`/api/plots/scatterplot?${params}`, { method: "GET" });
        return await response.json();
    } catch (error) {
        console.error(error.message);
    }
}

export async function queryAttributeSummaries(table_name) {
    const params = new URLSearchParams({ tablename: table_name });
    try {
        const response = await fetch(`/api/plots/summaries?${params}`, { method: "GET" });
        return await response.json();
    } catch (error) {
        console.error(error.message);
    }
}

export async function queryTopErrorRows(tableName, numRows) {
    const params = new URLSearchParams({ tablename: tableName, num_rows: numRows });
    try {
        const response = await fetch(`/api/plots/top-error-rows?${params}`, { method: "GET" });
        return await response.json();
    } catch (error) {
        console.error(error.message);
    }
}

/**
 * POST /api/wrangle/remove
 * Removes selected rows from the DB in-place.
 */
export async function wrangleRemove(table, currentSelection, cols) {
    try {
        const response = await fetch("/api/wrangle/remove", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ table, currentSelection, cols }),
        });
        return await response.json();
    } catch (error) {
        console.error("[wrangleRemove]", error.message);
    }
}

/**
 * POST /api/wrangle/impute
 * Imputes values in-place. `col` specifies which column to impute (for scatterplot/heatmap).
 */
export async function wrangleImpute(table, currentSelection, cols, col) {
    try {
        const response = await fetch("/api/wrangle/impute", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ table, currentSelection, cols, col }),
        });
        return await response.json();
    } catch (error) {
        console.error("[wrangleImpute]", error.message);
    }
}

/**
 * POST /api/wrangle/preview
 * Returns modified histogram data without writing to DB.
 * method: "remove" | "impute_x" | "impute_y"
 */
export async function wranglePreview(table, currentSelection, cols, method) {
    try {
        const response = await fetch("/api/wrangle/preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ table, currentSelection, cols, method }),
        });
        return await response.json();
    } catch (error) {
        console.error("[wranglePreview]", error.message);
    }
}

/**
 * POST /api/plots/rows-in-bin
 * Get row IDs inside a clicked histogram bin or heatmap tile.
 *
 * For 1-D:  { type:"1d", column, bin, bin_count }
 * For 2-D:  { type:"2d", column_x, column_y, x_bin, y_bin, x_bins, y_bins }
 */
export async function queryRowsInBin(params) {
    try {
        const response = await fetch("/api/plots/rows-in-bin", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(params),
        });
        return await response.json();
    } catch (error) {
        console.error("[queryRowsInBin]", error.message);
    }
}

/**
 * POST /api/plots/update-backend-attributes
 * When attributes are changed on the frontend, make sure associated active attributes are reflected on the backend.
 *
 * params: {list of removed attributes}
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
export async function queryBinsForRows(params) {
    try {
        const response = await fetch("/api/plots/bins-for-rows", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(params),
        });
        return await response.json();
    } catch (error) {
        console.error("[queryBinsForRows]", error.message);
    }
}

/**
 * POST /api/wrangle/create-previews
 * Create preview_delete and preview_impute copies of the table,
 * apply wrangling to each, re-run error detection, and return the
 * two preview table names.
 *
 * { table, row_ids, cols }
 */
export async function createPreviews(table, rowIds, cols) {
    try {
        const response = await fetch("/api/wrangle/create-previews", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ table, row_ids: rowIds, cols }),
        });
        return await response.json();
    } catch (error) {
        console.error("[createPreviews]", error.message);
    }
}

/**
 * GET /api/plots/preview-histogram
 * Fetch histogram data for a preview table (preview_delete / preview_impute).
 *
 * params shape:
 *   { type:"1d", tablename, column, bins }
 *   { type:"2d", tablename, column_x, column_y, x_bins, y_bins }
 */
export async function queryPreviewHistogram(params) {
    try {
        const qs = new URLSearchParams(params);
        const response = await fetch(`/api/plots/preview-histogram?${qs}`, { method: "GET" });
        return await response.json();
    } catch (error) {
        console.error("[queryPreviewHistogram]", error.message);
    }
}

/**
 * POST /api/wrangle/execute
 * Promote a preview table to be the main table, deleting all other previews.
 */
export async function executeWrangle(table, previewTable) {
    try {
        const response = await fetch("/api/wrangle/execute", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ table, preview_table: previewTable }),
        });
        return await response.json();
    } catch (error) {
        console.error("[executeWrangle]", error.message);
    }
}

/**
 * GET /api/plots/preview-scatterplot
 * Fetch scatterplot data for a preview table.
 *
 * params shape:
 *   { tablename, x_column, y_column, error_sample_count, total_sample_count }
 */
export async function queryPreviewScatterplot(params) {
    try {
        const qs = new URLSearchParams(params);
        const response = await fetch(`/api/plots/preview-scatterplot?${qs}`, { method: "GET" });
        return await response.json();
    } catch (error) {
        console.error("[queryPreviewScatterplot]", error.message);
    }
}

export async function resetApp() {
    try {
        const response = await fetch("/api/reset", { method: "POST" });
        return await response.json();
    } catch (error) {
        console.error("[resetApp]", error.message);
    }
}

export {
    uploadFileToDB,
    getSampleData,
    getErrorData,
    queryHistogram1d,
    queryHistogram2d,
};

const serverCalls = {
    uploadFileToDB,
    getSampleData,
    getErrorData,
    queryHistogram1d,
    queryHistogram2d,
    querySample2d,
    queryAttributeSummaries,
    queryTopErrorRows,
    wrangleRemove,
    wrangleImpute,
    wranglePreview,
    queryRowsInBin,
    queryBinsForRows,
    createPreviews,
    queryPreviewHistogram,
    queryPreviewScatterplot,
    executeWrangle,
};

export default serverCalls;

if (typeof window !== "undefined" && import.meta.env.DEV) {
    window.serverCalls = serverCalls;
}
