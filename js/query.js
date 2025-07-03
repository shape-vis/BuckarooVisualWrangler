
function query_histogram1d( data, errors, xCol ) {

    function find_error_items( bin, ids ) {
        let items = []
        let counts = {}
        ids.forEach(id => {
            items.push({id: id, error: id in errors[xCol] ? errors[xCol][id] : null });
            let err = (id in errors[xCol]) ? counts[errors[xCol][id]] : "none"
            counts[err] = (counts[err] || 0) + 1;
        });
        let val_output = [];
        for(let key in counts){
            val_output.push({ bin: bin, name: key, value: counts[key] });
        }
        return [items, val_output];
    }

    let histData = [];

    const numericData = data.filter(d => 
        typeof d[xCol] === "number" && !isNaN(d[xCol])
    );

    if(numericData.length > 0){
        const xScale = d3.scaleLinear()
            .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol]) + 1])
        
        const histogramGenerator = d3.histogram()
            .domain(xScale.domain())
            .value(d => d[xCol])
            .thresholds(10);

    
        const bins = histogramGenerator(numericData);  

        bins.forEach(bin => {
            let items_counts = find_error_items(String(bin.x0) + "-" + String(bin.x1), bin.map(d => d.ID));
            histData.push({
                type: "numeric",
                bin: [bin.x0, bin.x1],
                items: items_counts[0],
                counts: items_counts[1],
                length: items_counts[0].length
            });
        });
    }

    const nonNumericData = data.filter(d => 
        typeof d[xCol] !== "number" || isNaN(d[xCol])
    ).map(d => ({
        ...d,
        [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
    }));

    if(nonNumericData.length > 0){
        const groupedCategories = d3.group(nonNumericData, d => String(d[xCol]));
        const uniqueCategories = [...[...groupedCategories.keys()].filter(d => d !== "NaN").sort()]
        uniqueCategories.forEach(category => {
            let tmp_items = nonNumericData.filter(d => String(d[xCol]) === category).map(d => d.ID);
            let items_counts = find_error_items(category, tmp_items);
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

