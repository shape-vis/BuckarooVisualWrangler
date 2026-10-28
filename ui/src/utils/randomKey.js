/* A short key that is unique enough within one page: the time it was made, and a few random characters for
   keys made in the same millisecond. Sub-node ids and compare groups are built from these. */
export function randomKey() {
    const timePart = Date.now().toString(36);
    const randomPart = Math.random().toString(36).slice(2, 6);
    return `${timePart}${randomPart}`;
}
