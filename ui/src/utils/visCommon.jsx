// visCommon.jsx
import * as d3 from "d3";

const TOOLTIP_GAP = 10;

/**
 * Places the tooltip beside the cursor, flipping to the other side of it when the default placement
 * would run off the edge of the window. Without this, anything plotted near the right edge - a
 * sparkline's last point, the rightmost bin of a histogram - shows a clipped tooltip.
 *
 * Must be called after the content is set: the flip depends on the rendered size.
 */
function positionTooltip(tooltip, event) {
    const node = tooltip.node();
    if (!node) return;

    const { offsetWidth: width, offsetHeight: height } = node;

    // pageX/pageY are document coordinates, so the edges have to be in document space too
    const rightEdge = window.scrollX + document.documentElement.clientWidth;
    const bottomEdge = window.scrollY + document.documentElement.clientHeight;

    const overflowsRight = event.pageX + TOOLTIP_GAP + width > rightEdge;
    const overflowsBottom = event.pageY + TOOLTIP_GAP + height > bottomEdge;

    const left = overflowsRight ? event.pageX - TOOLTIP_GAP - width : event.pageX + TOOLTIP_GAP;
    const top = overflowsBottom ? event.pageY - TOOLTIP_GAP - height : event.pageY + TOOLTIP_GAP;

    tooltip.style("left", `${Math.max(0, left)}px`)
           .style("top", `${Math.max(0, top)}px`);
}

/**
 * Shows the shared tooltip with the given html, placed beside the cursor.
 *
 * For callers outside d3 - React event handlers, say - that still want the one tooltip element and
 * its edge-aware placement.
 */
export function showTooltip(html, event) {
    const tooltip = d3.select("#tooltip");
    tooltip.style("display", "block").html(html);
    positionTooltip(tooltip, event);
}

export function moveTooltip(event) {
    positionTooltip(d3.select("#tooltip"), event);
}

export function hideTooltip() {
    d3.select("#tooltip").style("display", "none");
}

// Handlers default to doing nothing, so a chart passes only the clicks it reacts to
function ignoreClick() {}

export function createTooltip(target_objects, html_function, left_click_handler = ignoreClick, right_click_handler = ignoreClick, double_click_handler = ignoreClick) {

    const tooltip = d3.select("#tooltip");
    target_objects.on("mouseover", function(event, d) {
            d3.select(this).attr("opacity", 0.5)

            showTooltip(html_function(d), event);
        })
        .on("mousemove", function(event) {
            positionTooltip(tooltip, event);
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

export function createHybridScales(size, numHistData, catHistData, numDomain, catDomain, direction = "horizontal") {

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

    function apply( val, type, centerBand = false ){
        if( type === "numeric" && scaleNum !== null )
            return scaleNum(val);
        if( type === "categorical" && scaleCat !== null ) {
            const basePos = scaleCat(val);
            // Return the center of the band for point positioning, or edge for rectangles
            return centerBand ? basePos + scaleCat.bandwidth() / 2 : basePos;
        }
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

    return { scaleNum, scaleCat, draw, apply, categoricalBandwidth, numericalBandwidth, numHistData, catHistData }
}

/* A numeric axis's domain from its bins: the lowest bin edge to the highest, or null when the axis has no
   numeric bins */
function numericDomainOf(bins) {
    if (bins.length === 0 || !bins[0]) return null;
    return [d3.min(bins, (bin) => bin.x0), d3.max(bins, (bin) => bin.x1)];
}

// A categorical axis's domain is its labels, or null when it has none
function categoricalDomainOf(labels) {
    if (labels.length === 0) return null;
    return labels;
}

/**
 * createHybridScales fed the shape the server sends for a binned axis - numeric bins with x0 and x1 edges, and
 * categorical labels - either of which may be empty.
 */
export function createBinnedScales(size, numericBins, categories, direction) {
    const numericDomain = numericDomainOf(numericBins);
    const categoricalDomain = categoricalDomainOf(categories);
    return createHybridScales(size, numericBins, categories, numericDomain, categoricalDomain, direction);
}

/* value held between lo and hi. When the range is empty - hi below lo - hi wins. */
export function clamp(value, lo, hi) {
    return Math.min(Math.max(value, lo), hi);
}

// Firefox can report a wheel's movement in lines rather than pixels
const WHEEL_LINE_PIXELS = 16;

/* How far a wheel event scrolls, in pixels */
export function wheelPixels(event) {
    if (event.deltaMode === 1) return event.deltaY * WHEEL_LINE_PIXELS;
    return event.deltaY;
}

/* An error rate as a percentage to two places. A missing rate reads as zero. */
export function asPercent(rate) {
    return `${((rate ?? 0) * 100).toFixed(2)}%`;
}
