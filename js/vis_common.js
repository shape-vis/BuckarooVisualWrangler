


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
            if(left_click_handler) left_click_handler(d);
        })
        .on("contextmenu", function(event, d) {
            event.preventDefault(); // Prevent default context menu
            if(right_click_handler) right_click_handler(d);
            return false;
        })
        .on("dblclick", function(event, d) {
            if(double_click_handler) double_click_handler(d);
        });    
}

