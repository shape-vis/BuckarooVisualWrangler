

function numericHistogramGenerator(filteredData, col){
    const scale = d3.scaleLinear().domain([d3.min(filteredData, (d) => d[col]), d3.max(filteredData, (d) => d[col]) + 1])
    return d3.histogram().domain(scale.domain()).value(d => d[col]).thresholds(10);
}

function numericHistogram(filteredData, col){
    const scale = d3.scaleLinear().domain([d3.min(filteredData, (d) => d[col]), d3.max(filteredData, (d) => d[col]) + 1])
    const histogramGenerator = d3.histogram().domain(scale.domain()).value(d => d[col]).thresholds(10);
    return histogramGenerator(filteredData);  
}

function categoricalHistogram(filteredData, col){
    const groupedCategories = d3.group(filteredData, d => String(d[col]));
    return [...[...groupedCategories.keys()].filter(d => d !== "NaN").sort()];
}

function numeric_categorical_histograms(data, xCol){
    const numericData = data.filter(d => typeof d[xCol] === "number" && !isNaN(d[xCol]) );

    const categoricalData = data.filter(d => typeof d[xCol] !== "number" || isNaN(d[xCol]) )
                                .map(d => ({ ...d, [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] }));

    let numericBins = (numericData.length > 0) ? numericHistogram(numericData, xCol) : [];
    let categoricalBins = (categoricalData.length > 0) ? categoricalHistogram(categoricalData, xCol) : [];

    return [numericData, numericBins, categoricalData,  categoricalBins ]
}

function numeric_categorical_histograms2(data, xCol){
    const numericData = data.filter(d => typeof d[xCol] === "number" && !isNaN(d[xCol]) );

    const categoricalData = data.filter(d => typeof d[xCol] !== "number" || isNaN(d[xCol]) )
                                .map(d => ({ ...d, [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] }));

    let numericBins = (numericData.length > 0) ? numericHistogramGenerator(numericData, xCol) : (x) => [];
    let categoricalBins = (categoricalData.length > 0) ? categoricalHistogram(categoricalData, xCol) : [];

    return [numericData, numericBins, categoricalData,  categoricalBins ]
}

function numericHistogramToScale(histogram) {
    return histogram.map( d => { return { x0: d.x0, x1: d.x1 } });
}

function query_histogram1d( data, errors, xCol ) {

    console.log("query_histogram1d", data, errors, xCol);

    function find_error_items( type, bin, desc, ids ) {
        let items = []
        let counts = {}
        ids.forEach(id => {
            // console.log("id", id, errors, xCol, id in errors);
            let err = "none"
            if( xCol in errors ){
                items.push({id: id, error: id in errors[xCol] ? errors[xCol][id] : null });
                err = (id in errors[xCol]) ? counts[errors[xCol][id]] : "none"
            }
            else
                items.push({id: id, error: null });
            counts[err] = (counts[err] || 0) + 1;
        });
        let val_output = [];
        for(let key in counts){
            val_output.push({ type: type, bin: bin, desc: desc, name: key, value: counts[key] });
        }
        return [items, val_output];
    }

    let histData = [];

    const [numericData, numericBins, categoricalData,  categoricalBins] = numeric_categorical_histograms(data, xCol);

    if( numericBins.length > 0 ){

        numericBins.forEach(bin => {
            let items_counts = find_error_items("numeric", bin,String(bin.x0) + " - " + String(bin.x1), bin.map(d => d.ID));
            histData.push({
                type: "numeric",
                bin: [bin.x0, bin.x1],
                items: items_counts[0],
                counts: items_counts[1],
                length: items_counts[0].length
            });
        });
    }

    if(categoricalBins.length > 0 ){
        categoricalBins.forEach(category => {
            let tmp_items = categoricalData.filter(d => String(d[xCol]) === category).map(d => d.ID);
            let items_counts = find_error_items("categorical", category, category, tmp_items);
            histData.push({
                type: "categorical",
                bin: category,
                items: items_counts[0],
                counts: items_counts[1],
                length: items_counts[0].length
            });
        });    
    }

    const [numericDataX, numericBinsX, categoricalDataX,  categoricalBinsX] = numeric_categorical_histograms2(data, xCol);

    const xBins = numericBinsX(numericDataX);

    let ret = []
    xBins.forEach((xBin, xBinIdx) => {
        let bins = {"items": 0};
        xBin.forEach(d => {
            bins["items"] = (bins["items"] || 0) + 1;
            (errors[xCol][d.ID] || []).forEach(err => {
                bins[err] = (bins[err] || 0) + 1;
            });
        });
        ret.push({
            count: bins,
            xBin: xBinIdx,
            xType: "numeric",
        })            
    });


    if( categoricalDataX.length > 0 ){
        let bins = {}
        categoricalDataX.forEach((d) => {
            let xCat = String(d[xCol]);

            if(!(xCat in bins)){
                bins[xCat] = {"items": 0};
                ret.push({
                    count: bins[xCat],
                    xBin: xCat,
                    xType: "categorical",
                })
            }
            bins[xCat]["items"] = (bins[xCat]["items"] || 0) + 1;
            if( xCol in errors ){
                (errors[xCol][d.ID] || []).forEach(err => {
                                bins[xCat][err] = (bins[xCat][err] || 0) + 1;
                            });
            }
        });
    }    


    tmp = {
        histograms: ret,
        scaleX: { numeric: numericHistogramToScale(numericBinsX(numericDataX)), 
                    categorical: categoricalBinsX }
    }
    // console.log("query_histogram1d", tmp);
    // return histData;

    return tmp
}


