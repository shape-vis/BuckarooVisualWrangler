import { expect } from "@playwright/test";

/**
 * The actions the specs take and the readings they make, named for what a user does: open the graph, pick a bin,
 * repair, accept. Locators are by role, label and text first; the data-* attributes on plot marks and React Flow's
 * own data-id on graph nodes cover what has no accessible name.
 */

// ── Views ────────────────────────────────────────────────────────────────────

/** The header's view toggles are divs, so they are found by their class and text. */
export function viewToggle(page, name) {
    return page.locator(".navButton", { hasText: name });
}

export async function openGraph(page) {
    const toggle = viewToggle(page, "Provenance Graph");
    const isOpen = await toggle.evaluate((element) => element.classList.contains("navButton--selected"));
    if (!isOpen) await toggle.click();
    await expect(page.locator(".react-flow__node").first()).toBeVisible();
}

/** Opens the Plots view on its attribute plots - a docked compare or support-nodes window may be the tab showing. */
export async function openPlots(page) {
    const toggle = viewToggle(page, "Plots");
    const isOpen = await toggle.evaluate((element) => element.classList.contains("navButton--selected"));
    if (!isOpen) await toggle.click();
    const attributesTab = page.getByRole("tab", { name: "Attributes" });
    if ((await attributesTab.getAttribute("aria-selected")) !== "true") await attributesTab.click();
}

/** A header action by its label - the name ends with it, after any icon glyph. */
export function headerButton(page, name) {
    const endsWithLabel = new RegExp(`(^|\\s)${name}$`);
    return page.locator("#header").getByRole("button", { name: endsWithLabel });
}

/** The header's node label: "n0a - e2e_tiny", or a candidate's "c0 - ...". */
export function tableStatus(page) {
    return page.locator(".table-status-label");
}

// ── The graph ────────────────────────────────────────────────────────────────

/** A graph node by its table - React Flow puts the node's id, which is its table, on data-id. */
export function graphNode(page, table) {
    return page.locator(`.react-flow__node[data-id="${table}"]`);
}

/** Where a node is double-clicked: its title - a node's tools and a candidate's buttons keep a double-click to
    themselves, and a candidate's edges are its resize handles. */
export function nodeTitle(page, table) {
    return graphNode(page, table).locator("h3, .prospective-node-title").first();
}

/** Double-clicking a node makes it the current one. */
export async function navigateTo(page, table) {
    const loaded = page.waitForResponse((response) => response.url().includes("/api/setGraphToClickedNode"));
    await nodeTitle(page, table).dblclick();
    await loaded;
    await expect(graphNode(page, table)).toHaveClass(/pgraph-node--current/);
}

/** Shift-click makes a node selection A - shift-clicking it again clears it. */
export async function shiftClick(page, table) {
    await graphNode(page, table).click({ modifiers: ["Shift"] });
}

// ── The main view's plots ────────────────────────────────────────────────────

export function histogram(page, column) {
    return page.locator(`[data-testid="histogram"][data-column="${cssString(column)}"]`).first();
}

function cssString(value) {
    return value.replaceAll("\\", "\\\\").replaceAll("\"", "\\\"");
}

/**
 * What a histogram draws, bin by bin: its rows and its rows per error type, read off the bars' data attributes.
 * @return {Map<string, {type, items, errors: Object<string, number>}>}
 */
export async function readHistogram(page, column) {
    const plot = histogram(page, column);
    await expect(plot.locator("rect[data-bin]").first()).toBeAttached();
    const segments = await plot.locator("rect[data-bin]").evaluateAll((rects) => {
        const read = [];
        for (const rect of rects) {
            read.push({
                bin: rect.getAttribute("data-bin"),
                type: rect.getAttribute("data-bin-type"),
                segment: rect.getAttribute("data-segment"),
                count: Number(rect.getAttribute("data-count")),
                items: Number(rect.getAttribute("data-bin-items")),
            });
        }
        return read;
    });

    const bins = new Map();
    for (const segment of segments) {
        if (!bins.has(segment.bin)) {
            bins.set(segment.bin, { type: segment.type, items: segment.items, errors: {} });
        }
        if (segment.segment !== "none") {
            bins.get(segment.bin).errors[segment.segment] = segment.count;
        }
    }
    return bins;
}

