import { test, expect, expectedFor, serverTable } from "./fixtures.js";
import {
    accept, clickBin, decline, expectedHistogram, graphNode, headerButton, mapToObject, navigateTo, openGraph,
    openPlots, plotOnly, readHistogram, repair, shiftClick, tableStatus, viewToggle,
} from "./helpers.js";

/* The provenance graph: picking selection A, navigating, undo and redo at both ends of the history, folding a run,
   the analysis mode, React Flow's own controls and resizing a candidate. */

/* Repairs the current node by deleting one bin's rows, and accepts the delete. Returns the accepted table. */
async function deleteBin(page, column, bin) {
    await openPlots(page);
    await plotOnly(page, [column]);
    await clickBin(page, column, bin);
    const candidates = await repair(page);
    await accept(page, candidates.delete.table);
    return { accepted: candidates.delete.table, sibling: candidates.impute.table };
}

/* A root and three accepted deletes below it, one after another: n0a → n0b → n0c → n0d. Each delete's impute sibling
   stays staged unless straight is asked for, when it is declined and the chain has no forks. */
async function buildChain(page, upload, { straight = false } = {}) {
    const root = await upload("e2e_tiny");
    const chain = [root];
    const steps = [["Score", "null"], ["Count", "0"], ["Count", "0"]];
    for (const [column, bin] of steps) {
        const { accepted, sibling } = await deleteBin(page, column, bin);
        if (straight) {
            await openGraph(page);
            await decline(page, sibling);
        }
        chain.push(accepted);
    }
    return chain;
}

async function fitView(page) {
    await page.getByRole("button", { name: "Fit View" }).click();
}

test("shift-clicking a node makes it selection A, and the header offers to compare it", async ({ page, upload }) => {
    const root = await upload("e2e_tiny");
    const { accepted } = await deleteBin(page, "Score", "null");
    await openGraph(page);
    await expect(headerButton(page, "Compare")).toHaveCount(0);

    await shiftClick(page, root);
    await expect(graphNode(page, root)).toContainText("selection A");
    await expect(graphNode(page, accepted)).toContainText("selection B");
    await expect(headerButton(page, "Compare")).toBeVisible();

    // Shift-clicking it again clears it
    await shiftClick(page, root);
    await expect(graphNode(page, root)).not.toContainText("selection A");
    await expect(headerButton(page, "Compare")).toHaveCount(0);

    // ... as does the toolbar's Clear selection
    await shiftClick(page, root);
    await page.getByRole("button", { name: "Clear selection" }).click();
    await expect(headerButton(page, "Compare")).toHaveCount(0);
});

test("a plain click on a node changes nothing", async ({ page, upload }) => {
    const root = await upload("e2e_tiny");
    const { accepted } = await deleteBin(page, "Score", "null");
    await openGraph(page);

    await graphNode(page, root).click();
    await expect(graphNode(page, accepted)).toHaveClass(/pgraph-node--current/);
    expect(await serverTable(page)).toBe(accepted);
    await expect(headerButton(page, "Compare")).toHaveCount(0);
});

test("double-clicking a node moves to it, and the plots draw its data", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    const root = await upload("e2e_tiny");
    const { accepted } = await deleteBin(page, "Score", "null");

    await openGraph(page);
    await navigateTo(page, root);
    await expect(tableStatus(page)).toHaveText(/^n0a/);
    expect(await serverTable(page)).toBe(root);
    await openPlots(page);
    await plotOnly(page, ["Score"]);
    const drawn = await readHistogram(page, "Score");
    expect(mapToObject(drawn)).toEqual(mapToObject(expectedHistogram(expected.root.histograms.Score)));

    // What n0b's plots draw is repair.spec.js's to check
    await openGraph(page);
    await navigateTo(page, accepted);
    await expect(tableStatus(page)).toHaveText(/^n0b/);
    expect(await serverTable(page)).toBe(accepted);
});

