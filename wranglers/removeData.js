export default function removeData(selectedPoints) {
    console.log("here in removeData wrangler");

    const selectedIDs = new Set(selectedPoints.map(p => p.ID));
  
    return function(row) {
        return !selectedIDs.has(row.ID);
    };
}