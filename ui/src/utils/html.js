// html.js
// Helpers for the html the plots build by hand - tooltips set as html, and ids that url(#...) references name.

const HTML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"};

/* Category labels, column names and node names are the user's data, and tooltips are set as html, so anything
   of theirs is escaped before it goes in */
export function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => HTML_ESCAPES[character]);
}

/* An id from React's useId, made safe for a url(#...) reference: its own characters are not all allowed there.
   Ids are still unique per page, which is what the clip paths and patterns that use them need. */
export function domSafeId(id) {
    return id.replace(/[^\w-]/g, "");
}
