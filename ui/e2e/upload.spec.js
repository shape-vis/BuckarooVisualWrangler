import path from "node:path";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";

import { test, expect, serverTable, DATA_DIR } from "./fixtures.js";
import { graphNode, headerButton, openGraph, plotOnly, readHistogram, tableStatus } from "./helpers.js";

/* Getting data in: the upload box, the sample datasets, a file the server cannot read, and the way home and back. */

function writeTemporaryCsv(name, text) {
    const folder = mkdtempSync(path.join(tmpdir(), "buckaroo-e2e-"));
    const file = path.join(folder, name);
    writeFileSync(file, text);
    return file;
}

test("uploading a CSV makes it the root and the current table", async ({ page, upload }) => {
    const table = await upload("e2e_tiny");

    await expect(tableStatus(page)).toHaveText(/^n0a - e2e_tiny/);
    expect(await serverTable(page)).toBe(table);

    await openGraph(page);
    await expect(graphNode(page, table)).toBeVisible();
    await expect(graphNode(page, table)).toHaveClass(/pgraph-node--current/);
    await expect(page.locator(".react-flow__node")).toHaveCount(1);
});

test("a sample dataset loads from the home page", async ({ page }) => {
    await page.goto("/");
    const loaded = page.waitForResponse((response) => response.url().includes("/api/preloaded"));
    await page.getByRole("button", { name: /Video Game/ }).click();
    const response = await loaded;
    const body = await response.json();
    expect(body.success).toBe(true);

    await expect(tableStatus(page)).toContainText("games");
    expect(await serverTable(page)).toBe(body.table_name);
});

test("an empty file shows an error on the home page, without a server error", async ({ page, guard }) => {
    // Fixed on October 29, 2026: load_file used to read the CSV outside its try block, so the server answered 500
    guard.allow(/Upload error/);

    await page.goto("/");
    await page.locator("#fileInput").setInputFiles(writeTemporaryCsv("empty.csv", ""));

    await expect(page.locator(".error-box")).toBeVisible();
    await expect(page.getByText("Welcome to Buckaroo!")).toBeVisible();
});

test("a CSV with a header and no rows opens without errors", async ({ page }) => {
    test.info().annotations.push({
        type: "BUG",
        description: "with no rows, set_id_column's ID column is empty, get_sqlalchemy_dtype_map types an empty column "
            + "as Text, and every plot and the table panel then fail joining \"ID\" (text) to row_id (bigint)",
    });
    test.fail();
    await page.goto("/");
    const uploaded = page.waitForResponse((response) => response.url().includes("/api/upload"));
    await page.locator("#fileInput").setInputFiles(writeTemporaryCsv("header_only.csv", "a,b\n"));
    const body = await (await uploaded).json();
    expect(body.success).toBe(true);
    expect(body["rows for undetected data"]).toBe(0);

    await expect(tableStatus(page)).toContainText("header_only");
    await openGraph(page);
    await expect(page.locator(".react-flow__node")).toHaveCount(1);
});

test("columns with quotes, commas, percent signs and reserved words plot without errors", async ({ page }) => {
    const csv = '"quote""d",c%d,"x,y",select\n1,2,3,a\n4,5,6,b\n7,8,9,a\n';
    await page.goto("/");
    const uploaded = page.waitForResponse((response) => response.url().includes("/api/upload"));
    await page.locator("#fileInput").setInputFiles(writeTemporaryCsv("weird_names.csv", csv));
    expect((await (await uploaded).json()).success).toBe(true);

    const columns = ['quote"d', "c%d", "x,y"];
    await plotOnly(page, columns);
    for (const column of columns) {
        const bins = await readHistogram(page, column);
        let rows = 0;
        for (const bin of bins.values()) rows += bin.items;
        expect(rows, column).toBe(3);
    }
});

test("Home goes back to the start, and a new upload replaces the session", async ({ page, upload }) => {
    const first = await upload("e2e_tiny");

    const reset = page.waitForResponse((response) => response.url().includes("/api/reset"));
    await page.getByRole("button", { name: "Home" }).click();
    await reset;
    await expect(page.locator("#fileInput")).toBeAttached();
    await expect(page.getByText("Welcome to Buckaroo!")).toBeVisible();

    const second = await upload("e2e_anomalies");
    expect(second).not.toBe(first);
    expect(await serverTable(page)).toBe(second);
    await openGraph(page);
    await expect(page.locator(".react-flow__node")).toHaveCount(1);
    await expect(graphNode(page, second)).toBeVisible();
});

test("clicking the app's title goes back to the start", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await page.locator("#header h1").click();
    await expect(page.getByText("Welcome to Buckaroo!")).toBeVisible();
});

test("reloading the page stays on the dataset", async ({ page, upload }) => {
    const table = await upload("e2e_tiny");
    await page.reload();
    await expect(tableStatus(page)).toContainText("e2e_tiny");
    expect(await serverTable(page)).toBe(table);
    await expect(headerButton(page, "Undo")).toBeVisible();
});

test("uploading through the upload box's file dialog", async ({ page }) => {
    await page.goto("/");
    const chooser = page.waitForEvent("filechooser");
    await page.locator("#uploadBox").click();
    const fileChooser = await chooser;
    const uploaded = page.waitForResponse((response) => response.url().includes("/api/upload"));
    await fileChooser.setFiles(path.join(DATA_DIR, "e2e_many_labels.csv"));
    const body = await (await uploaded).json();
    expect(body.success).toBe(true);
    await expect(tableStatus(page)).toContainText("e2e_many_labels");
});
