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
};

export default serverCalls;

if (typeof window !== "undefined") {
    window.serverCalls = serverCalls;
}
