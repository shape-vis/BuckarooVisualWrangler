import { test, expect, expectedFor } from "./fixtures.js";
import {
    accept, clickBin, graphNode, headerButton, navigateTo, openGraph, openPlots, plotOnly, repair, serverNode,
    shiftClick,
} from "./helpers.js";

/* The compare panel: two nodes binned on shared axes, docked as a tab or popped out into a window of its own. The
   comparison opened throughout is the one from the user's report - a delete and an impute of Critic_Count's missing
   rows, side by side - and every plot is held to the expected JSON and to the live API. */

/**
 * Stages the delete and the impute of Critic_Count's missing rows on e2e_games_small, makes the impute current
 * (selection B) and the delete selection A, and opens the comparison.
 * @return {delete, impute} - the two candidates
 */
async function openDeleteVsImpute(page, upload, dataset = "e2e_games_small", column = "Critic_Count") {
    await upload(dataset);
    await openPlots(page);
    await plotOnly(page, [column]);
    await clickBin(page, column, "null");
    const candidates = await repair(page);

    await openGraph(page);
    await navigateTo(page, candidates.impute.table);
    await shiftClick(page, candidates.delete.table);
    await headerButton(page, "Compare").click();
    await expect(page.locator(".compare-panel")).toBeVisible();
    return candidates;
}

/* A field of the options column by its label - the select's own accessible name also carries its options' text */
function field(scope, label) {
    return scope.locator(`label.compare-field:has(> span.compare-field-label:text-is("${label}")) select`);
}

/* A choice in one of the panel's segmented controls, by the group's name - "Drift" is both a plot type and a ranking */
function choice(scope, group, name) {
    return scope.getByRole("radiogroup", { name: group }).getByRole("radio", { name, exact: true });
}

function comparePlot(scope) {
    return scope.locator('[data-testid="comparison-plot"]');
}

/** What the side-by-side or overlay plot draws: rows per bin on each side, {a: {bin: rows}, b: {...}}. */
async function readComparePlot(scope) {
    return comparePlot(scope).locator("rect[data-role]").evaluateAll((rects) => {
        const sides = { a: {}, b: {} };
        for (const rect of rects) {
            const role = rect.getAttribute("data-role");
            const items = Number(rect.getAttribute("data-bin-items"));
            if (items > 0) sides[role][rect.getAttribute("data-bin")] = items;
        }
        return sides;
    });
}

/** A comparison as the expected JSON or the API holds it, in readComparePlot's shape - empty bins left out. */
function sidesOf(bins) {
    const sides = { a: {}, b: {} };
    for (const entry of bins) {
        for (const role of ["a", "b"]) {
            const items = entry[role].items;
            if (items > 0) sides[role][String(entry.xBin)] = items;
        }
    }
    return sides;
}

async function apiCompare(page, candidates, column) {
    const response = await page.request.get("/api/pgraph/compare", {
        params: { a: candidates.delete.table, b: candidates.impute.table, kind: "histogram", x: column },
    });
    const body = await response.json();
    expect(body.success, JSON.stringify(body)).toBe(true);
    return body;
}

/** Picks the plotted column, and waits for the plot to draw it. */
async function chooseColumn(scope, column) {
    const select = field(scope, "Column");
    await select.selectOption(column);
    await expect(select).toHaveValue(column);
    await expect(comparePlot(scope)).toHaveAttribute("data-x", column);
}

/** The plot draws exactly the expected bins for the column, and they are the API's. */
async function expectColumnPlotted(page, scope, candidates, expected, column) {
    const want = sidesOf(expected.scenarios.critic_count_missing.delete_vs_impute[column].bins);
    const fromApi = await apiCompare(page, candidates, column);
    expect(sidesOf(fromApi.bins), `${column}: the API against the expected values`).toEqual(want);
    await expect.poll(() => readComparePlot(scope), { message: `${column}: the plot` }).toEqual(want);
}

