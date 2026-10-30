import { test, expect } from "./fixtures.js";
import { clickBin, headerButton, openPlots, plotOnly } from "./helpers.js";

/* The settings dialog, and which header actions are offered when. */

async function axisTextSize(page) {
    return page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--axis-text-size").trim());
}

async function openSettings(page) {
    await page.getByRole("button", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: "Plot Settings" })).toBeVisible();
}

test("each axis text size applies to the plots, and Apply closes the dialog", async ({ page, upload }) => {
    await upload("e2e_tiny");
    await openSettings(page);

    for (const [label, size] of [["S", "7px"], ["M", "9px"], ["L", "12px"]]) {
        const button = page.getByRole("button", { name: label, exact: true });
        await button.click();
        await expect(button).toHaveClass(/settings-toggle-btn--active/);
        expect(await axisTextSize(page)).toBe(size);
    }
    await page.getByRole("button", { name: "Apply" }).click();
    await expect(page.getByRole("heading", { name: "Plot Settings" })).toHaveCount(0);
    expect(await axisTextSize(page)).toBe("12px");
});

test("Cancel leaves the axis text size as it was", async ({ page, upload }) => {
    test.info().annotations.push({
        type: "BUG",
        description: "the size buttons apply the size at once (setAxisTextSize writes --axis-text-size), and Cancel "
            + "only closes the dialog - so a size picked and then cancelled stays",
    });
    test.fail();
    await upload("e2e_tiny");
    await openSettings(page);
    await page.getByRole("button", { name: "M", exact: true }).click();
    await page.getByRole("button", { name: "Apply" }).click();

    await openSettings(page);
    await page.getByRole("button", { name: "L", exact: true }).click();
    await page.getByRole("button", { name: "Cancel" }).click();
    expect(await axisTextSize(page)).toBe("9px");
});

/* Repair's and Compare's own on and off are checked where they are used: attributes.spec.js and graph.spec.js */
test("the header offers each action only when it can be taken", async ({ page, upload }) => {
    await upload("e2e_tiny");

    await expect(headerButton(page, "Undo")).toBeEnabled();
    await expect(headerButton(page, "Redo")).toBeEnabled();
    await expect(headerButton(page, "Add Support Nodes")).toBeEnabled();

    await openPlots(page);
    await plotOnly(page, ["Score"]);
    await clickBin(page, "Score", "0");
    await expect(headerButton(page, "Repair")).toHaveAttribute("title", "Repair Selection");
});
