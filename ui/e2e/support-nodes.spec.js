import { test, expect, expectedFor } from "./fixtures.js";
import {
    accept, clickBin, graphNode, headerButton, openGraph, openPlots, plotOnly, repair, serverNode,
} from "./helpers.js";

/* Support nodes: adding each kind from the support-nodes window, minimising to a badge and back, hiding them all with
   a node's eye, removing them, keeping them over a reload, popping the window out, and what a candidate does with its
   parent's - which accepting now always opens. */

/** A node's support records, as the server keeps them. */
async function supportRecords(page, table) {
    const node = await serverNode(page, table);
    return node?.data?.support_nodes ?? [];
}

async function supportKinds(page, table) {
    const kinds = [];
    for (const record of await supportRecords(page, table)) kinds.push(record.kind);
    return kinds.sort();
}

/** The support nodes drawn beside a host. */
function drawnSupports(page, table) {
    return page.locator(`.react-flow__node[data-id^="support:${table}:"]`);
}

function supportWindow(page) {
    return page.locator(".support-window").first();
}

/** Opens the support-nodes window on the current node from the header. */
async function openSupportWindow(page) {
    await headerButton(page, "Add Support Nodes").click();
    await expect(supportWindow(page)).toBeVisible();
}

async function pickKind(page, label) {
    const option = supportWindow(page).getByRole("option", { name: label, exact: true });
    await option.click();
    await expect(option).toHaveAttribute("aria-selected", "true");
}

/** Adds one sub-node of a kind - from its Add button, or from the first card of its gallery - and waits for the save. */
async function addKind(page, label) {
    await pickKind(page, label);
    const saved = page.waitForResponse((response) => response.url().includes("/api/pgraph/support_nodes")
        && response.request().method() === "POST");
    const addButton = supportWindow(page).locator(".support-window-add");
    if (await addButton.count()) {
        await expect(addButton).toBeEnabled();
        await addButton.click();
    } else {
        await supportWindow(page).locator(".support-plot-action--primary").first().click();
    }
    const response = await saved;
    expect((await response.json()).success).toBe(true);
}

/** Root, and one accepted delete below it: n0a → n0b, so n0b has an edge for the kinds that need one. */
async function rootAndChild(page, upload) {
    const root = await upload("e2e_tiny");
    await openPlots(page);
    await plotOnly(page, ["Score"]);
    await clickBin(page, "Score", "null");
    const candidates = await repair(page);
    await accept(page, candidates.delete.table);
    return { root, child: candidates.delete.table, sibling: candidates.impute.table };
}

test("every kind of sub-node can be added from the window, and is kept on the server", async ({ page, upload }) => {
    const { child } = await rootAndChild(page, upload);
    await openGraph(page);
    await openSupportWindow(page);
    await expect(supportWindow(page)).toContainText("Add support nodes to node n0b");

    const kinds = [
        ["Quality metrics", "qualityMetrics"],
        ["Wrangle diff", "wrangleDiff"],
        ["Error plot", "errorPlot"],
        ["Drift plot", "drift"],
        ["Sparkline", "qualitySparkline"],
    ];
    const added = [];
    for (const [label, kind] of kinds) {
        await addKind(page, label);
        added.push(kind);
        await expect.poll(() => supportKinds(page, child)).toEqual([...added].sort());
    }
    await expect(supportWindow(page).locator(".support-window-count")).toHaveText(String(kinds.length));
    await expect(supportWindow(page).locator(".support-window-attached-row")).toHaveCount(kinds.length);
    await expect(drawnSupports(page, child)).toHaveCount(kinds.length);
});

test("a sub-node minimises to a badge on its node, and the badge brings it back", async ({ page, upload }) => {
    const { child } = await rootAndChild(page, upload);
    await openGraph(page);
    await openSupportWindow(page);
    await addKind(page, "Quality metrics");
    await expect(drawnSupports(page, child)).toHaveCount(1);

    await drawnSupports(page, child).getByRole("button", { name: "Minimise this sub-node" }).click();
    await expect(drawnSupports(page, child)).toHaveCount(0);
    const badge = graphNode(page, child).getByRole("button", { name: "Show Quality metrics" });
    await expect(badge).toBeVisible();

    await badge.click();
    await expect(drawnSupports(page, child)).toHaveCount(1);
    await expect(badge).toHaveCount(0);
});

