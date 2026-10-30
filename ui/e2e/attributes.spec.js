import { test, expect, expectedFor } from "./fixtures.js";
import {
    apiHistogram, attributeRow, clickBin, expectedHistogram, headerButton, histogram, isAttributeSelected,
    listedAttributes, mapToObject, plotOnly, readHistogram, setAttributeSelected,
} from "./helpers.js";

/* The attribute list and the main view's plots: what each column's histogram draws, its error badges, sorting,
   selecting attributes, and selecting rows by clicking and brushing. Every number is held to the expected JSON and to
   the live API. */

const DATASETS = ["e2e_tiny", "e2e_games_small", "e2e_anomalies", "e2e_many_labels"];

async function apiHistogramFor(page, column) {
    const response = await page.request.get("/api/plots/1-d-histogram", { params: { column, bins: 10 } });
    const body = await response.json();
    expect(body.success, `histogram of ${column}: ${JSON.stringify(body)}`).toBe(true);
    return apiHistogram(body.histogram);
}

/* The columns in groups of up to three, the most the matrix plots at once */
function inGroupsOfThree(columns) {
    const groups = [];
    for (let start = 0; start < columns.length; start += 3) {
        groups.push(columns.slice(start, start + 3));
    }
    return groups;
}

for (const dataset of DATASETS) {
    test(`${dataset}: every column's histogram draws the expected bins and error counts`, async ({ page, upload }) => {
        const expected = expectedFor(dataset);
        await upload(dataset);

        for (const group of inGroupsOfThree(expected.columns)) {
            await plotOnly(page, group);
            for (const column of group) {
                const want = expectedHistogram(expected.root.histograms[column]);
                const drawn = await readHistogram(page, column);
                const fromApi = await apiHistogramFor(page, column);

                expect(mapToObject(fromApi), `${column}: the API against the expected values`).toEqual(mapToObject(want));
                expect(mapToObject(drawn), `${column}: the plot against the API`).toEqual(mapToObject(fromApi));
            }
        }
    });

    test(`${dataset}: each attribute's badges show its error rates`, async ({ page, upload }) => {
        const expected = expectedFor(dataset);
        await upload(dataset);
        const rows = expected.root.rows;

        for (const column of expected.columns) {
            const row = attributeRow(page, column);
            await expect(row).toHaveCount(1);
            const counts = expected.root.errors[column];

            let flaggedTypes = 0;
            for (const [errorType, count] of Object.entries(counts)) {
                const badge = row.locator(`.error-scent[data-error-type="${errorType}"]`);
                if (count === 0) {
                    await expect(badge, `${column} ${errorType}`).toHaveCount(0);
                    continue;
                }
                flaggedTypes += 1;
                const percent = ((count / rows) * 100).toFixed(2);
                await expect(badge, `${column} ${errorType}`).toHaveText(`${percent}%`);
            }
            if (flaggedTypes === 0) {
                await expect(row.locator(".error-scent--ok")).toBeVisible();
            }
        }
    });
}

test("the attribute list holds exactly the data columns", async ({ page, upload }) => {
    test.info().annotations.push({
        type: "BUG",
        description: "the structural \"ID\" column is listed as an attribute (\"id\", with a mean and range), though "
            + "every metric, detector and drift measure leaves it out",
    });
    test.fail();
    const expected = expectedFor("e2e_tiny");
    await upload("e2e_tiny");

    const listed = await listedAttributes(page);
    expect([...listed].sort()).toEqual([...expected.columns].sort());
});

test("sorting by each error type orders the attributes by it", async ({ page, upload }) => {
    const expected = expectedFor("e2e_games_small");
    await upload("e2e_games_small");
    const rows = expected.root.rows;

    function rate(column, errorType) {
        const counts = expected.root.errors[column];
        if (!counts) return 0;
        if (errorType === "total") {
            let total = 0;
            for (const count of Object.values(counts)) total += count;
            return total / rows;
        }
        return (counts[errorType] ?? 0) / rows;
    }

    const sortings = [
        ["Missing Values", "missing", "descending"],
        ["Data Type Mismatch", "mismatch", "descending"],
        ["Incomplete Data (< 3 points)", "incomplete", "descending"],
        ["Average Anomalies (Outliers)", "anomaly", "descending"],
        ["None", "total", "ascending"],
        ["Total Error %", "total", "descending"],
    ];
    for (const [label, errorType, direction] of sortings) {
        await page.locator(".attribute-sorting-item", { hasText: label }).click();
        const listed = await listedAttributes(page);
        const dataColumns = [];
        for (const column of listed) {
            if (expected.columns.includes(column)) dataColumns.push(column);
        }
        for (let index = 1; index < dataColumns.length; index += 1) {
            const before = rate(dataColumns[index - 1], errorType);
            const after = rate(dataColumns[index], errorType);
            if (direction === "descending") {
                expect(before, `${label}: ${dataColumns[index - 1]} before ${dataColumns[index]}`).toBeGreaterThanOrEqual(after);
            } else {
                expect(before, `${label}: ${dataColumns[index - 1]} before ${dataColumns[index]}`).toBeLessThanOrEqual(after);
            }
        }
    }
});

