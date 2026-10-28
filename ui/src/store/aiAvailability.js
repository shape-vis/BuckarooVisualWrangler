import {CANDIDATE_LOCKED} from "./RepairContext.jsx";

/**
 * Why asking the AI for repairs is off, or what asking does - the same words on a node's AI button and on the
 * header's AI Wrangle. Checked in order, so the most fundamental reason wins:
 *
 *   configured - whether the server has a model to ask
 *   locked     - whether the node asked about is a staged candidate, which nothing is wrangled from
 *   analysing  - whether the graph is in analysis mode, where new candidates land somewhere the tree is not drawn
 *   busy       - whether a request is already out
 *
 * Returns {blocked, detail}.
 */
export function aiAvailability({configured, locked, analysing, busy}) {
    if (!configured) {
        return {blocked: true, detail: "AI suggestions are not configured - add GEMINI_API_KEY to .env"};
    }
    if (locked) return {blocked: true, detail: `${CANDIDATE_LOCKED}.`};
    if (analysing) return {blocked: true, detail: "Switch to wrangling mode for suggestions"};
    if (busy) return {blocked: true, detail: "Working…"};
    return {blocked: false, detail: "Suggest repairs for this node"};
}
