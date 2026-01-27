// serverCalls.js
// Modernized module: named exports + default export + window compatibility
// Preserves original implementations and signatures.

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

async function queryHistogram1d(tableName,columnName,minId,maxId,binCount) {
    console.log("1d histogram fetch");
    const params = new URLSearchParams({
        column:columnName,
        tablename:tableName,
        min_id:minId,
        max_id:maxId,
        bins:binCount});
    const url = `/api/plots/1-d-histogram?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}

async function queryHistogram2d(tableName,columnX,columnY,minId,maxID,bins) {
    console.log("2d histogram fetch");
    const params = new URLSearchParams({
        column_x:columnX,
        column_y:columnY,
        tablename:tableName,
        min_id: minId,
        max_id: maxID,
        x_bins: bins,
        y_bins: bins});
    const url = `/api/plots/2-d-histogram?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}

export async function querySample2d(tableName, xColumn, yColumn, minId, maxId, errorSamples, totalSamples) {
    console.log("2d sample fetch");
    const params = new URLSearchParams({
        x_column:xColumn,
        y_column:yColumn,
        tablename:tableName,
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

export async function queryAttributeSummaries(table_name) {
    const params = new URLSearchParams({
        min_id:0,
        max_id:1000,
        tablename: table_name
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

export async function queryTopErrorRows(tableName, numRows) {
    const params = new URLSearchParams({
        tablename:tableName,
        num_rows:numRows});

    const url = `/api/plots/top-error-rows?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }   
    catch (error){
        console.error(error.message)
    }
}

async function wrangleRemove(xCol, minId, maxId) {
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

// Named exports for functions defined earlier
export {
    uploadFileToDB,
    getSampleData,
    getErrorData,
    queryHistogram1d,
    queryHistogram2d,
    wrangleRemove
};

// Default export for convenience
const serverCalls = {
    uploadFileToDB,
    getSampleData,
    getErrorData,
    queryHistogram1d,
    queryHistogram2d,
    querySample2d,
    queryAttributeSummaries,
    wrangleRemove
};

export default serverCalls;

/* Backwards compatibility: attach to window */
if (typeof window !== "undefined") {
    window.serverCalls = serverCalls;
    // also expose individual names (legacy code may call these globals)
    window.uploadFileToDB = uploadFileToDB;
    window.getSampleData = getSampleData;
    window.getErrorData = getErrorData;
    window.queryHistogram1d = queryHistogram1d;
    window.queryHistogram2d = queryHistogram2d;
    window.querySample2d = querySample2d;
    window.queryAttributeSummaries = queryAttributeSummaries;
    window.wrangleRemove = wrangleRemove;
}