test("a node's eye hides all its sub-nodes as badges, and shows them again", async ({ page, upload }) => {
    const { child } = await rootAndChild(page, upload);
    await openGraph(page);
    await openSupportWindow(page);
    await addKind(page, "Quality metrics");
    await addKind(page, "Drift plot");
    await expect(drawnSupports(page, child)).toHaveCount(2);

    await graphNode(page, child).getByRole("button", { name: "Hide supporting nodes" }).click();
    await expect(drawnSupports(page, child)).toHaveCount(0);
    // The badges stay, so what is hidden can still be seen
    await expect(graphNode(page, child).locator(".support-badge")).toHaveCount(2);

    await graphNode(page, child).getByRole("button", { name: "Show supporting nodes" }).click();
    await expect(drawnSupports(page, child)).toHaveCount(2);
});

test("removing a sub-node, from its own button or from the window, takes it off the server", async ({ page, upload }) => {
    const { child } = await rootAndChild(page, upload);
    await openGraph(page);
    await openSupportWindow(page);
    await addKind(page, "Quality metrics");
    await addKind(page, "Drift plot");

    const removed = page.waitForResponse((response) => response.url().includes("/api/pgraph/support_nodes")
        && response.request().method() === "DELETE");
    await drawnSupports(page, child).first().getByRole("button", { name: "Remove this sub-node" }).click();
    await removed;
    await expect.poll(async () => (await supportRecords(page, child)).length).toBe(1);

    await supportWindow(page).getByRole("button", { name: "Remove" }).first().click();
    await expect.poll(async () => (await supportRecords(page, child)).length).toBe(0);
    await expect(drawnSupports(page, child)).toHaveCount(0);
    await expect(supportWindow(page).locator(".support-window-empty")).toBeVisible();
});

test("sub-nodes outlive a reload of the page", async ({ page, upload }) => {
    const { child } = await rootAndChild(page, upload);
    await openGraph(page);
    await openSupportWindow(page);
    await addKind(page, "Quality metrics");
    await addKind(page, "Error plot");

    await page.reload();
    await openGraph(page);
    await expect(drawnSupports(page, child)).toHaveCount(2);
    expect(await supportKinds(page, child)).toEqual(["errorPlot", "qualityMetrics"]);
});

test("accepting a candidate opens the sub-nodes it inherited from its parent", async ({ page, upload }) => {
    const root = await upload("e2e_tiny");
    await openGraph(page);
    await openSupportWindow(page);
    await addKind(page, "Quality metrics");
    await addKind(page, "Drift plot");
    await expect.poll(() => supportKinds(page, root)).toEqual(["drift", "qualityMetrics"]);

    await openPlots(page);
    await plotOnly(page, ["Score"]);
    await clickBin(page, "Score", "null");
    const candidates = await repair(page);

    // Staged, each candidate carries copies of root's, minimised to badges
    for (const candidate of Object.values(candidates)) {
        await expect(drawnSupports(page, candidate.table)).toHaveCount(0);
        await expect(graphNode(page, candidate.table).locator(".support-badge")).toHaveCount(2);
    }

    // Accepting has no choice to make any more: one Accept, and they open
    await expect(graphNode(page, candidates.delete.table).getByRole("button", { name: /Accept/ })).toHaveCount(1);
    await accept(page, candidates.delete.table);
    await expect(drawnSupports(page, candidates.delete.table)).toHaveCount(2);
    await expect(graphNode(page, candidates.delete.table).locator(".support-badge")).toHaveCount(0);

    // The sibling still staged keeps its copies as badges
    await expect(graphNode(page, candidates.impute.table).locator(".support-badge")).toHaveCount(2);
});

test("a node cannot be given the same sub-node twice", async ({ page, upload }) => {
    const root = await upload("e2e_tiny");
    await openGraph(page);
    await openSupportWindow(page);

    await addKind(page, "Quality metrics");
    await expect(supportWindow(page).locator(".support-window-reason")).toContainText("already has this quality metrics");
    await expect(supportWindow(page).locator(".support-window-add")).toBeDisabled();

    // A gallery's card the node already has is refused; the others can still be added
    await addKind(page, "Error plot");
    const cards = supportWindow(page).locator(".support-plot-action--primary");
    await expect(cards.first()).toHaveText("Already on this node");
    await expect(cards.first()).toBeDisabled();
    await expect(cards.nth(1)).toBeEnabled();

    expect(await supportKinds(page, root)).toEqual(["errorPlot", "qualityMetrics"]);
});

