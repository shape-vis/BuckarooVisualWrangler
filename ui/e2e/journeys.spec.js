import { test, expect, serverTable } from "./fixtures.js";
import {
    graphNode, headerButton, listedAttributes, nodeTitle, openGraph, openPlots, setAttributeSelected, tableStatus,
    viewToggle,
} from "./helpers.js";

/* Long walks through the app: a seeded random choice of what a user does next, again and again. Each step is one
   action that makes sense in the state the app is in, and after every step the app must have settled with no error,
   the header must name the node the server is on, and the graph must mark that same node current. A failure names
   the seed and the steps that led to it. */

const STEPS = 25;
const WALKS = [
    { dataset: "e2e_tiny", seed: 11 },
    { dataset: "e2e_games_small", seed: 22 },
    { dataset: "e2e_anomalies", seed: 33 },
    { dataset: "e2e_many_labels", seed: 44 },
];

/* A small seeded generator (mulberry32), so a walk is the same every run */
function seededRandom(seed) {
    let state = seed >>> 0;
    return function next() {
        state = (state + 0x6d2b79f5) >>> 0;
        let mixed = state;
        mixed = Math.imul(mixed ^ (mixed >>> 15), mixed | 1);
        mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
        return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
    };
}

function pick(random, items) {
    return items[Math.floor(random() * items.length)];
}

/* The node part of a table name: "n0b" of "n0b_e2e_tiny_xyz", "c3" of "c3_e2e_tiny_xyz" */
function nodeLabelOf(table) {
    return table.split("_")[0];
}

async function settle(page) {
    await expect(page.locator(".table-status-dot--ready")).toBeVisible();
}

async function graphTables(page) {
    await openGraph(page);
    return page.locator(".react-flow__node").evaluateAll((nodes) => {
        const tables = [];
        for (const node of nodes) {
            const id = node.getAttribute("data-id");
            if (!id.startsWith("support:") && !id.startsWith("collapsed:")) tables.push(id);
        }
        return tables;
    });
}

/* The actions a walk chooses between. Each returns a description of what it did, or null when it does not apply in
   the app's current state - the walk then picks again. */
const ACTIONS = {
    async toggleView(page, random) {
        const name = pick(random, ["Provenance Graph", "Plots"]);
        await viewToggle(page, name).click();
        return `toggle ${name}`;
    },

    async plotAttribute(page, random) {
        await openPlots(page);
        const column = pick(random, await listedAttributes(page));
        const selected = random() < 0.7;
        await setAttributeSelected(page, column, selected);
        return `${selected ? "select" : "deselect"} ${column}`;
    },

    async selectBinAndRepair(page, random) {
        await openPlots(page);
        const plots = page.locator('[data-testid="histogram"]');
        if ((await plots.count()) === 0) return null;
        const plot = plots.nth(Math.floor(random() * (await plots.count())));
        const bars = plot.locator("rect[data-bin]");
        if ((await bars.count()) === 0) return null;
        const bar = bars.nth(Math.floor(random() * (await bars.count())));
        const bin = await bar.getAttribute("data-bin");
        const column = await plot.getAttribute("data-column");

        const answered = page.waitForResponse((response) => response.url().includes("/api/plots/rows-in-bin"));
        await bar.click({ force: true });
        await answered;
        const repairButton = headerButton(page, "Repair");
        if (!(await repairButton.isEnabled())) return `select ${column}[${bin}] (repair locked)`;

        const staged = page.waitForResponse((response) => response.url().includes("/api/wrangle/create-previews"));
        await repairButton.click();
        const body = await (await staged).json();
        expect(body.success, JSON.stringify(body)).toBe(true);
        return `repair ${column}[${bin}]`;
    },

    async acceptOrDecline(page, random) {
        // Staged candidates only, by the server's word: an accepted node keeps its c-prefixed table name
        const drawn = new Set(await graphTables(page));
        const graph = await (await page.request.get("/api/routes/update_pgraph")).json();
        const candidates = [];
        for (const node of graph.nodes) {
            if (node.data.provisional && drawn.has(node.id)) candidates.push(node.id);
        }
        if (candidates.length === 0) return null;
        const table = pick(random, candidates);
        const action = random() < 0.6 ? "Accept" : "Decline";
        const route = action === "Accept" ? "/api/candidates/accept" : "/api/candidates/discard";
        // The candidate can be anywhere in the tree, outside the pane - fitted, every node is on screen
        await page.getByRole("button", { name: "Fit View" }).click();
        const button = graphNode(page, table).getByRole("button", { name: action });
        await expect(button).toBeInViewport();
        const answered = page.waitForResponse((response) => response.url().includes(route), { timeout: 15_000 });
        await button.click({ timeout: 15_000 });
        const body = await (await answered).json();
        expect(body.success, JSON.stringify(body)).toBe(true);
        return `${action.toLowerCase()} ${nodeLabelOf(table)}`;
    },

    async navigate(page, random) {
        const table = pick(random, await graphTables(page));
        const answered = page.waitForResponse((response) => response.url().includes("/api/setGraphToClickedNode"),
            { timeout: 15_000 });
        await page.getByRole("button", { name: "Fit View" }).click();
        await expect(graphNode(page, table)).toBeInViewport();
        await nodeTitle(page, table).dblclick({ timeout: 15_000 });
        await answered;
        return `navigate ${nodeLabelOf(table)}`;
    },

    async undoOrRedo(page, random) {
        const name = random() < 0.5 ? "Undo" : "Redo";
        const route = name === "Undo" ? "/api/undo" : "/api/redo";
        const answered = page.waitForResponse((response) => response.url().includes(route));
        await headerButton(page, name).click();
        await answered;
        return name.toLowerCase();
    },

    async compareSomething(page, random) {
        const tables = await graphTables(page);
        if (tables.length < 2) return null;
        const current = await serverTable(page);
        const others = [];
        for (const table of tables) {
            if (table !== current) others.push(table);
        }
        await page.getByRole("button", { name: "Fit View" }).click();
        const other = pick(random, others);
        await expect(graphNode(page, other)).toBeInViewport();
        await graphNode(page, other).click({ modifiers: ["Shift"], timeout: 15_000 });
        const compare = headerButton(page, "Compare");
        if ((await compare.count()) === 0) return `shift-click ${nodeLabelOf(other)} (cleared)`;
        await compare.click();
        const panel = page.locator(".compare-panel");
        await expect(panel).toBeVisible();
        const select = panel.locator('label.compare-field:has(> span.compare-field-label:text-is("Column")) select');
        const options = await select.locator("option").allInnerTexts();
        const column = pick(random, options);
        await select.selectOption(column);
        await expect(panel.locator('[data-testid="comparison-plot"]')).toHaveAttribute("data-x", column);
        await panel.getByRole("button", { name: "Close Compare nodes" }).click();
        return `compare ${nodeLabelOf(other)} on ${column}`;
    },

    async addSupportNode(page) {
        await openGraph(page);
        await headerButton(page, "Add Support Nodes").click();
        const window = page.locator(".support-window").first();
        await expect(window).toBeVisible();
        await window.getByRole("option", { name: "Quality metrics", exact: true }).click();
        const add = window.locator(".support-window-add");
        if (await add.isEnabled()) {
            const saved = page.waitForResponse((response) => response.url().includes("/api/pgraph/support_nodes"));
            await add.click();
            await saved;
        }
        await window.getByRole("button", { name: /^Close/ }).click();
        return "add quality metrics";
    },

    async openAndCancelSettings(page) {
        await page.getByRole("button", { name: "Settings" }).click();
        await page.getByRole("button", { name: "Cancel" }).click();
        return "settings";
    },
};

