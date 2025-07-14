


function createTooltip( target_objects, html_function, left_click_handler = (d)=>{}, right_click_handler = (d)=>{}, double_click_handler = (d)=>{} ) {

    const tooltip = d3.select("#tooltip");
    target_objects.on("mouseover", function(event, d) {
            d3.select(this).attr("opacity", 0.5)

            tooltip.style("display", "block")
                .html(html_function(d) )
                .style("left", `${event.pageX + 10}px`)
                .style("top", `${event.pageY + 10}px`);
        })
        .on("mousemove", function(event) {
            tooltip
                .style("left", `${event.pageX + 10}px`)
                .style("top", `${event.pageY + 10}px`);
        })
        .on("mouseout", function() {
            d3.select(this).attr("opacity", 1)
            tooltip.style("display", "none");
        })
        .on("click", function (event, d) {
            if(left_click_handler) left_click_handler(d, event);
        })
        .on("contextmenu", function(event, d) {
            event.preventDefault(); // Prevent default context menu
            if(right_click_handler) right_click_handler(d);
            return false;
        })
        .on("dblclick", function(event, d) {
            if(double_click_handler) double_click_handler(d, event);
        });    
}


function createBackgroundBox(canvas, width, height) {
    return canvas.append("rect")
            .attr("width", width)
            .attr("height", height)
            .attr("fill", "#ffffff00")        
}


function createHybridScales(size, numHistData, catHistData, numDomain, catDomain, direction = "horizontal") {

    let sizeDistNum = 0, sizeDistCat = 0 

    if( numHistData === null ) 
        sizeDistCat = size;
    else if( catHistData === null ) 
        sizeDistNum = size;
    else {
        sizeDistNum = size * (numHistData.length / (catHistData.length + numHistData.length));
        sizeDistCat = size * (catHistData.length / (catHistData.length + numHistData.length));
    }

    const spacing = (numHistData === null || catHistData === null || numHistData.length === 0 || catHistData.length === 0) ? 0 : 5

    const scaleNum = ( numHistData === null || numHistData.length === 0) ? null : 
                        d3.scaleLinear()
                            .domain(numDomain)
                            .range( direction === "horizontal" ? [0, sizeDistNum-spacing] : [size, sizeDistCat+spacing]);

    const scaleCat = ( catHistData === null || catHistData.length === 0 ) ? null :
                         d3.scaleBand()
                            .domain(catDomain)
                            .range( direction === "horizontal" ? [sizeDistNum+spacing, size] : [sizeDistCat-spacing, 0]);

    function draw(canvas) {
        if( direction === "horizontal" ) {
            if( scaleCat !== null )
                canvas
                        .append("g")
                        .attr("transform", `translate(0, ${size})`)
                        .call(d3.axisBottom(scaleCat))            
                        .selectAll("text") 
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d )  
                        .attr("class", "bottom-axis-text")
                        .attr("dx", "-0.5em") 
                        .attr("dy", "0.5em")  
                        .append("title")  
                        .text(d => d);

            if( scaleNum !== null )
                canvas
                        .append("g")
                        .attr("transform", `translate(0, ${size})`)
                        .call(d3.axisBottom(scaleNum).tickFormat(d3.format(".2s")))
                        .selectAll("text") 
                        .attr("class", "bottom-axis-text")
                        .attr("dx", "-0.5em") 
                        .attr("dy", "0.5em")  
                        .append("title")  
                        .text(d => d);
        }
        else{
            if( scaleCat !== null ){
                canvas
                        .append("g")
                        .call(d3.axisLeft(scaleCat))
                        .selectAll("text")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d )
                        .attr("class", "left-axis-text")
                        .append("title")
                        .text(d => d);
            }

            if( scaleNum !== null ){
                canvas
                        .append("g")
                        .call(d3.axisLeft(scaleNum).tickFormat(d3.format(".2s")))
                        .selectAll("text")
                        .attr("class", "left-axis-text")
                        .append("title")
                        .text(d => d);
            }                
        }
    }

    function apply( val, type ){
        if( type === "numeric" && scaleNum !== null ) 
            return scaleNum(val);
        if( type === "categorical" && scaleCat !== null )
            return scaleCat(val);
        console.warn("No scale available for type:", type, val);
        return null;
    }

    function categoricalBandwidth() {
        if( scaleCat !== null ) {
            return scaleCat.bandwidth();
        }
        console.warn("No categorical scale available for bandwidth");
        return 0;
    }

    function numericalBandwidth(x0,x1) {
        if( scaleNum !== null ) {
            return (scaleNum(x1) - scaleNum(x0));
        }
        console.warn("No numerical scale available for bandwidth");
        return 0;
    }

    return { scaleNum, scaleCat, draw, apply, categoricalBandwidth, numericalBandwidth }
}


