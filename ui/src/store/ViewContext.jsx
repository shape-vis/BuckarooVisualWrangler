import { createContext } from "react";

/**
 * Coordinates the active workspace view and data-refresh revision.
 * Keeping this context separate from the page component preserves React Fast Refresh.
 */
export const ViewContext = createContext(null);
