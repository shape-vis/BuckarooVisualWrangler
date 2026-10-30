import { test as base, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/**
 * What every spec shares: the guard that fails a test on any console error, page error or 5xx response, and the
 * helpers that load a mock dataset through the upload box and read what the app should show for it.
 *
 * The expected values in data/expected/*.json come from the backend stress tests' answer key - see
 * tests/stress/make_e2e_expected.py - so a number the UI shows is checked against the same truth the backend is.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const DATA_DIR = path.join(HERE, "data");

/** The expected values for one mock dataset. */
export function expectedFor(name) {
    const file = path.join(DATA_DIR, "expected", `${name}.json`);
    return JSON.parse(readFileSync(file, "utf-8"));
}

/* Console messages that are the browser reporting a response the test already sees through the response listener -
   a 4xx a test provokes on purpose, say - rather than the app's own errors */
function isResourceNoise(text) {
    return text.startsWith("Failed to load resource");
}

/* Watches one page - the app, or a popped-out window - for anything that should never happen */
function watchPage(page, problems) {
    page.on("console", (message) => {
        if (message.type() !== "error") return;
        const text = message.text();
        if (isResourceNoise(text)) return;
        problems.push(`console.error on ${page.url()}: ${text}`);
    });
    page.on("pageerror", (error) => {
        problems.push(`page error on ${page.url()}: ${error.message}`);
    });
    page.on("response", (response) => {
        if (response.status() >= 500) {
            problems.push(`${response.status()} from ${response.request().method()} ${response.url()}`);
        }
    });
}

/** Reads /api/tablename: the table the backend is on. */
export async function serverTable(page) {
    const response = await page.request.get("/api/tablename");
    const body = await response.json();
    return body.table_name ?? null;
}

/** The graph as the backend has it. */
export async function serverGraph(page) {
    const response = await page.request.get("/api/routes/update_pgraph");
    return response.json();
}

export const test = base.extend({
    /* The AI is never really asked: the server would call Gemini. Every test gets a refusal by default, and a spec
       that drives the AI answers in its own page.route, which takes precedence over this one. */
    context: async ({ context }, provide) => {
        await context.route("**/api/ai/suggest", (route) => route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ success: false, error: "The AI is mocked in the end-to-end tests" }),
        }));
        await provide(context);
    },

    /* Problems seen on any page of the test - checked at the end, so a test fails on an error it did not look for.
       A test that provokes errors on purpose calls allow() with a pattern for each. */
    guard: [async ({ context }, provide) => {
        const problems = [];
        const allowed = [];
        context.on("page", (page) => watchPage(page, problems));
        for (const page of context.pages()) {
            watchPage(page, problems);
        }

        const guard = {
            allow(pattern) {
                allowed.push(pattern);
            },
            problems,
        };
        await provide(guard);

        const unexpected = [];
        for (const problem of problems) {
            let isAllowed = false;
            for (const pattern of allowed) {
                if (pattern.test(problem)) isAllowed = true;
            }
            if (!isAllowed) unexpected.push(problem);
        }
        expect(unexpected, "console errors, page errors or 5xx responses during the test").toEqual([]);
    }, { auto: true }],

    /* Loads a mock dataset through the home page's upload box, as a user would, and waits for the main view.
       Returns the root's table name, from the upload's own response. */
    upload: async ({ page }, provide) => {
        async function upload(name) {
            await page.goto("/");
            const uploaded = page.waitForResponse((response) => response.url().includes("/api/upload"));
            await page.locator("#fileInput").setInputFiles(path.join(DATA_DIR, `${name}.csv`));
            const response = await uploaded;
            const body = await response.json();
            expect(body.success, `upload of ${name}: ${JSON.stringify(body)}`).toBe(true);

            await expect(page.locator(".table-status-label")).toContainText(name);
            upload.lastResponse = body;
            return body.table_name;
        }
        await provide(upload);
    },
});

export { expect };