test("the docked panel names both nodes and their rows, and plots every column as expected", async ({ page, upload }) => {
    const expected = expectedFor("e2e_games_small");
    const scenario = expected.scenarios.critic_count_missing;
    const candidates = await openDeleteVsImpute(page, upload);
    const panel = page.locator(".compare-panel");

    await expect(page.getByRole("tab", { name: "Compare" })).toHaveAttribute("aria-selected", "true");
    const rows = panel.locator(".compare-node-rows");
    await expect(rows.nth(0)).toHaveText(`${scenario.candidates.delete.rows.toLocaleString()} rows`);
    await expect(rows.nth(1)).toHaveText(`${scenario.candidates.impute.rows.toLocaleString()} rows`);

    for (const column of ["Critic_Score", "Critic_Count", "Platform", "User_Score", "Rating", "Developer"]) {
        await chooseColumn(panel, column);
        await expectColumnPlotted(page, panel, candidates, expected, column);
    }
});

test("the histogram's views - side by side, overlay, difference - and every measure draw", async ({ page, upload }) => {
    const expected = expectedFor("e2e_games_small");
    const candidates = await openDeleteVsImpute(page, upload);
    const panel = page.locator(".compare-panel");
    await chooseColumn(panel, "Critic_Count");

    await choice(panel, "View", "Overlay").click();
    await expect(comparePlot(panel)).toHaveAttribute("data-view", "overlay");
    await expectColumnPlotted(page, panel, candidates, expected, "Critic_Count");

    await choice(panel, "View", "Difference").click();
    await expect(comparePlot(panel)).toHaveAttribute("data-view", "difference");
    const measure = panel.getByLabel("Measure");
    for (const value of ["items", "errors", "missing", "mismatch", "anomaly", "incomplete"]) {
        await measure.selectOption(value);
        await expect(measure).toHaveValue(value);
        await expect(comparePlot(panel).locator("rect").first()).toBeAttached();
    }

    await choice(panel, "View", "Side by side").click();
    await expect(comparePlot(panel)).toHaveAttribute("data-view", "side");
    await expect(measure).toHaveCount(0);
});

test("the heatmap plots two columns, and its axes and measures can be chosen", async ({ page, upload }) => {
    await openDeleteVsImpute(page, upload);
    const panel = page.locator(".compare-panel");

    // What the tiles hold is test_compare_stress.py's to check
    await choice(panel, "Plot type", "Heatmap").click();
    const xAxis = field(panel, "X axis");
    const yAxis = field(panel, "Y axis");
    await xAxis.selectOption("Critic_Score");
    await yAxis.selectOption("Critic_Count");
    await expect(comparePlot(panel)).toHaveAttribute("data-kind", "heatmap");
    await expect(comparePlot(panel).locator("rect").first()).toBeAttached();

    const measure = panel.getByLabel("Measure");
    for (const value of ["items", "errors", "missing"]) {
        await measure.selectOption(value);
        await expect(measure).toHaveValue(value);
    }
    await choice(panel, "View", "Difference").click();
    await expect(comparePlot(panel)).toHaveAttribute("data-view", "difference");
});

test("the drift view draws a numeric column's ridgeline and a categorical column's flows", async ({ page, upload }) => {
    await openDeleteVsImpute(page, upload);
    const panel = page.locator(".compare-panel");

    await choice(panel, "Plot type", "Drift").click();
    await chooseColumn(panel, "Critic_Count");
    await expect(comparePlot(panel)).toHaveAttribute("data-kind", "drift");
    await expect(comparePlot(panel)).toHaveAttribute("data-view", "ridgeline");
    await expect(comparePlot(panel).locator("path").first()).toBeAttached();

    await chooseColumn(panel, "Platform");
    await expect(comparePlot(panel)).toHaveAttribute("data-view", "flows");
    await expect(comparePlot(panel).locator("path, rect").first()).toBeAttached();

    // These two only meet at root, so the common ancestor is offered but off
    await expect(panel.getByRole("radiogroup", { name: "Measured against" }).getByRole("radio", { name: /Common ancestor/ })).toBeDisabled();
    await choice(panel, "Measured against", "Root").click();
});

