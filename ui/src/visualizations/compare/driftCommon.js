// compare/driftCommon.js
// What both drift views - the ridgeline and the flows - share. Each node is drawn against root, from
// /api/pgraph/drift_detail - see app/pgraph/distortion.py. Drift is a cost, not an error, so none of these views
// colors it good or bad.
// The panel can measure from the two selections' common ancestor instead, so the reference is named by
// ctx.labels.base wherever the reader sees it; "root" in the code means whichever state that is.

import * as d3 from "d3";
import {ROLE_COLORS} from "../../utils/comparison.js";
import {clamp} from "../../utils/visCommon.jsx";

// The reference state's grey - root's, or the common ancestor's
export const DRIFT_BASE_COLOR = "#8c939d";

export const formatShare = d3.format(".1%");

// The annotation bubble's radius, and how far it sits from the spot it points at
const BUBBLE_R = 11;
const BUBBLE_REACH = 34;

/* A thought bubble pinned beside the place a node's data actually moved, with an arrow to that place, so the
   reader can see which part of the picture its annotation is about. aside is appended to the sentences - a
   zoomed ridgeline uses it to say the spot is outside the range shown. */
export function drawAnnotationBubble(g, {ax, ay, bounds, aside}, role, side, ctx) {
    const sentences = side?.annotation?.sentences ?? [];
    if (!sentences.length) return;

    const color = ROLE_COLORS[role];
    // Up and to the right of the spot, but never outside the panel it belongs to
    const bx = clamp(ax + BUBBLE_REACH, bounds.left + BUBBLE_R, bounds.right - BUBBLE_R);
    const by = clamp(ay - BUBBLE_REACH, bounds.top + BUBBLE_R, bounds.bottom - BUBBLE_R);
    const at = (t) => [bx + (ax - bx) * t, by + (ay - by) * t];
    const angle = Math.atan2(ay - by, ax - bx);
    const back = [ax - Math.cos(angle) * 9, ay - Math.sin(angle) * 9];
    const corner = (turn) => [back[0] + Math.cos(angle + turn) * 4.5, back[1] + Math.sin(angle + turn) * 4.5];

    const group = g.append("g").attr("class", "compare-bubble");
    group.append("line")
        .attr("x1", at(0.62)[0]).attr("y1", at(0.62)[1]).attr("x2", back[0]).attr("y2", back[1])
        .attr("stroke", color).attr("stroke-width", 1.4);
    group.append("polygon")
        .attr("points", [[ax, ay], corner(Math.PI / 2), corner(-Math.PI / 2)].map((point) => point.join(",")).join(" "))
        .attr("fill", color);
    // The two puffs that make it a thought bubble rather than a speech balloon
    [[0.26, 4], [0.46, 2.5]].forEach(([t, r]) => {
        const [px, py] = at(t);
        group.append("circle").attr("cx", px).attr("cy", py).attr("r", r)
            .attr("fill", "#ffffff").attr("stroke", color).attr("stroke-width", 1.2);
    });
    group.append("circle").attr("cx", bx).attr("cy", by).attr("r", BUBBLE_R)
        .attr("fill", "#ffffff").attr("stroke", color).attr("stroke-width", 1.6);
    group.append("text").attr("class", "compare-bubble-mark")
        .attr("x", bx).attr("y", by).attr("text-anchor", "middle").attr("dominant-baseline", "central")
        .attr("fill", color).text("i");

    /* The sentences go to the readout under the plot rather than to a tooltip over it: they run to a few
       lines, and a floating panel would cover the very spot the bubble is pointing at. */
    group
        .on("mouseover", () => {
            group.classed("compare-bubble--hover", true);
            ctx.showNote?.({role, label: ctx.labels[role], text: [...sentences, aside].filter(Boolean).join(" ")});
        })
        .on("mouseout", () => {
            group.classed("compare-bubble--hover", false);
            ctx.showNote?.(null);
        });
}