/** An expected histogram (from the expected JSON) in the shape readHistogram returns. */
export function expectedHistogram(expectedPlot) {
    const bins = new Map();
    for (const entry of expectedPlot.bins) {
        const errors = {};
        for (const [key, value] of Object.entries(entry.count)) {
            if (key !== "items" && value > 0) errors[key] = value;
        }
        bins.set(String(entry.xBin), { type: entry.xType, items: entry.count.items, errors });
    }
    return bins;
}

/** A histogram as /api/plots/1-d-histogram sent it, in the shape readHistogram returns. */
export function apiHistogram(histogramPayload) {
    const bins = new Map();
    for (const entry of histogramPayload.histograms) {
        const errors = {};
        for (const [key, value] of Object.entries(entry.count)) {
            if (key !== "items" && value > 0) errors[key] = value;
        }
        bins.set(String(entry.xBin), { type: entry.xType, items: entry.count.items, errors });
    }
    return bins;
}

export function mapToObject(map) {
    const object = {};
    const keys = [...map.keys()].sort();
    for (const key of keys) {
        object[key] = map.get(key);
    }
    return object;
}

/** Clicks one bin of a histogram, which selects its rows. Returns the row ids the server says the bin holds. */
export async function clickBin(page, column, bin) {
    const bar = histogram(page, column).locator(`rect[data-bin="${cssString(String(bin))}"]`).first();
    const answered = page.waitForResponse((response) => response.url().includes("/api/plots/rows-in-bin"));
    await bar.click({ force: true });
    const response = await answered;
    const body = await response.json();
    return body.row_ids;
}

// ── Repairing ────────────────────────────────────────────────────────────────

/**
 * Presses Repair with rows selected, and waits for the candidates to be staged and drawn.
 * @return the staged candidates, as /api/wrangle/create-previews sent them, by op
 */
export async function repair(page) {
    const staged = page.waitForResponse((response) => response.url().includes("/api/wrangle/create-previews"));
    await headerButton(page, "Repair").click();
    const response = await staged;
    const body = await response.json();
    expect(body.success, JSON.stringify(body)).toBe(true);

    const byOp = {};
    for (const candidate of body.candidates) {
        byOp[candidate.op] = candidate;
        await expect(graphNode(page, candidate.table)).toBeVisible();
    }
    return byOp;
}

/** Accepts a candidate from its own node, and waits for the app to land on it. */
export async function accept(page, table) {
    const node = graphNode(page, table);
    const accepted = page.waitForResponse((response) => response.url().includes("/api/candidates/accept"));
    await node.getByRole("button", { name: "Accept" }).click();
    const response = await accepted;
    const body = await response.json();
    expect(body.success, JSON.stringify(body)).toBe(true);
    await expect(tableStatus(page)).toContainText(body.label);
    return body;
}

export async function decline(page, table) {
    const node = graphNode(page, table);
    const declined = page.waitForResponse((response) => response.url().includes("/api/candidates/discard"));
    await node.getByRole("button", { name: "Decline" }).click();
    await declined;
    await expect(node).toHaveCount(0);
}

/** Selects one bin's rows and stages every repair of them. */
// ── Numbers ──────────────────────────────────────────────────────────────────

export function close(actual, expected, digits = 9) {
    if (expected === null || expected === undefined) return actual === null || actual === undefined;
    return Math.abs(actual - expected) <= Math.max(1, Math.abs(expected)) * 10 ** -digits;
}

// ── The attribute list ───────────────────────────────────────────────────────

/** One attribute's row in the attribute list - its name is shortened on screen, so it is found by its title. */
export function attributeRow(page, column) {
    return page.locator("li.attribute-row").filter({
        has: page.locator(`span.attribute-row-name[title="${cssString(column)}"]`),
    });
}

