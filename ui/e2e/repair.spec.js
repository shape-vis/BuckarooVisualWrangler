import { test, expect, expectedFor, serverTable } from "./fixtures.js";
import {
    accept, clickBin, clickTile, close, decline, expectNodeHistograms, expectedHistogram, graphNode, headerButton,
    histogram, mapToObject, navigateTo, openGraph, openPlots, plotOnly, readHistogram, repair, serverNode,
    tableStatus,
} from "./helpers.js";

/* Repairing a selection: the candidates it stages, what each holds, accepting and declining them, and the two-column
   repairs. Every staged table is held to the expected JSON - its every column's histogram, its fill value, its
   drift - and every accepted one to what its plots then draw. */

/* Each candidate's drift from root, as the server measured it, against the expected values */
async function expectDrift(page, table, expectedDrift) {
    const node = await serverNode(page, table);
    const distortion = node.data.distortion;
    for (const [column, want] of Object.entries(expectedDrift.columns)) {
        const got = distortion.columns[column];
        if (want.value === null) {
            expect(got.value, `${column} drift`).toBeNull();
            expect(got.reason, `${column} reason`).toBe(want.reason);
        } else {
            expect(close(got.value, want.value), `${column} drift ${got.value} vs ${want.value}`).toBe(true);
        }
    }
    if (expectedDrift.overall === null) {
        expect(distortion.overall).toBeNull();
    } else {
        expect(close(distortion.overall, expectedDrift.overall), `overall ${distortion.overall}`).toBe(true);
    }
}

async function selectAndRepair(page, column, bin) {
    await openPlots(page);
    await plotOnly(page, [column]);
    const rowIds = await clickBin(page, column, bin);
    const candidates = await repair(page);
    return { rowIds, candidates };
}

test("a one-column repair stages delete and impute, each holding exactly the expected table", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    const scenario = expected.scenarios.score_missing;
    await upload("e2e_tiny");

    // Which rows the click selects is attributes.spec.js's to check, and which repairs are staged test_candidates.py's
    const { candidates } = await selectAndRepair(page, "Score", "null");

    for (const [op, candidate] of Object.entries(candidates)) {
        const want = scenario.candidates[op];
        await expectNodeHistograms(page, candidate.table, want);
        await expectDrift(page, candidate.table, want.drift);
        const node = await serverNode(page, candidate.table);
        expect(node.data.metrics.row_count).toBe(want.rows);
        await expect(graphNode(page, candidate.table)).toContainText(`${scenario.row_ids.length} selected rows`);
    }
    await expect(graphNode(page, candidates.delete.table)).toContainText("Delete rows");
    await expect(graphNode(page, candidates.impute.table)).toContainText("Impute Score");
});

test("each candidate's preview chart draws its own table", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    await upload("e2e_tiny");
    const { candidates } = await selectAndRepair(page, "Score", "null");

    for (const [op, candidate] of Object.entries(candidates)) {
        const card = graphNode(page, candidate.table).locator(".prospective-node-chart");
        await expect(card.locator("rect[data-bin]").first()).toBeAttached();
        const drawn = await card.locator("rect[data-bin]").evaluateAll((rects) => {
            const bins = {};
            for (const rect of rects) {
                const bin = rect.getAttribute("data-bin");
                bins[bin] = (bins[bin] ?? 0) + Number(rect.getAttribute("data-count"));
            }
            return bins;
        });
        const want = {};
        for (const entry of expected.scenarios.score_missing.candidates[op].histograms.Score.bins) {
            want[String(entry.xBin)] = entry.count.items;
        }
        expect(drawn, op).toEqual(want);
    }
});

test("accepting the delete makes it the current node, and its plots draw the rows left", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    const want = expected.scenarios.score_missing.candidates.delete;
    const root = await upload("e2e_tiny");
    const { candidates } = await selectAndRepair(page, "Score", "null");

    await accept(page, candidates.delete.table);
    await expect(tableStatus(page)).toHaveText(/^n0b - e2e_tiny/);
    expect(await serverTable(page)).toBe(candidates.delete.table);

    // The sibling stays staged; the root stays where it was
    await expect(graphNode(page, candidates.impute.table)).toBeVisible();
    await expect(graphNode(page, root)).toBeVisible();
    await expect(graphNode(page, candidates.delete.table)).toHaveClass(/pgraph-node--current/);

    await openPlots(page);
    await plotOnly(page, ["Score", "Count"]);
    for (const column of ["Score", "Count"]) {
        const drawn = await readHistogram(page, column);
        expect(mapToObject(drawn), column).toEqual(mapToObject(expectedHistogram(want.histograms[column])));
    }
});

test("accepting the impute fills the selection with the column's mean, stored as its type stores it", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    const scenario = expected.scenarios.count_missing;
    await upload("e2e_tiny");
    const { candidates } = await selectAndRepair(page, "Count", "null");

    // The mean of 1..10 is 5.5; Count is an integer column, so the fill is 6
    expect(scenario.candidates.impute.fill).toBe(6);
    await accept(page, candidates.impute.table);
    await openPlots(page);
    await plotOnly(page, ["Count"]);
    const drawn = await readHistogram(page, "Count");
    expect(mapToObject(drawn)).toEqual(mapToObject(expectedHistogram(scenario.candidates.impute.histograms.Count)));
});