function query_histogram2d(data, errors, xCol, yCol) {

    console.log("query_histogram2d", data, errors, xCol, yCol);

    function get_errors(d,xCol,yCol){
        if( errors === undefined || errors === null ) return [];
        // console.log("get_errors", errors, d, xCol, yCol);
        let curErrors = [];
        let ID = d.ID;
        if( xCol in errors && ID in errors[xCol] ) curErrors = curErrors.concat(errors[xCol][ID]);
        if( yCol in errors && ID in errors[yCol] ) curErrors = curErrors.concat(errors[yCol][ID]);
        return curErrors;
    }

    const [numericDataX, numericBinsX, categoricalDataX,  categoricalBinsX] = numeric_categorical_histograms2(data, xCol);
    const [numericDataY, numericBinsY, categoricalDataY,  categoricalBinsY] = numeric_categorical_histograms2(data, yCol);

    let numXnumY = data.filter(d =>  ( typeof d[xCol] === "number" && !isNaN(d[xCol]) ) &&  ( typeof d[yCol] === "number" && !isNaN(d[yCol]) ) );
    let numXcatY = data.filter(d =>  ( typeof d[xCol] === "number" && !isNaN(d[xCol]) ) && ( typeof d[yCol] !== "number" || isNaN(d[yCol]) ) );
    let catXnumY = data.filter(d =>  ( typeof d[xCol] !== "number" || isNaN(d[xCol]) ) && ( typeof d[yCol] === "number" && !isNaN(d[yCol]) ) );
    let catXcatY = data.filter(d =>  ( typeof d[xCol] !== "number" || isNaN(d[xCol]) ) && ( typeof d[yCol] !== "number" || isNaN(d[yCol]) ) );
                                    
    numXcatY = numXcatY.map(d => ({
        ...d,
        [yCol]: typeof d[yCol] === "boolean" ? String(d[yCol]) : d[yCol] 
    }));                                

    catXnumY = catXnumY.map(d => ({
        ...d,
        [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
    }));

    catXcatY = catXcatY.map(d => ({
        ...d,
        [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol],
        [yCol]: typeof d[yCol] === "boolean" ? String(d[yCol]) : d[yCol] 
    }));

    let ret = []

    if( numXnumY.length > 0 ){
        const xBins = numericBinsX(numXnumY);
        const yBins = numericBinsY(numXnumY);

        xBins.forEach((xBin, binIdx) => {
            xBin.forEach(d => {
                d.__xbin = binIdx
            });
        });

        yBins.forEach((yBin, binIdx) => {
            yBin.forEach(d => {
                d.__ybin = binIdx
            });
        });

        let bins = [];
        xBins.forEach((xBin, xBinIdx) => {
            bins[xBinIdx] = [];
            yBins.forEach((yBin, yBinIdx) => {
                bins[xBinIdx][yBinIdx] = {"items": 0};
                ret.push({
                    count: bins[xBinIdx][yBinIdx],
                    xBin: xBinIdx,
                    yBin: yBinIdx,
                    xType: "numeric",
                    yType: "numeric"
                })
            });
        });

        numXnumY.forEach((d) => {
            let xBinIdx = d.__xbin;
            let yBinIdx = d.__ybin;
            bins[xBinIdx][yBinIdx]["items"] = (bins[xBinIdx][yBinIdx]["items"] || 0) + 1;
            get_errors(d, xCol, yCol).forEach(err => {
                bins[xBinIdx][yBinIdx][err] = (bins[xBinIdx][yBinIdx][err] || 0) + 1;
            });
        });
    }

    if( catXcatY.length > 0 ){
        let bins = {}
        catXcatY.forEach((d) => {
            let xCat = String(d[xCol]);
            let yCat = String(d[yCol]);


            if(!(xCat in bins)){
                bins[xCat] = {};
            }
            if(!(yCat in bins[xCat])){
                bins[xCat][yCat] = {"items": 0};
                ret.push({
                    count: bins[xCat][yCat],
                    xBin: xCat,
                    yBin: yCat,
                    xType: "categorical",
                    yType: "categorical"
                })
            }
            bins[xCat][yCat]["items"] = (bins[xCat][yCat]["items"] || 0) + 1;
            get_errors(d, xCol, yCol).forEach(err => {
                bins[xCat][yCat][err] = (bins[xCat][yCat][err] || 0) + 1;
            });
        });
    }

    if( numXcatY.length > 0 ){
        const xBins = numericBinsX(numXcatY);

        let bins = []
        xBins.forEach((xBin, binIdx) => {
            bins[binIdx] = {};
            categoricalBinsY.forEach(cat => {
                bins[binIdx][cat] = {"items": 0};
                ret.push({
                    count: bins[binIdx][cat],
                    xBin: binIdx,
                    yBin: cat,
                    xType: "numeric",
                    yType: "categorical"
                })
            });
            xBin.forEach(d => {
                let yCat = String(d[yCol]);
                bins[binIdx][yCat]["items"] = (bins[binIdx][yCat]["items"] || 0) + 1;
                get_errors(d, xCol, yCol).forEach(err => {
                    bins[binIdx][yCat][err] = (bins[binIdx][yCat][err] || 0) + 1;
                });
            });
        });
    }

    if( catXnumY.length > 0 ){
        const yBins = numericBinsY(catXnumY);

        let bins = {}
        categoricalBinsX.forEach((cat, catIdx) => {
            bins[cat] = [];
            yBins.forEach((yBin, binIdxY) => {
                bins[cat][binIdxY] = {"items": 0};
                ret.push({
                    count: bins[cat][binIdxY],
                    xBin: cat,
                    yBin: binIdxY,
                    xType: "categorical",
                    yType: "numeric"
                })
            });
        });

        yBins.forEach((yBin, binIdxY) => {
            yBin.forEach(d => {
                let xCat = String(d[xCol]);
                bins[xCat][binIdxY]["items"] = (bins[xCat][binIdxY]["items"] || 0) + 1;
                get_errors(d, xCol, yCol).forEach(err => {
                    bins[xCat][binIdxY][err] = (bins[xCat][binIdxY][err] || 0) + 1;
                });
            });
        });
    }

    return {histograms: ret,
        scaleX: {numeric: numericHistogramToScale(numericBinsX(numericDataX)), categorical: categoricalBinsX},
        scaleY: {numeric: numericHistogramToScale(numericBinsY(numericDataY)), categorical: categoricalBinsY},
    };

}


function query_sample2d(data, errors, xCol, yCol, errorSamples, totalSamples ) {

    console.log("query_sample2d", data, errors, xCol, yCol, errorSamples, totalSamples);

    function get_errors(d,xCol,yCol){
        let curErrors = [];
        let ID = d.ID;
        if( xCol in errors && ID in errors[xCol] ) curErrors = curErrors.concat(errors[xCol][ID]);
        if( yCol in errors && ID in errors[yCol] ) curErrors = curErrors.concat(errors[yCol][ID]);
        return curErrors;
    }


    let errorData = data.filter( d => (xCol in errors && errors[xCol][d.ID]) || (yCol in errors && errors[yCol][d.ID]) )
    let nonErrorData = data.filter( d => !(xCol in errors && errors[xCol][d.ID]) && !(yCol in errors && errors[yCol][d.ID]) )

    // console.log("errorSamples", errorData.length, "nonErrorSamples", nonErrorData.length);

    while( errorData.length > errorSamples ){
        let idx = Math.floor(Math.random() * errorData.length);
        errorData.splice(idx, 1);
    }
    while( (errorData.length + nonErrorData.length) > totalSamples ){
        let idx = Math.floor(Math.random() * nonErrorData.length);
        nonErrorData.splice(idx, 1);
    }
    let workingData = errorData.concat(nonErrorData);

    let numXnumY = workingData.filter(d =>  ( typeof d[xCol] === "number" && !isNaN(d[xCol]) ) &&  ( typeof d[yCol] === "number" && !isNaN(d[yCol]) ) );
    let numXcatY = workingData.filter(d =>  ( typeof d[xCol] === "number" && !isNaN(d[xCol]) ) && ( typeof d[yCol] !== "number" || isNaN(d[yCol]) ) );
    let catXnumY = workingData.filter(d =>  ( typeof d[xCol] !== "number" || isNaN(d[xCol]) ) && ( typeof d[yCol] === "number" && !isNaN(d[yCol]) ) );
    let catXcatY = workingData.filter(d =>  ( typeof d[xCol] !== "number" || isNaN(d[xCol]) ) && ( typeof d[yCol] !== "number" || isNaN(d[yCol]) ) );

    let outData = []
    if( numXnumY.length > 0 ){
        numXnumY.forEach(d => {
            outData.push({
                ID: d.ID,
                xType: "numeric",
                yType: "numeric",
                x: d[xCol],
                y: d[yCol],
                errors: get_errors(d, xCol, yCol)
            });
        });
    }

    if( numXcatY.length > 0 ){
        numXcatY.forEach(d => {
            outData.push({
                ID: d.ID,
                xType: "numeric",
                yType: "categorical",
                x: d[xCol],
                y: String(d[yCol]),
                errors: get_errors(d, xCol, yCol)
            });
        });
    }

    if( catXnumY.length > 0 ){
        catXnumY.forEach(d => {
            outData.push({
                ID: d.ID,
                xType: "categorical",
                yType: "numeric",
                x: String(d[xCol]),
                y: d[yCol],
                errors: get_errors(d, xCol, yCol)
            });
        });
    }

    if( catXcatY.length > 0 ){
        catXcatY.forEach(d => {
            outData.push({
                ID: d.ID,
                xType: "categorical",
                yType: "categorical",
                x: String(d[xCol]),
                y: String(d[yCol]),
                errors: get_errors(d, xCol, yCol)
            });
        });
    }
            



    const [numericDataX, numericBinsX, categoricalDataX,  categoricalBinsX] = numeric_categorical_histograms2(workingData, xCol);
    const [numericDataY, numericBinsY, categoricalDataY,  categoricalBinsY] = numeric_categorical_histograms2(workingData, yCol);

    const scaleX = numericDataX.length > 0 ? [d3.min(numericDataX, (d) => d[xCol]), d3.max(numericDataX, (d) => d[xCol]) + 1] : [];
    const scaleY = numericDataY.length > 0 ? [d3.min(numericDataY, (d) => d[yCol]), d3.max(numericDataY, (d) => d[yCol]) + 1] : [];

    return {data: outData,
        scaleX: {numeric: scaleX, categorical: categoricalBinsX},
        scaleY: {numeric: scaleY, categorical: categoricalBinsY},
    };

}

function query_attribute_summary(controller, table) {
    // Get the column error summary from the controller model
    const columnErrors = controller.model.getColumnErrorSummary(); 
    const attributes = table.columnNames().slice(1);

    let attrDist = {};
    attributes.forEach(attr => {
        // Initialize the error counts for each attribute
        let data = table.array(attr);
        const numericData = data.filter(d => typeof d === "number" && !isNaN(d) );

        const categoricalData = data.filter(d => typeof d !== "number" || isNaN(d))
                                    .map(d => (typeof d === "boolean" ? String(d) : d));

                                            attrDist[attr] = {}
        if (numericData.length > 0){
            attrDist[attr]["numeric"] = {
                mean: d3.mean(numericData),
                min: d3.min(numericData),
                max: d3.max(numericData)
            };
        }

        if (categoricalData.length > 0){
            const categoricalCounts = d3.rollup(categoricalData, v => v.length, d => String(d));
            const modeCat = (categoricalCounts.size === 0) ? null: [...categoricalCounts].sort((a, b) => b[1] - a[1])[0][0];
            attrDist[attr]["categorical"] = {
                categories: [...categoricalCounts].length,
                mode: modeCat
            };
        }
    });

    // Return the summary data
    return {
        columnErrors: columnErrors,
        attributes: attributes,
        attributeDistributions: attrDist
    };

}