/** The attributes the list shows, by their full names, in the order shown. */
export async function listedAttributes(page) {
    await expect(page.locator("span.attribute-row-name").first()).toBeVisible();
    return page.locator("span.attribute-row-name").evaluateAll((spans) => {
        const names = [];
        for (const span of spans) names.push(span.getAttribute("title"));
        return names;
    });
}

export async function isAttributeSelected(page, column) {
    const toggle = attributeRow(page, column).locator(".rotatedButton--select-toggle");
    return toggle.evaluate((element) => element.classList.contains("rotatedButton--selected"));
}

/** Makes sure an attribute is plotted - or not - by its Select toggle. */
export async function setAttributeSelected(page, column, selected) {
    const toggle = attributeRow(page, column).locator(".rotatedButton--select-toggle");
    if ((await isAttributeSelected(page, column)) !== selected) {
        await toggle.click();
    }
    await expect.poll(() => isAttributeSelected(page, column)).toBe(selected);
}

/** Plots exactly these attributes - at most three, as the matrix keeps. */
export async function plotOnly(page, columns) {
    const listed = await listedAttributes(page);
    for (const column of listed) {
        if (!columns.includes(column)) await setAttributeSelected(page, column, false);
    }
    for (const column of columns) {
        await setAttributeSelected(page, column, true);
    }
    for (const column of columns) {
        await expect(histogram(page, column)).toBeAttached();
    }
}

// ── Reading any node's data ──────────────────────────────────────────────────

/** A node's histogram of one column, read without moving to it - the preview route a candidate's card draws from. */
export async function nodeHistogram(page, table, column) {
    const response = await page.request.get("/api/plots/preview-histogram", {
        params: { type: "1d", tablename: table, column, bins: 10 },
    });
    const body = await response.json();
    expect(body.success, `preview histogram of ${table}.${column}: ${JSON.stringify(body)}`).toBe(true);
    return apiHistogram(body.histogram);
}

/** One node as the server's graph has it: {id, data: {label, provisional, metrics, distortion, ...}}. */
export async function serverNode(page, table) {
    const response = await page.request.get("/api/routes/update_pgraph");
    const graph = await response.json();
    for (const node of graph.nodes) {
        if (node.id === table) return node;
    }
    return null;
}

/** Clicks one heatmap tile, which selects its rows. Returns the row ids the server says the tile holds. */
export async function clickTile(page, xColumn, yColumn, xBin, yBin) {
    const heatmap = page.locator(`[data-testid="heatmap"][data-x-column="${cssString(xColumn)}"][data-y-column="${cssString(yColumn)}"]`).first();
    const tile = heatmap.locator(`rect[data-x-bin="${cssString(String(xBin))}"][data-y-bin="${cssString(String(yBin))}"]`);
    // Near the tile's lower left corner: the matrix's magnifier sits over the top right of each cell. A click within
    // 300ms of the plot clearing its brush - which drawing it does - is ignored as the tail of a drag, so a click
    // that gets no answer is made again, as a user would
    for (let attempt = 0; attempt < 4; attempt += 1) {
        const answered = page.waitForResponse(
            (response) => response.url().includes("/api/plots/rows-in-bin"),
            { timeout: 2_000 },
        ).catch(() => null);
        const box = await tile.boundingBox();
        await tile.click({ force: true, position: { x: 3, y: Math.max(3, box.height - 3) } });
        const response = await answered;
        if (response) {
            const body = await response.json();
            return body.row_ids;
        }
    }
    throw new Error(`clicking tile ${xBin}|${yBin} of ${xColumn} x ${yColumn} selected nothing`);
}

/** Every column of a node, as the expected JSON holds it and as the server plots it, for one assertion each. */
export async function expectNodeHistograms(page, table, expectedNode) {
    for (const [column, plot] of Object.entries(expectedNode.histograms)) {
        const fromApi = await nodeHistogram(page, table, column);
        expect(mapToObject(fromApi), `${table}.${column}`).toEqual(mapToObject(expectedHistogram(plot)));
    }
}