test("a wrangle diff cannot be added to the root, which has no edge into it", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await openGraph(page);
    await openSupportWindow(page);
    await pickKind(page, "Wrangle diff");
    await expect(supportWindow(page).locator(".support-window-reason")).toBeVisible();
    await expect(supportWindow(page).locator(".support-window-add")).toBeDisabled();
});

test("a sparkline is added, then given its branch by clicking the edge above its node", async ({ page, upload }) => {
    const { root, child } = await rootAndChild(page, upload);
    await openGraph(page);
    await openSupportWindow(page);
    await addKind(page, "Sparkline");

    const prompt = page.locator(".pgraph-pick-prompt");
    if (!(await prompt.isVisible())) {
        await drawnSupports(page, child).getByTitle(/Pick the edge in the graph/).click();
    }
    await expect(prompt).toBeVisible();
    const measured = page.waitForResponse((response) => response.url().includes("/api/pgraph/support_nodes")
        && response.request().method() === "PATCH");
    await page.locator(`.react-flow__edge[data-id*="${root}"][data-id*="${child}"]`).first().click({ force: true });
    await measured;
    await expect(prompt).toHaveCount(0);

    const records = await supportRecords(page, child);
    expect(records[0].kind).toBe("qualitySparkline");
    expect(records[0].config.branch).toBeTruthy();
});

test("the support-nodes window pops out and docks again", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await openGraph(page);
    await openSupportWindow(page);

    const opened = page.context().waitForEvent("page");
    await supportWindow(page).getByRole("button", { name: "Pop out" }).click();
    const popup = await opened;
    await expect(popup.locator(".support-window")).toBeVisible();
    await pickKindIn(popup, "Quality metrics");

    await popup.locator(".support-window").getByRole("button", { name: "Dock" }).click();
    await expect(supportWindow(page)).toBeVisible();
    await supportWindow(page).getByRole("button", { name: /Close/ }).click();
    await expect(page.locator(".support-window")).toHaveCount(0);
});

async function pickKindIn(scope, label) {
    const option = scope.locator(".support-window").getByRole("option", { name: label, exact: true });
    await option.click();
    await expect(option).toHaveAttribute("aria-selected", "true");
}

test("an error plot's Repair grows it into a brushable plot whose selection stages repairs", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    const root = await upload("e2e_tiny");
    await openGraph(page);
    await openSupportWindow(page);
    await addKind(page, "Error plot");
    const support = drawnSupports(page, root);
    await expect(support).toHaveCount(1);

    await support.getByRole("button", { name: "Repair" }).click();
    const plot = support.locator('[data-testid="histogram"]');
    await expect(plot.locator("rect[data-bin]").first()).toBeAttached();
    const column = await plot.getAttribute("data-column");
    // Grown, it reaches past the graph's edge - fitted, the whole of it is on screen
    await page.getByRole("button", { name: "Fit View" }).click();
    await expect(plot.locator('rect[data-bin="null"]').first()).toBeInViewport();

    const answered = page.waitForResponse((response) => response.url().includes("/api/plots/rows-in-bin"));
    await plot.locator('rect[data-bin="null"]').first().click({ force: true });
    const rowIds = (await (await answered).json()).row_ids;
    let nullRows = 0;
    for (const entry of expected.root.histograms[column].bins) {
        if (entry.xBin === "null") nullRows = entry.count.items;
    }
    expect(rowIds.length).toBe(nullRows);

    const staged = page.waitForResponse((response) => response.url().includes("/api/wrangle/create-previews"));
    await support.getByRole("button", { name: "Repair selection" }).click();
    const body = await (await staged).json();
    expect(body.success).toBe(true);
    for (const candidate of body.candidates) {
        await expect(graphNode(page, candidate.table)).toBeVisible();
    }

    await support.getByRole("button", { name: "Done" }).click();
    await expect(support.getByRole("button", { name: "Repair selection" })).toHaveCount(0);
});