test("at most three attributes are plotted, the oldest dropped for a fourth", async ({ page, upload }) => {
    await upload("e2e_tiny");
    // Selected in this order, so Score is the oldest
    for (const column of await listedAttributes(page)) {
        await setAttributeSelected(page, column, false);
    }
    for (const column of ["Score", "Count", "Rating"]) {
        await setAttributeSelected(page, column, true);
    }

    await setAttributeSelected(page, "Platform", true);
    await expect.poll(() => isAttributeSelected(page, "Score")).toBe(false);
    for (const column of ["Count", "Rating", "Platform"]) {
        expect(await isAttributeSelected(page, column)).toBe(true);
        await expect(histogram(page, column)).toBeAttached();
    }
    await expect(histogram(page, "Score")).toHaveCount(0);

    await setAttributeSelected(page, "Rating", false);
    await expect(histogram(page, "Rating")).toHaveCount(0);
});

test("clicking a bin selects exactly its rows, and clicking the background clears them", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    await upload("e2e_tiny");
    await plotOnly(page, ["Score"]);
    await expect(headerButton(page, "Repair")).toBeDisabled();

    const rowIds = await clickBin(page, "Score", "null");
    expect([...rowIds].sort()).toEqual(expected.scenarios.score_missing.row_ids);
    await expect(headerButton(page, "Repair")).toBeEnabled();

    await histogram(page, "Score").locator(":scope > rect").first().click({ position: { x: 3, y: 3 }, force: true });
    await expect(headerButton(page, "Repair")).toBeDisabled();
});

test("brushing across bins selects every row in them", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await plotOnly(page, ["Score"]);
    const plot = histogram(page, "Score");
    const area = await plot.locator(":scope > rect").first().boundingBox();

    // Bins 0-2 of ten numeric bins plus the null bin: the first quarter of the axis. The brush starts above the
    // bars, which are at most half the plot's height here.
    const answered = [];
    page.on("response", (response) => {
        if (response.url().includes("/api/plots/rows-in-bin")) answered.push(response);
    });
    await page.mouse.move(area.x + 4, area.y + 10);
    await page.mouse.down();
    await page.mouse.move(area.x + area.width * 0.2, area.y + 12, { steps: 8 });
    await page.mouse.up();

    await expect(headerButton(page, "Repair")).toBeEnabled();
    await expect.poll(() => answered.length).toBeGreaterThan(0);
    const rowIds = new Set();
    for (const response of answered) {
        const body = await response.json();
        for (const rowId of body.row_ids) rowIds.add(rowId);
    }
    expect([...rowIds].sort((a, b) => a - b)).toEqual([1, 2, 3]);
});

test("no bar is drawn below its plot's floor", async ({ page, upload }) => {
    test.info().annotations.push({
        type: "BUG",
        description: "stackBars subtracts each error type's count from the bin's rows, so a row flagged two ways (Rating's "
            + "\"undefined\" is missing and incomplete) stacks past zero and its bar is drawn below the x axis",
    });
    test.fail();
    await upload("e2e_tiny");
    await plotOnly(page, ["Rating"]);
    const plot = histogram(page, "Rating");
    const floor = Number(await plot.getAttribute("data-height"));

    const bottoms = await plot.locator("rect[data-bin]").evaluateAll((rects) => {
        const read = [];
        for (const rect of rects) {
            read.push(Number(rect.getAttribute("y")) + Number(rect.getAttribute("height")));
        }
        return read;
    });
    for (const bottom of bottoms) {
        expect(bottom).toBeLessThanOrEqual(floor + 0.5);
    }
});