test("a candidate can be visited and compared, and the header names it", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await openPlots(page);
    await plotOnly(page, ["Score"]);
    await clickBin(page, "Score", "null");
    const candidates = await repair(page);

    await navigateTo(page, candidates.impute.table);
    await expect(tableStatus(page)).toHaveText(/^c\d+ - e2e_tiny/);
    expect(await serverTable(page)).toBe(candidates.impute.table);

    await shiftClick(page, candidates.delete.table);
    await expect(graphNode(page, candidates.delete.table)).toContainText("selection A");
    await expect(headerButton(page, "Compare")).toBeVisible();
});

test("undo and redo walk the history, stop at either end, and redo retraces past staged siblings", async ({ page, upload }) => {
    // Fixed October 30, 2026: redo used to retrace only the last undo, then fall to the newest child - a candidate
    const chain = await buildChain(page, upload);
    const labels = ["n0a", "n0b", "n0c", "n0d"];

    async function expectOn(index) {
        await expect(tableStatus(page)).toHaveText(new RegExp(`^${labels[index]} `));
        await expect.poll(() => serverTable(page)).toBe(chain[index]);
    }

    await expectOn(3);
    for (let index = 2; index >= 0; index -= 1) {
        await headerButton(page, "Undo").click();
        await expectOn(index);
    }
    // At the root, undo has nowhere to go
    await headerButton(page, "Undo").click();
    await expectOn(0);

    for (let index = 1; index <= 3; index += 1) {
        await headerButton(page, "Redo").click();
        await expectOn(index);
    }
    // At the newest node, redo has nowhere to go
    await headerButton(page, "Redo").click();
    await expectOn(3);
});

test("a lasso through a fork is refused with a reason", async ({ page, upload }) => {
    const chain = await buildChain(page, upload);
    await openGraph(page);
    await fitView(page);
    await lasso(page, [chain[1], chain[2]]);

    await expect(page.locator(".pgraph-collapse-error")).toContainText("branches");
    await expect(page.locator(".react-flow__node-collapsedNode")).toHaveCount(0);
    await page.locator(".pgraph-collapse-error").click();
    await expect(page.locator(".pgraph-collapse-error")).toHaveCount(0);
});

/* Holds "c" - the tree's lasso key - and drags a box around the nodes */
async function lasso(page, tables) {
    let left = Infinity;
    let top = Infinity;
    let right = -Infinity;
    let bottom = -Infinity;
    for (const table of tables) {
        const box = await graphNode(page, table).boundingBox();
        left = Math.min(left, box.x);
        top = Math.min(top, box.y);
        right = Math.max(right, box.x + box.width);
        bottom = Math.max(bottom, box.y + box.height);
    }
    await page.keyboard.down("c");
    // React Flow holds the key in its state; until it has drawn with it, a drag selects text instead of lassoing
    await expect(page.locator(".react-flow__pane.selection").first()).toBeVisible();
    await page.mouse.move(left - 15, top - 15);
    await page.mouse.down();
    await page.mouse.move(right + 15, bottom + 15, { steps: 12 });
    await page.mouse.up();
    await page.keyboard.up("c");
}

test("a lasso around a run folds it into one node, and Expand all unfolds it", async ({ page, upload }) => {
    const chain = await buildChain(page, upload, { straight: true });
    await openGraph(page);
    await fitView(page);

    await lasso(page, [chain[1], chain[2]]);

    await expect(page.locator(".react-flow__node-collapsedNode")).toHaveCount(1);
    await expect(graphNode(page, chain[1])).toHaveCount(0);
    await expect(graphNode(page, chain[2])).toHaveCount(0);

    await page.getByRole("button", { name: /Expand all/ }).click();
    await expect(page.locator(".react-flow__node-collapsedNode")).toHaveCount(0);
    await expect(graphNode(page, chain[1])).toBeVisible();
    await expect(graphNode(page, chain[2])).toBeVisible();
});