test("imputing a categorical column fills the selection with its most common value", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    const scenario = expected.scenarios.rating_missing;
    await upload("e2e_tiny");
    await openPlots(page);
    await plotOnly(page, ["Rating"]);

    // Brush across the two missing bins, "null" and "undefined", the last two on the axis
    const plot = histogram(page, "Rating");
    const nullBar = await plot.locator('rect[data-bin="null"]').first().boundingBox();
    const undefinedBar = await plot.locator('rect[data-bin="undefined"]').first().boundingBox();
    const area = await plot.locator(":scope > rect").first().boundingBox();
    const answered = [];
    page.on("response", (response) => {
        if (response.url().includes("/api/plots/rows-in-bin")) answered.push(response);
    });
    await page.mouse.move(nullBar.x + 2, area.y + 4);
    await page.mouse.down();
    await page.mouse.move(undefinedBar.x + undefinedBar.width - 2, area.y + 6, { steps: 8 });
    await page.mouse.up();
    await expect(headerButton(page, "Repair")).toBeEnabled();
    await expect.poll(() => answered.length).toBe(2);

    const candidates = await repair(page);
    expect(scenario.candidates.impute.fill).toBe("E");
    await expectNodeHistograms(page, candidates.impute.table, scenario.candidates.impute);
    await expectNodeHistograms(page, candidates.delete.table, scenario.candidates.delete);
});

test("declining a candidate removes it from the graph and the server", async ({ page, upload }) => {
    await upload("e2e_tiny");
    const { candidates } = await selectAndRepair(page, "Score", "null");

    await decline(page, candidates.impute.table);
    expect(await serverNode(page, candidates.impute.table)).toBeNull();
    await expect(graphNode(page, candidates.delete.table)).toBeVisible();

    await decline(page, candidates.delete.table);
    expect(await serverNode(page, candidates.delete.table)).toBeNull();
    await expect(page.locator(".react-flow__node")).toHaveCount(1);
});

test("a two-column repair stages delete, impute x and impute y, each holding the expected table", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    const scenario = expected.scenarios.score_count_missing;
    await upload("e2e_tiny");
    await openPlots(page);
    await plotOnly(page, ["Score", "Count"]);

    // The heatmap with Score across and Count up, whichever cell of the matrix it is
    const heatmap = page.locator('[data-testid="heatmap"][data-x-column="Score"][data-y-column="Count"]');
    let xColumn = "Score";
    let yColumn = "Count";
    if ((await heatmap.count()) === 0) {
        xColumn = "Count";
        yColumn = "Score";
    }
    const rowIds = await clickTile(page, xColumn, yColumn, "null", "null");
    expect([...rowIds].sort((a, b) => a - b)).toEqual(scenario.row_ids);

    const candidates = await repair(page);

    // The heatmap's x and y are the selection's own columns, in its order
    const wantByOp = {
        delete: scenario.candidates.delete,
        impute_x: xColumn === "Score" ? scenario.candidates.impute_x : scenario.candidates.impute_y,
        impute_y: xColumn === "Score" ? scenario.candidates.impute_y : scenario.candidates.impute_x,
    };
    for (const [op, candidate] of Object.entries(candidates)) {
        await expectNodeHistograms(page, candidate.table, wantByOp[op]);
    }

    await accept(page, candidates.impute_y.table);
    await openPlots(page);
    await plotOnly(page, [yColumn]);
    const drawn = await readHistogram(page, yColumn);
    expect(mapToObject(drawn)).toEqual(mapToObject(expectedHistogram(wantByOp.impute_y.histograms[yColumn])));
});

test("nothing can be repaired from a candidate until it is accepted", async ({ page, upload }) => {
    await upload("e2e_tiny");
    const { candidates } = await selectAndRepair(page, "Score", "null");

    await openGraph(page);
    await navigateTo(page, candidates.delete.table);
    await openPlots(page);
    await plotOnly(page, ["Count"]);
    await clickBin(page, "Count", "0");
    const repairButton = headerButton(page, "Repair");
    await expect(repairButton).toBeDisabled();
    await expect(repairButton).toHaveAttribute("title", /Accept this candidate/);
});

test("repairs chain: a repair of an accepted node builds on its table", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    await upload("e2e_tiny");

    // Delete Score's missing rows, then impute nothing is left to impute in Score - so delete a bin of Count
    let staged = await selectAndRepair(page, "Score", "null");
    await accept(page, staged.candidates.delete.table);
    staged = await selectAndRepair(page, "Count", "0");
    await accept(page, staged.candidates.delete.table);

    expect(await serverTable(page)).toBe(staged.candidates.delete.table);
    await expect(tableStatus(page)).toHaveText(/^n0c/);
    const node = await serverNode(page, staged.candidates.delete.table);
    // 12 rows, less the two missing Score, less Count's first bin (1 only, after the delete)
    expect(node.data.metrics.row_count).toBe(expected.scenarios.score_missing.candidates.delete.rows - 1);
});

test("the larger dataset: deleting and imputing Critic_Count's missing rows hold the expected tables", async ({ page, upload }) => {
    const expected = expectedFor("e2e_games_small");
    const scenario = expected.scenarios.critic_count_missing;
    await upload("e2e_games_small");
    const { rowIds, candidates } = await selectAndRepair(page, "Critic_Count", "null");
    expect([...rowIds].sort((a, b) => a - b)).toEqual(scenario.row_ids);

    for (const [op, candidate] of Object.entries(candidates)) {
        await expectNodeHistograms(page, candidate.table, scenario.candidates[op]);
        await expectDrift(page, candidate.table, scenario.candidates[op].drift);
    }
});