test("the Sankey's categories can be hidden, searched, and taken out of (other)", async ({ page, upload }) => {
    // What the flows hold is test_drift_stress.py's to check
    await openDeleteVsImpute(page, upload, "e2e_many_labels", "Category");
    const panel = page.locator(".compare-panel");
    await choice(panel, "Plot type", "Drift").click();
    await chooseColumn(panel, "Category");
    await expect(comparePlot(panel)).toHaveAttribute("data-view", "flows");

    const picker = panel.locator(".compare-picker");
    const summary = picker.locator(".compare-picker-summary");
    await summary.click();
    const shown = async () => {
        const text = await summary.innerText();
        const match = /(\d+) of (\d+) shown/.exec(text);
        return { shown: Number(match[1]), of: Number(match[2]) };
    };
    const start = await shown();
    expect(start.shown).toBe(start.of);

    const search = picker.getByLabel("Search categories");
    await search.fill("cat_0");
    await picker.getByRole("button", { name: "Deselect all" }).first().click();
    const afterDeselect = await shown();
    expect(afterDeselect.shown).toBeLessThan(start.shown);
    await picker.getByRole("button", { name: "Select all" }).first().click();
    expect((await shown()).shown).toBe(start.shown);

    await search.fill("");
    await picker.locator('input[type="checkbox"]').first().uncheck();
    expect((await shown()).shown).toBe(start.shown - 1);
    await picker.locator('input[type="checkbox"]').first().check();

    // Taking (other)'s categories out asks for them as bands of their own
    const kept = page.waitForResponse((answer) => answer.url().includes("/api/pgraph/drift_detail")
        && answer.url().includes("keep="));
    await picker.getByTitle(/Draw every category listed in \(other\) as its own band/).click();
    await kept;
    await expect.poll(async () => (await shown()).of).toBeGreaterThan(start.of);

    await picker.getByTitle(/Fold every category taken out of \(other\) back into it/).click();
    await expect.poll(async () => (await shown()).of).toBe(start.of);
});

test("the most changed attributes rank by error change or drift, and a click plots one", async ({ page, upload }) => {
    await openDeleteVsImpute(page, upload);
    const panel = page.locator(".compare-panel");

    const ranked = panel.locator(".compare-ranked-item");
    await expect(ranked.first()).toBeVisible();
    await choice(panel, "Rank attributes by", "Drift").click();
    await choice(panel, "Rank attributes by", "Error change").click();

    const between = field(panel, "Error Δ between");
    for (const value of ["ab", "rootA", "rootB"]) {
        await between.selectOption(value);
        await expect(between).toHaveValue(value);
    }

    const count = await ranked.count();
    for (let index = 0; index < Math.min(count, 4); index += 1) {
        const name = await ranked.nth(index).locator(".compare-ranked-name").innerText();
        await ranked.nth(index).click();
        await expect(field(panel, "Column")).toHaveValue(name);
        await expect(ranked.nth(index)).toHaveClass(/compare-ranked-item--active/);
    }
});

test("Save keeps the comparison on both nodes as compare sub-nodes, and closing it leaves them", async ({ page, upload }) => {
    const candidates = await openDeleteVsImpute(page, upload);
    const panel = page.locator(".compare-panel");

    const saved = page.waitForResponse((response) => response.url().includes("/api/pgraph/support_nodes")
        && response.request().method() === "POST");
    await panel.getByRole("button", { name: "Save" }).click();
    await saved;
    await expect(panel.locator(".compare-saved")).toContainText("Kept on");

    // One compare record on each node, as the server keeps them
    for (const candidate of [candidates.delete, candidates.impute]) {
        const node = await serverNode(page, candidate.table);
        const kinds = [];
        for (const record of node.data.support_nodes ?? []) kinds.push(record.kind);
        expect(kinds, candidate.table).toEqual(["compare"]);
    }
    await openGraph(page);
    const supportNodes = page.locator('.react-flow__node[data-id^="support:"]');
    const drawn = await supportNodes.count();
    expect(drawn).toBeGreaterThanOrEqual(2);

    await panel.getByRole("button", { name: "Close Compare nodes" }).click();
    await expect(page.getByRole("tab", { name: "Compare" })).toHaveCount(0);
    await expect(supportNodes).toHaveCount(drawn);
    await expect(graphNode(page, candidates.delete.table)).toBeVisible();
});

