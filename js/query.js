

function numeric_categorical_histograms(data, xCol){
    const numericData = data.filter(d => 
        typeof d[xCol] === "number" && !isNaN(d[xCol])
    );

    const categoricalData = data.filter(d => 
        typeof d[xCol] !== "number" || isNaN(d[xCol])
    ).map(d => ({
        ...d,
        [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
    }));

    let numericBins = [];
    let categoricalBins = [];

    if(numericData.length > 0){
        const xScale = d3.scaleLinear()
            .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol]) + 1])
        
        const histogramGenerator = d3.histogram()
            .domain(xScale.domain())
            .value(d => d[xCol])
            .thresholds(10);

        numericBins = histogramGenerator(numericData);  
    }    

    if(categoricalData.length > 0){
        const groupedCategories = d3.group(categoricalData, d => String(d[xCol]));
        categoricalBins = [...[...groupedCategories.keys()].filter(d => d !== "NaN").sort()]
    }

    return {numericData, numericBins, categoricalData,  categoricalBins};
}



function query_histogram1d( data, errors, xCol ) {

    function find_error_items( type, bin, desc, ids ) {
        let items = []
        let counts = {}
        ids.forEach(id => {
            items.push({id: id, error: id in errors[xCol] ? errors[xCol][id] : null });
            let err = (id in errors[xCol]) ? counts[errors[xCol][id]] : "none"
            counts[err] = (counts[err] || 0) + 1;
        });
        let val_output = [];
        for(let key in counts){
            val_output.push({ type: type, bin: bin, desc: desc, name: key, value: counts[key] });
        }
        return [items, val_output];
    }

    let histData = [];

    const {numericData, numericBins, categoricalData,  categoricalBins} = numeric_categorical_histograms(data, xCol);

    // const numericData = data.filter(d => 
    //     typeof d[xCol] === "number" && !isNaN(d[xCol])
    // );

    // if(numericData.length > 0){
    //     const xScale = d3.scaleLinear()
    //         .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol]) + 1])
        
    //     const histogramGenerator = d3.histogram()
    //         .domain(xScale.domain())
    //         .value(d => d[xCol])
    //         .thresholds(10);

    //     const bins = histogramGenerator(numericData);  

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

    // const nonNumericData = data.filter(d => 
    //     typeof d[xCol] !== "number" || isNaN(d[xCol])
    // ).map(d => ({
    //     ...d,
    //     [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
    // }));

    // if(nonNumericData.length > 0){
    //     const groupedCategories = d3.group(nonNumericData, d => String(d[xCol]));
    //     const uniqueCategories = [...[...groupedCategories.keys()].filter(d => d !== "NaN").sort()]
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

    return histData;
}

function query_histogram2d(data, errors, xCol, yCol) {

    // console.log(data, xCol)
    const {numericDataX, numericBinsX, categoricalDataX,  categoricalBinsX} = numeric_categorical_histograms(data, xCol);
    const {numericDataY, numericBinsY, categoricalDataY,  categoricalBinsY} = numeric_categorical_histograms(data, yCol);

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

    console.log("numXnumY", numXnumY.length, "numXcatY", numXcatY.length, "catXnumY", catXnumY.length, "catXcatY", catXcatY.length);
    


    // const numericDataX = data.filter(d => 
    //     typeof d[xCol] === "number" && !isNaN(d[xCol])
    // );

    // const nonNumericDataX = data.filter(d => 
    //     typeof d[xCol] !== "number" || isNaN(d[xCol])
    // ).map(d => ({
    //     ...d,
    //     [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
    // }));

    // const numericDataY = data.filter(d => 
    //     typeof d[yCol] === "number" && !isNaN(d[yCol])
    // );

    // const nonNumericDataY = data.filter(d => 
    //     typeof d[yCol] !== "number" || isNaN(d[yCol])
    // ).map(d => ({
    //     ...d,
    //     [yCol]: typeof d[yCol] === "boolean" ? String(d[yCol]) : d[yCol] 
    // }));


}