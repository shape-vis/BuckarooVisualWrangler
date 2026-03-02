



/**
 * Sends the user uploaded file to the endpoint in the server to add it to the DB
 * @param {} fileToSend the file the user is sending
 */
async function uploadFileToDB(fileToSend){
    console.log("starting upload");
        const url = "/api/upload"
        try {
            const response = await fetch(url, {
              method: "POST",
              body: fileToSend
            });
            if (!response.ok) {
                throw new Error(`Response status: ${response.status}`);
            }
            if(response.statusText === "OK"){
                return true
            }
        } catch (error) {
                console.error(error.message);
            }
}

/**
 * Get a window of data from the full datatable stored in the database
 * @returns {Promise<void>}
 * @param {string} filename the name of the file the user wants to get data from
 * @param {string} dataSize the max ID to construct the window of data from
 */
async function getSampleData(filename,dataSize) {
    console.log("starting sample fetch from db");
    const params = new URLSearchParams({filename: filename,datasize:dataSize});
    const url = `/api/get-sample?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        if (!response.ok){
            throw new Error(`Response status: ${response.status}`);
        }
        const jsonTable = await response.json();
        console.log(jsonTable[0]);
        return jsonTable;
    }
    catch (error){
        console.error(error.message)
    }
}

/**
 * Get a window of data from the full error datatable stored in the database
 * @param {string} filename the name of the file the user wants to get data from
 * @param {string} dataSize the max ID to construct the window of data from
 * @returns {Promise<void>}
 */
async function getErrorData(filename,dataSize, anomalyMethods = null) {
    console.log("starting error fetch from db");
    const methodsToSend = Array.isArray(anomalyMethods) ? anomalyMethods : getActiveAnomalyMethods();
    const rarityThreshold = getActiveRarityThreshold();
    const params = new URLSearchParams({
        filename: filename,
        datasize:dataSize,
        anomaly_methods: JSON.stringify(methodsToSend),
        rarity_threshold: String(rarityThreshold)
    });
    const url = `/api/get-errors?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        if (!response.ok){
            throw new Error(`Response status: ${response.status}`);
        }
        const jsonTable = await response.json();
        console.log(jsonTable[0]);
        return jsonTable;
    }
    catch (error){
        console.error(error.message)
    }
}

/**
 * Get the data for the 1d histogram in the view
 * @returns {Promise<void>}
 */
async function queryHistogram1d(columnName,tableName,minId,maxId,binCount) {
    console.log("1d histogram fetch");
    const methodsToSend = getActiveAnomalyMethods();
    const rarityThreshold = getActiveRarityThreshold();
    const params = new URLSearchParams({
        column:columnName,
        tablename:tableName,
        min_id:minId,
        max_id:maxId,
        bins:binCount,
        anomaly_methods: JSON.stringify(methodsToSend),
        rarity_threshold: String(rarityThreshold)});
    const url = `/api/plots/1-d-histogram?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}



/**
 * Get the data for the 2d histogram in the view from the DB
 * @param columnX
 * @param columnY
 * @param tableName
 * @param minId
 * @param maxID
 * @param bins
 * @returns {Promise<any>}
 */
async function queryHistogram2d(columnX,columnY,tableName,minId,maxID,bins) {
    console.log("1d histogram fetch");
    const methodsToSend = getActiveAnomalyMethods();
    const rarityThreshold = getActiveRarityThreshold();
    const params = new URLSearchParams({
        column_x:columnX,
        column_y:columnY,
        tablename:tableName,
        min_id: minId,
        max_id: maxID,
        x_bins: bins,
        y_bins: bins,
        anomaly_methods: JSON.stringify(methodsToSend),
        rarity_threshold: String(rarityThreshold)});
    const url = `/api/plots/2-d-histogram?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}



/**
 * Get the scatterplot data from the pandas for the view
 * @param xColumn
 * @param yColumn
 * @param minId
 * @param maxId
 * @param errorSamples
 * @param totalSamples
 * @returns {Promise<any>}
 */
export async function querySample2d(xColumn, yColumn, tableName, minId, maxId, errorSamples, totalSamples) {
    console.log("2d sample fetch");
    const methodsToSend = getActiveAnomalyMethods();
    const rarityThreshold = getActiveRarityThreshold();
    const params = new URLSearchParams({
        x_column:xColumn,
        y_column:yColumn,
        tablename:tableName,
        min_id:minId,
        max_id:maxId,
        error_sample_count:errorSamples,
        total_sample_count:totalSamples,
        anomaly_methods: JSON.stringify(methodsToSend),
        rarity_threshold: String(rarityThreshold)});

    const url = `/api/plots/scatterplot?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}

/**
 * Retrives the attribute summaries from the pandas implementation in the server
 * @param minId
 * @param maxId
 * @returns {Promise<any>}
 */
export async function queryAttributeSummaries(minId, maxId) {
    const methodsToSend = getActiveAnomalyMethods();
    const rarityThreshold = getActiveRarityThreshold();
    const params = new URLSearchParams({
        min_id:minId,
        max_id:maxId,
        tablename: localStorage.getItem("table") || "",
        anomaly_methods: JSON.stringify(methodsToSend),
        rarity_threshold: String(rarityThreshold)
    });

    const url = `/api/plots/summaries?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}


export async function wrangleRemove(xCol, minId, maxId) {
    const params = new URLSearchParams({
        min_id:minId,
        max_id:maxId,});

    const url = `/api/plots/summaries?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}


export {uploadFileToDB, getSampleData, getErrorData, queryHistogram1d, queryHistogram2d};
function getActiveAnomalyMethods() {
    const defaultMethods = ["zscore", "mad", "iqr"];
    try {
        const raw = localStorage.getItem("anomalyMethods");
        if (!raw) return defaultMethods;
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return defaultMethods;

        const normalized = parsed
            .map(method => String(method).trim().toLowerCase())
            .filter(method => ["zscore", "mad", "iqr"].includes(method));

        if (normalized.length === 0) return ["zscore"];
        return normalized;
    } catch (error) {
        return defaultMethods;
    }
}

function getActiveRarityThreshold() {
    const fallback = 0.01;
    try {
        const raw = localStorage.getItem("rarityThreshold");
        if (!raw) return fallback;
        const parsed = Number(raw);
        if (!Number.isFinite(parsed)) return fallback;
        return Math.max(0, Math.min(1, parsed));
    } catch (error) {
        return fallback;
    }
}