test("popped out, picking another column redraws the plot (Critic_Score → Critic_Count)", async ({ page, upload }) => {
    const expected = expectedFor("e2e_games_small");
    const candidates = await openDeleteVsImpute(page, upload);

    const opened = page.context().waitForEvent("page");
    await page.locator(".compare-panel").getByRole("button", { name: "Pop out" }).click();
    const popup = await opened;
    const panel = popup.locator(".compare-panel");
    await expect(panel).toBeVisible();
    await expect(page.getByRole("tab", { name: "Compare" })).toHaveCount(0);

    await chooseColumn(panel, "Critic_Score");
    await expectColumnPlotted(page, panel, candidates, expected, "Critic_Score");
    await chooseColumn(panel, "Critic_Count");
    await expectColumnPlotted(page, panel, candidates, expected, "Critic_Count");
    // Several more, back and forth, as a user flicking through the columns would
    for (const column of ["Platform", "Critic_Score", "User_Score", "Critic_Count"]) {
        await chooseColumn(panel, column);
        await expectColumnPlotted(page, panel, candidates, expected, column);
    }

    // Docking brings it back into its tab as it was left
    await panel.getByRole("button", { name: "Dock" }).click();
    await expect(page.getByRole("tab", { name: "Compare" })).toBeVisible();
    const docked = page.locator(".compare-panel");
    await expect(field(docked, "Column")).toHaveValue("Critic_Count");
    await expectColumnPlotted(page, docked, candidates, expected, "Critic_Count");
});

test("popped out, the panel's other controls work too", async ({ page, upload }) => {
    await openDeleteVsImpute(page, upload);
    const opened = page.context().waitForEvent("page");
    await page.locator(".compare-panel").getByRole("button", { name: "Pop out" }).click();
    const popup = await opened;
    const panel = popup.locator(".compare-panel");

    await choice(panel, "View", "Overlay").click();
    await expect(comparePlot(panel)).toHaveAttribute("data-view", "overlay");
    await choice(panel, "Plot type", "Heatmap").click();
    await field(panel, "Y axis").selectOption("Critic_Score");
    await expect(comparePlot(panel)).toHaveAttribute("data-kind", "heatmap");
    await choice(panel, "Plot type", "Drift").click();
    await expect(comparePlot(panel)).toHaveAttribute("data-kind", "drift");
    const ranked = panel.locator(".compare-ranked-item").nth(1);
    const name = await ranked.locator(".compare-ranked-name").innerText();
    await ranked.click();
    await expect(field(panel, "Column")).toHaveValue(name);
});

test("closing the popped-out window closes the comparison", async ({ page, upload }) => {
    await openDeleteVsImpute(page, upload);
    const opened = page.context().waitForEvent("page");
    await page.locator(".compare-panel").getByRole("button", { name: "Pop out" }).click();
    const popup = await opened;
    await expect(popup.locator(".compare-panel")).toBeVisible();

    await popup.close({ runBeforeUnload: true });
    await expect(page.getByRole("tab", { name: "Compare" })).toHaveCount(0);
    await expect(page.locator(".compare-panel")).toHaveCount(0);

    // And it opens again from the header, docked
    await headerButton(page, "Compare").click();
    await expect(page.locator(".compare-panel")).toBeVisible();
});

test("popped out, the picker keeps working after docking and popping out again, a new pair and a wrangle", async ({ page, upload }) => {
    const expected = expectedFor("e2e_games_small");
    const candidates = await openDeleteVsImpute(page, upload);

    async function popOut() {
        const opened = page.context().waitForEvent("page");
        await page.locator(".compare-panel").getByRole("button", { name: "Pop out" }).click();
        const popup = await opened;
        await expect(popup.locator(".compare-panel")).toBeVisible();
        return popup;
    }

    let popup = await popOut();
    await popup.locator(".compare-panel").getByRole("button", { name: "Dock" }).click();
    popup = await popOut();
    await chooseColumn(popup.locator(".compare-panel"), "Critic_Count");
    await expectColumnPlotted(page, popup.locator(".compare-panel"), candidates, expected, "Critic_Count");

    // A wrangle in the main window remounts its views; the popped-out panel lives outside them
    await accept(page, candidates.delete.table);
    await chooseColumn(popup.locator(".compare-panel"), "Critic_Score");
    await expectColumnPlotted(page, popup.locator(".compare-panel"), candidates, expected, "Critic_Score");

    // A new pair opened while popped out mounts a fresh panel into the same window
    const graph = await (await page.request.get("/api/routes/update_pgraph")).json();
    let root = null;
    for (const node of graph.nodes) {
        if (node.data.parent === "root") root = node.id;
    }
    await openGraph(page);
    await shiftClick(page, root);
    await headerButton(page, "Compare").click();
    const panel = popup.locator(".compare-panel");
    await expect(panel.locator(".compare-node-chip").first()).toHaveText("n0a");
    for (const column of ["Rating", "Critic_Count"]) {
        await chooseColumn(panel, column);
    }
});
