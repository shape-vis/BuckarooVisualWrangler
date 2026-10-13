// drift.js
// Shared by every view that shows drift from root: how its numbers read.
// Drift is a cost, not an error - see app/pgraph/distortion.py - so nothing here colors it good or bad.

/** A drift value as it reads everywhere: three places, or a dash where there is none. */
export const formatDrift = (value) => (value == null ? "—" : value.toFixed(3));

/** A change in drift between two nodes, both measured from root. */
export function formatDriftDelta(delta) {
    return `${signOf(delta)}${Math.abs(delta).toFixed(3)}`;
}

// A typographic minus rather than a hyphen, and ± for no change at all
function signOf(delta) {
    if (delta > 0) return "+";
    if (delta < 0) return "−";
    return "±";
}
