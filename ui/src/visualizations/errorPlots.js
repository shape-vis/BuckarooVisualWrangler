// errorPlots.js
// What the error plots share - the histogram, heatmap and scatterplot of the selection panel, and the repair
// preview's small versions of the same three: the colours of their marks, the stacking of a histogram's bars,
// and the fetching and caching of the main charts' data.

import { useEffect, useRef, useState } from "react";
import { useRowRange } from "../store/RowRangeContext.jsx";

// A mark picked out by a selection, in any chart
export const HIGHLIGHT_FILL = "gold";
// Every mark's colour when the chart is drawn without error colours
const PLAIN_FILL = "steelblue";
export const plainColorScale = () => PLAIN_FILL;
/* A brush drag ends with a click on whatever mark it ended over. A click this soon after a drag is that one, and
   is ignored, or it would replace the drag's selection with the single mark. */
export const BRUSH_CLICK_GUARD_MS = 300;

/**
 * A histogram's bins flattened into the segments of their stacked bars: each error type's count from the top
 * down, then the clean rows beneath.
 *
 * A row flagged two ways counts under both types, so a bin's flags can add up to more than its rows. The bar is
 * still drawn its rows' height: the error types then share it in proportion to their counts, so each one present
 * shows, and none reaches below the axis. A segment's value stays its real count.
 *
 * @returns [{bin, type, value, name, top, bottom}] - type is the bin's numeric or categorical kind, name the
 *          error type the segment counts, or "none"
 */
export function stackBars(histograms) {
    const segments = [];
    histograms.forEach((d) => {
        const errorTypes = Object.keys(d.count).filter((key) => key !== "items");
        let flagged = 0;
        for (const errorType of errorTypes) {
            flagged += d.count[errorType];
        }
        // How much of the bar one flag takes: one row's height, or less when the flags overlap
        let flagHeight = 1;
        if (flagged > d.count.items) {
            flagHeight = d.count.items / flagged;
        }

        let top = d.count.items;
        for (const errorType of errorTypes) {
            const height = d.count[errorType] * flagHeight;
            segments.push({
                bin: d.xBin, type: d.xType, value: d.count[errorType], name: errorType, top, bottom: top - height,
            });
            top -= height;
        }
        const clean = d.count.items - flagged;
        if (clean > 0) {
            segments.push({ bin: d.xBin, type: d.xType, value: clean, name: "none", top: clean, bottom: 0 });
        }
    });
    return segments;
}

// A heatmap tile's colour: its first error type's, or the clean colour when none of its rows is flagged
export function tileColor(colorScale, tile) {
    const errorTypes = Object.keys(tile.count).filter((key) => key !== "items");
    if (errorTypes.length === 0) return colorScale("none");
    return colorScale(errorTypes[0]);
}

// A scatterplot point's colour: its first error's, or the clean colour when it has none
export function pointColor(colorScale, point) {
    if (!point.errors || point.errors.length === 0) return colorScale("none");
    return colorScale(point.errors[0]);
}

/* A ref that always holds the latest value, for d3 handlers that are set up once but must still call the
   current version of a function or read the current version of a number */
export function useLatestRef(value) {
    const ref = useRef(value);
    useEffect(() => { ref.current = value; }, [value]);
    return ref;
}

/**
 * A chart's data, fetched as its table, columns or row range change.
 *
 * Data for the whole table is kept in cache, a Map that outlives the component, so a chart that is unmounted
 * and mounted again - the focus view zooming in and out - draws at once rather than asking the server again.
 * Data for a row range is always fetched afresh.
 *
 * @param cache       the chart kind's cache
 * @param cacheKey    what the whole table's data is filed under - the table and columns
 * @param load        async ({useRange, minId, maxId}) => the data; throws when the server could not give it
 * @param requestDeps everything load reads besides the row range, so a change to any of them fetches again
 * @param logPrefix   put before a failure's message in the console, naming the chart
 */
export function useCachedPlotData(cache, cacheKey, load, requestDeps, logPrefix = "") {
    const [data, setData] = useState(null);
    const { useRange, minId, maxId } = useRowRange();

    useEffect(() => {
        async function fetchData() {
            if (!useRange && cache.has(cacheKey)) {
                setData(cache.get(cacheKey));
                return;
            }

            try {
                const fetched = await load({ useRange, minId, maxId });
                setData(fetched);
                if (!useRange) cache.set(cacheKey, fetched);
            } catch (err) {
                const reason = err?.message || err;
                if (logPrefix) {
                    console.error(logPrefix + reason);
                } else {
                    console.error(reason);
                }
            }
        }
        fetchData();
        // load is a new function every render; requestDeps names everything it reads
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [...requestDeps, useRange, minId, maxId]);

    return data;
}