/** After every step: settled, and the header, the server and the graph agree on the current node. */
async function expectConsistent(page, history) {
    await settle(page);
    const table = await serverTable(page);
    const where = `after: ${history.join(" → ")}`;
    // A candidate is named by its table's c-prefix; an accepted one keeps its table and is named by its label
    const graph = await (await page.request.get("/api/routes/update_pgraph")).json();
    let label = nodeLabelOf(table);
    for (const node of graph.nodes) {
        if (node.id === table && !node.data.provisional) label = node.data.label;
    }
    await expect(tableStatus(page), where).toHaveText(new RegExp(`^${label} - `));
    if ((await page.locator(".react-flow").count()) > 0 && (await graphNode(page, table).count()) > 0) {
        await expect(graphNode(page, table), where).toHaveClass(/pgraph-node--current/);
    }
    // Every histogram drawn holds every row of the current node
    const plots = page.locator('[data-testid="histogram"]');
    const count = await plots.count();
    if (count > 0 && (await page.getByRole("tab", { name: "Attributes" }).getAttribute("aria-selected")) === "true") {
        let rows = null;
        for (const node of graph.nodes) {
            if (node.id === table) rows = node.data.metrics.row_count;
        }
        for (let index = 0; index < count; index += 1) {
            const plot = plots.nth(index);
            const column = await plot.getAttribute("data-column");
            await expect.poll(async () => {
                const totals = await plot.locator("rect[data-bin]").evaluateAll((rects) => {
                    const byBin = {};
                    for (const rect of rects) byBin[rect.getAttribute("data-bin")] = Number(rect.getAttribute("data-bin-items"));
                    let sum = 0;
                    for (const items of Object.values(byBin)) sum += items;
                    return sum;
                });
                return totals;
            }, { message: `${column} rows, ${where}` }).toBe(rows);
        }
    }
}

for (const { dataset, seed } of WALKS) {
    test(`a ${STEPS}-step walk through ${dataset} (seed ${seed}) never errs and never loses its place`, async ({ page, upload }) => {
        test.setTimeout(180_000);
        const random = seededRandom(seed);
        await upload(dataset);
        const names = Object.keys(ACTIONS);
        const history = [];

        while (history.length < STEPS) {
            const name = pick(random, names);
            const done = await ACTIONS[name](page, random);
            if (done === null) continue;
            history.push(done);
            await expectConsistent(page, history);
        }
    });
}