/* What the tiles should hold is test_plots_stress.py's to check; here, that the heatmap draws what the API sends */
test("a heatmap draws the tiles the API sends", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await plotOnly(page, ["Score", "Count"]);
    const heatmap = page.locator('[data-testid="heatmap"][data-x-column="Score"][data-y-column="Count"]').first();
    const tilesInverse = page.locator('[data-testid="heatmap"][data-x-column="Count"][data-y-column="Score"]').first();
    const plotted = (await heatmap.count()) > 0 ? heatmap : tilesInverse;
    await expect(plotted.locator("rect[data-count]").first()).toBeAttached();

    const xColumn = await plotted.getAttribute("data-x-column");
    const yColumn = await plotted.getAttribute("data-y-column");
    const drawn = await plotted.locator("rect[data-count]").evaluateAll((rects) => {
        const tiles = {};
        for (const rect of rects) {
            const key = `${rect.getAttribute("data-x-bin")}|${rect.getAttribute("data-y-bin")}`;
            tiles[key] = Number(rect.getAttribute("data-count"));
        }
        return tiles;
    });

    const response = await page.request.get("/api/plots/2-d-histogram", {
        params: { column_x: xColumn, column_y: yColumn, bins: 10 },
    });
    const body = await response.json();
    const fromApi = {};
    for (const tile of body.histogram.histograms) {
        fromApi[`${tile.xBin}|${tile.yBin}`] = tile.count.items;
    }
    expect(drawn).toEqual(fromApi);
});

/* The table of the most flagged rows, as {row id: {column: error marked on its cell}} - blank rows left out */
async function readErrorTable(page) {
    const table = page.locator("#table");
    await expect(table.locator("tbody tr").first()).toBeAttached();
    return table.evaluate((element) => {
        const headers = [];
        for (const th of element.querySelectorAll("thead th")) headers.push(th.innerText.trim());
        const idIndex = headers.indexOf("ID");
        const rows = { blank: 0, flagged: {} };
        for (const tr of element.querySelectorAll("tbody tr")) {
            const cells = tr.querySelectorAll("td");
            let isBlank = true;
            for (const cell of cells) {
                if (cell.innerText.trim() !== "") isBlank = false;
            }
            if (isBlank) {
                rows.blank += 1;
                continue;
            }
            const marks = {};
            for (let index = 0; index < cells.length; index += 1) {
                const mark = cells[index].getAttribute("data-error");
                if (mark) marks[headers[index]] = mark;
            }
            const rowId = idIndex >= 0 ? cells[idIndex].innerText.trim() : String(Object.keys(rows.flagged).length);
            rows.flagged[rowId] = marks;
        }
        return rows;
    });
}

test("the table of the most flagged rows shows each with its flagged cells marked", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await page.locator(".panel--table .panel-toggle").click();
    await expect(page.locator("#table")).toBeVisible();

    const read = await readErrorTable(page);
    // Row 11: Score and Count blank, Rating "undefined" (missing, and rare); row 12: all three blank; row 6: Rating "M"
    expect(read.flagged).toEqual({
        "11": { Score: "missing", Count: "missing", Rating: "missing" },
        "12": { Score: "missing", Count: "missing", Rating: "missing" },
        "6": { Rating: "incomplete" },
    });
});

test("the table of the most flagged rows has no blank rows when fewer than ten are flagged", async ({ page, upload }) => {
    test.info().annotations.push({
        type: "BUG",
        description: "TableBody always draws maxRows (10) rows, so with three flagged rows seven empty rows follow them",
    });
    test.fail();
    await upload("e2e_tiny");
    await page.locator(".panel--table .panel-toggle").click();
    const read = await readErrorTable(page);
    expect(read.blank).toBe(0);
});

test("the filter dialog opens from an attribute's menu and closes", async ({ page, upload }) => {
    await upload("e2e_tiny");
    const row = attributeRow(page, "Platform");
    await row.locator(".standardButton--menu-trigger").click();
    await row.locator(".rotatedButton--popup-item", { hasText: "Filter" }).click();
    const close = page.locator(".standardButton", { hasText: "Close" });
    await expect(close).toBeVisible();
    await close.click();
    await expect(close).toHaveCount(0);
});

test("the attribute panel collapses and opens again", async ({ page, upload }) => {
    await upload("e2e_tiny");
    const panel = page.locator(".panel--attribute-summary");
    await panel.locator(".panel-toggle").click();
    await expect(panel.locator(".panel-collapse-text")).toHaveText("Attribute Summaries");
    await panel.locator(".panel-toggle").click();
    await expect(attributeRow(page, "Score")).toBeVisible();
});
