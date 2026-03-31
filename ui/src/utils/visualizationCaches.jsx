// Shared module-level caches for visualization components.
// Kept in a separate utility file so that component files only export
// components (required by React Fast Refresh).

export const scatterPlotCache = new Map();
export const heatMapCache = new Map();
export const histogramCache = new Map();

export function clearScatterPlotCache() { scatterPlotCache.clear(); }
export function clearHeatMapCache() { heatMapCache.clear(); }
export function clearHistogramCache() { histogramCache.clear(); }
