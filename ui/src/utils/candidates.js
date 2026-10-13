/* What each source calls its candidates, and which rows its row count is of. An AI suggestion counts the
   flagged rows its wrangle touches; a repair, the rows the user selected. */
export const CANDIDATE_SOURCES = {
    ai: { tag: "AI", rowNoun: "flagged" },
    repair: { tag: "Repair", rowNoun: "selected" },
};
