import { test, expect, expectedFor } from "./fixtures.js";
import { accept, graphNode, headerButton, navigateTo, openGraph } from "./helpers.js";

/* The AI's repairs, with the model mocked: /api/ai/suggest is answered here, never by Gemini. A mock that suggests
   repairs stages real candidates first - through the repair route, the one staging path that needs no model - so
   what the app does with an answer is the real thing: it pulls the graph, and the candidates appear in it. */

/** Answers the next AI request with real candidates for these rows, staged on the node asked about. */
async function suggestRepairsOf(page, rowIds, cols) {
    const asked = [];
    await page.route("**/api/ai/suggest", async (route) => {
        const body = route.request().postDataJSON();
        asked.push(body);
        const staged = await page.request.post("/api/wrangle/create-previews", { data: { row_ids: rowIds, cols } });
        const stagedBody = await staged.json();
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ success: true, node_table: body.node_table, candidates: stagedBody.candidates }),
        });
    });
    return asked;
}

async function answerWith(page, status, payload) {
    await page.route("**/api/ai/suggest", (route) => route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(payload),
    }));
}

test("AI Wrangle asks about the current node, and the repairs it suggests appear in the graph", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    const root = await upload("e2e_tiny");
    const asked = await suggestRepairsOf(page, expected.scenarios.score_missing.row_ids, ["Score"]);

    const answered = page.waitForResponse((response) => response.url().includes("/api/ai/suggest"));
    await headerButton(page, "AI Wrangle").click();
    const body = await (await answered).json();
    expect(asked).toEqual([{ node_table: root }]);

    await openGraph(page);
    // Accepting what was staged is repair.spec.js's to check
    for (const candidate of body.candidates) {
        await expect(graphNode(page, candidate.table)).toBeVisible();
    }
});

test("a node's own AI button asks about that node, not the current one", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    const root = await upload("e2e_tiny");
    // Move off the root first: accept a delete, so n0b is current
    const staged = await page.request.post("/api/wrangle/create-previews", {
        data: { row_ids: expected.scenarios.score_missing.row_ids, cols: ["Score"] },
    });
    const stagedBody = await staged.json();
    await page.reload();
    await openGraph(page);
    await accept(page, stagedBody.candidates[0].table);

    const asked = await suggestRepairsOf(page, [1], ["Count"]);
    const answered = page.waitForResponse((response) => response.url().includes("/api/ai/suggest"));
    await graphNode(page, root).getByRole("button", { name: "AI repairs" }).click();
    await answered;
    expect(asked).toEqual([{ node_table: root }]);
});

test("the model finding nothing to repair says so, and the note can be dismissed", async ({ page, upload }) => {
    const root = await upload("e2e_tiny");
    await answerWith(page, 200, { success: true, node_table: root, no_suggestions: "The table looks clean." });

    await headerButton(page, "AI Wrangle").click();
    const notice = page.locator(".pgraph-ai-notice");
    await expect(notice).toContainText("Nothing to repair here");
    await expect(notice).toContainText("The table looks clean.");
    await notice.click();
    await expect(notice).toHaveCount(0);
    await expect(page.locator(".react-flow__node")).toHaveCount(1);
});

test("a failed request shows its error over the graph, and it can be dismissed", async ({ page, upload, guard }) => {
    guard.allow(/502 from POST .*\/api\/ai\/suggest/);
    await upload("e2e_tiny");
    await answerWith(page, 502, { success: false, error: "The model did not answer" });

    await headerButton(page, "AI Wrangle").click();
    const message = page.locator(".pgraph-collapse-error", { hasText: "The model did not answer" });
    await expect(message).toBeVisible();
    await message.click();
    await expect(message).toHaveCount(0);
    await expect(headerButton(page, "AI Wrangle")).toBeEnabled();
});

test("the AI is off while a candidate is current, and in analysis mode", async ({ page, upload }) => {
    const expected = expectedFor("e2e_tiny");
    await upload("e2e_tiny");
    await suggestRepairsOf(page, expected.scenarios.score_missing.row_ids, ["Score"]);
    const answered = page.waitForResponse((response) => response.url().includes("/api/ai/suggest"));
    await headerButton(page, "AI Wrangle").click();
    const body = await (await answered).json();

    await openGraph(page);
    await navigateTo(page, body.candidates[0].table);
    await expect(headerButton(page, "AI Wrangle")).toBeDisabled();
    await expect(headerButton(page, "AI Wrangle")).toHaveAttribute("title", /Accept this candidate/);
    await expect(graphNode(page, body.candidates[0].table).getByRole("button", { name: "AI repairs" })).toBeDisabled();

    await page.getByRole("radio", { name: "Analysis" }).click();
    await expect(headerButton(page, "AI Wrangle")).toBeDisabled();
});

test("without a model configured, the AI buttons are off and say why", async ({ page, upload }) => {
    await page.route("**/api/ai/status", (route) => route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true, configured: false }),
    }));
    await upload("e2e_tiny");
    await expect(headerButton(page, "AI Wrangle")).toBeDisabled();
    await expect(headerButton(page, "AI Wrangle")).toHaveAttribute("title", /not configured/);
});