test("analysis mode plots the nodes, and every error metric can be chosen", async ({ page, upload }) => {
    await buildChain(page, upload);
    await openGraph(page);

    await page.getByRole("radio", { name: "Analysis" }).click();
    await expect(page.getByRole("radio", { name: "Analysis" })).toHaveAttribute("aria-checked", "true");
    const metric = page.locator(".pgraph-axis-pick select");
    await expect(metric).toBeVisible();

    const options = await metric.locator("option").evaluateAll((elements) => {
        const values = [];
        for (const element of elements) values.push(element.value);
        return values;
    });
    expect(options.length).toBeGreaterThan(1);
    for (const value of options) {
        await metric.selectOption(value);
        await expect(metric).toHaveValue(value);
    }
    await page.getByRole("radio", { name: "Full nodes" }).click();
    await page.getByRole("radio", { name: "Simple" }).click();

    await page.getByRole("radio", { name: "Wrangling" }).click();
    await expect(metric).toHaveCount(0);
    // The four nodes of the chain, and each delete's impute sibling, still staged
    await expect(page.locator(".react-flow__node")).toHaveCount(7);
});

/* The viewport's zoom, read off its transform */
async function zoomOf(page) {
    const style = await page.locator(".react-flow__viewport").first().getAttribute("style");
    const match = /scale\(([\d.]+)\)/.exec(style);
    return Number(match[1]);
}

test("React Flow's zoom, fit and lock controls work", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await openGraph(page);

    // A lone node is fitted at the maximum zoom, where zooming in is off - so out first
    const fitted = await zoomOf(page);
    await page.getByRole("button", { name: "Zoom Out" }).click();
    await expect.poll(() => zoomOf(page)).toBeLessThan(fitted);
    const zoomedOut = await zoomOf(page);
    await page.getByRole("button", { name: "Zoom In" }).click();
    await expect.poll(() => zoomOf(page)).toBeGreaterThan(zoomedOut);
    await page.getByRole("button", { name: "Zoom Out" }).click();
    await page.getByRole("button", { name: "Zoom Out" }).click();
    await fitView(page);
    await expect.poll(() => zoomOf(page)).toBeCloseTo(fitted, 2);

    // Locked, a node cannot be dragged; unlocked again, it can
    const lock = page.getByRole("button", { name: "Toggle Interactivity" });
    await lock.click();
    await expect(page.locator(".react-flow__node").first()).not.toHaveClass(/draggable/);
    await lock.click();
    await expect(page.locator(".react-flow__node").first()).toHaveClass(/draggable/);
});

test("a candidate can be resized from its corner", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await openPlots(page);
    await plotOnly(page, ["Score"]);
    await clickBin(page, "Score", "null");
    const candidates = await repair(page);
    await fitView(page);
    const node = graphNode(page, candidates.delete.table);

    const before = await node.boundingBox();
    const handle = node.locator(".react-flow__resize-control.handle.bottom.right");
    const corner = await handle.boundingBox();
    await page.mouse.move(corner.x + corner.width / 2, corner.y + corner.height / 2);
    await page.mouse.down();
    await page.mouse.move(corner.x + 60, corner.y + 40, { steps: 8 });
    await page.mouse.up();

    await expect.poll(async () => (await node.boundingBox()).width).toBeGreaterThan(before.width + 20);
});

test("the graph and plots views open side by side, and the last open one cannot be closed", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await openGraph(page);
    await expect(page.locator(".plots-pane")).toBeVisible();
    await expect(page.locator(".react-flow")).toBeVisible();

    await viewToggle(page, "Plots").click();
    await expect(page.locator(".plots-pane")).toHaveCount(0);
    // The graph is the only view left, so its toggle leaves it open
    await viewToggle(page, "Provenance Graph").click();
    await expect(page.locator(".react-flow")).toBeVisible();
    await viewToggle(page, "Plots").click();
    await expect(page.locator(".plots-pane")).toBeVisible();
});
