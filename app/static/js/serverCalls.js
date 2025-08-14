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
async function getErrorData(filename,dataSize) {
    console.log("starting error fetch from db");
    const params = new URLSearchParams({filename: filename,datasize:dataSize});
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
 * Get the data for the 1d histogram in the view - pandas version
 * @returns {Promise<void>}
 */
async function queryHistogram1d(columnName,minId,maxId,binCount) {
    console.log("1d histogram fetch");
    const params = new URLSearchParams({
        column:columnName,
        min_id:minId,
        max_id:maxId,
        bins:binCount});
    const url = `/api/plots/1-d-histogram-data?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}

/**
 * Get the data for the 1d histogram in the view from the DB
 * @returns {Promise<void>}
 */
export async function queryHistogram1dDB(columnName,tableName,minId,maxID,bins) {
    console.log("1d histogram fetch");
    const params = new URLSearchParams({
        column:columnName,
        tablename:tableName,
        min_id: minId,
        max_id: maxID,
        bins: bins});
    const url = `/api/plots/1-d-histogram-data-db?${params}`
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
export async function queryHistogram2dDB(columnX,columnY,tableName,minId,maxID,bins) {
    console.log("1d histogram fetch");
    const params = new URLSearchParams({
        column_x:columnX,
        column_y:columnY,
        tablename:tableName,
        min_id: minId,
        max_id: maxID,
        x_bins: bins,
        y_bins: bins});
    const url = `/api/plots/1-d-histogram-data-db?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}

/**
 * Get the data for the 2d histogram in the view
 * @param xColumn
 * @param yColumn
 * @param inId
 * @param maxId
 * @param binCount
 * @returns {Promise<any>}
 */
async function queryHistogram2d(xColumn,yColumn,minId,maxId,binCount) {
    console.log("2d histogram fetch");
    const params = new URLSearchParams({
        x_column:xColumn,
        y_column:yColumn,
        min_id:minId,
        max_id:maxId,
        bins:binCount});
    const url = `/api/plots/2-d-histogram-data?${params}`
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
export async function querySample2d(xColumn, yColumn, minId, maxId, errorSamples, totalSamples) {
    console.log("2d sample fetch");
    const params = new URLSearchParams({
        x_column:xColumn,
        y_column:yColumn,
        min_id:minId,
        max_id:maxId,
        error_sample_count:errorSamples,
        total_sample_count:totalSamples});

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


export {uploadFileToDB,getSampleData, getErrorData, queryHistogram1d, queryHistogram2d};