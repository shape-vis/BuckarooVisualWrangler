// CompareModal.jsx
// Opened from the header's Compare button while two nodes are paired in the graph: a shift-clicked
// selection A and the current node as selection B. Plot options down the left, the plot itself on the right.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { usePgraph } from "../store/PGraphContext.jsx";
import { getDriftDetail, getNodeComparison } from "../utils/serverCalls.jsx";
import {
    MEASURES, OTHER_LABEL, ROLE_NAMES, describeWrangle, flowCategories, nodeName, otherCategories,
} from "../utils/comparison.js";
import { formatDrift, useDriftNull } from "../utils/drift.js";
import DriftFlag from "./DriftFlag.jsx";
import ComparisonPlot from "../visualizations/ComparisonPlot.jsx";
import "../styles/CompareModal.css";

/* Each plot kind offers the views that make sense for it: a heatmap overlay would be two grids painted
   over one another. Drift draws each node against root rather than against the other, and its views
   depend on the column instead - see DRIFT_VIEWS. */
const PLOT_KINDS = [
    { id: "histogram", label: "Histogram", axes: 1, views: ["side", "overlay", "difference"] },
    { id: "heatmap", label: "Heatmap", axes: 2, views: ["side", "difference"] },
    { id: "drift", label: "Drift", axes: 1, views: null },
];

/* Drift's views: the shape a numeric column now has, and where a categorical one's rows went */
const DRIFT_VIEWS = { numeric: ["ridgeline"], categorical: ["flows"] };

const VIEW_LABELS = {
    side: "Side by side", overlay: "Overlay", difference: "Difference",
    ridgeline: "Ridgeline", flows: "Flows",
};

const RANKINGS = [{ id: "error", label: "Error change" }, { id: "drift", label: "Drift" }];

// How many attributes the most-changed list offers
const RANKED_LIMIT = 8;

// Options can be changed in quick succession, so a request waits for them to settle
const FETCH_DELAY_MS = 150;

/* The window's edges and corners, each with the way it moves the width and height. The window stays
   centred, so it grows on both sides at once: an edge pulled by d changes its side by 2d, which keeps the
   edge under the pointer. */
const EDGES = {
    n: { dx: 0, dy: -1, cursor: "ns-resize" },
    s: { dx: 0, dy: 1, cursor: "ns-resize" },
    e: { dx: 1, dy: 0, cursor: "ew-resize" },
    w: { dx: -1, dy: 0, cursor: "ew-resize" },
    ne: { dx: 1, dy: -1, cursor: "nesw-resize" },
    sw: { dx: -1, dy: 1, cursor: "nesw-resize" },
    nw: { dx: -1, dy: -1, cursor: "nwse-resize" },
    se: { dx: 1, dy: 1, cursor: "nwse-resize" },
};
// Below this the options column and the plot crowd each other out
const MIN_WINDOW = { width: 760, height: 520 };

// The size the window was last pulled to, kept for the next time it opens; null is the stylesheet's default
let rememberedSize = null;

// One empty list, so a column with nothing hidden hands the plot the same array every render
const NO_CATEGORIES = [];

/* A folded run stands in for its last node - the state the run arrives at, and whose metrics it
   already reports - so that is the table it is compared as. */
function tableOf(node, id) {
    return node?.type === "collapsedNode" ? node.data.tail : id;
}

function formatRate(rate) {
    return rate == null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

const signedRows = (change) => `${change > 0 ? "+" : "−"}${Math.abs(change).toLocaleString()} rows`;

/* The Drift kind's data: each node's breakdown against root. Both are measured from root, so a categorical
   column's two Sankeys share root's categories - the Flows view draws them as one, root in the middle. */
async function getDriftComparison({ a, b, x, keep }, signal) {
    const [detailA, detailB] = await Promise.all([
        getDriftDetail({ node: a, column: x, keep }, signal),
        getDriftDetail({ node: b, column: x, keep }, signal),
    ]);
    const failed = [detailA, detailB].find((response) => !response?.success);
    if (failed) return { success: false, error: failed?.error };
    return { success: true, kind: "drift", x, a: detailA, b: detailB };
}

/* A change in error rate, in percentage points. Errors going down is an improvement. */
function RateDelta({ delta }) {
    const points = delta * 100;
    const direction = points <= -0.05 ? "improved" : points >= 0.05 ? "worsened" : "flat";
    const text = direction === "flat" ? "±0.0" : `${points > 0 ? "+" : "−"}${Math.abs(points).toFixed(1)}`;
    return <span className={`compare-delta compare-delta--${direction}`}>{text} pts</span>;
}

/* One node in the header: its chip, the wrangle that produced it, and where that wrangle started.
   The row change is against that parent - a delete's footprint - not against the other node. */
function NodeSummary({ role, table, data, parentData, foldedCount }) {
    const sentence = describeWrangle(data?.wrangle);
    const parent = data?.parent && data.parent !== "root" ? data.parent : null;
    const rows = data?.metrics?.row_count;
    const parentRows = parentData?.metrics?.row_count;
    const rowChange = (rows != null && parentRows != null) ? rows - parentRows : 0;

    return (
        <span className="compare-node-summary">
            <span className={`compare-node-chip compare-node-chip--${role}`} title={table}>{nodeName(table)}</span>
            {sentence && <span className="compare-wrangle">{sentence}</span>}
            {parent && <span className="compare-wrangle-meta" title={parent}>from {nodeName(parent)}</span>}
            {rowChange !== 0 && <span className="compare-wrangle-meta">{signedRows(rowChange)}</span>}
            {foldedCount && <span className="compare-wrangle-meta">last of {foldedCount} folded nodes</span>}
        </span>
    );
}

function Segmented({ label, options, value, onChange }) {
    return (
        <div className="compare-segmented" role="radiogroup" aria-label={label}>
            {options.map((option) => (
                <button
                    key={option.id}
                    type="button"
                    role="radio"
                    aria-checked={value === option.id}
                    className={`compare-segment ${value === option.id ? "compare-segment--active" : ""}`}
                    onClick={() => onChange(option.id)}
                >
                    {option.label}
                </button>
            ))}
        </div>
    );
}

function AttributeSelect({ label, value, onChange, attributes }) {
    return (
        <label className="compare-field">
            <span className="compare-field-label">{label}</span>
            <select className="compare-select" value={value} onChange={(event) => onChange(event.target.value)}>
                {attributes.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
        </label>
    );
}

/* Which of a column's categories the Sankey draws. Everything the server sent is listed and ticked by
   default; unticking one hides its band, which is the same thing the plot's own bar-and-Delete does. The
   long tail the server folded into "(other)" is listed under it with each category's rows - ticking one of
   those asks the server for it as a band of its own, so those cost a request and the rest do not. */
function CategoryPicker({ categories, hidden, other, onHidden, onKeep }) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState("");
    const boxRef = useRef(null);

    // A click anywhere else closes the list, as a select would
    useEffect(() => {
        if (!open) return undefined;
        const onDown = (event) => {
            if (!boxRef.current?.contains(event.target)) setOpen(false);
        };
        document.addEventListener("mousedown", onDown);
        return () => document.removeEventListener("mousedown", onDown);
    }, [open]);

    const matches = (label) => label.toLowerCase().includes(query.trim().toLowerCase());
    const shownCount = categories.filter((label) => !hidden.includes(label)).length;
    const toggle = (label) => onHidden(hidden.includes(label)
        ? hidden.filter((name) => name !== label)
        : [...hidden, label]);

    /* Select and deselect all work on what the search leaves listed, so a search plus one click covers a
       run of categories. They leave the catch-all's own list alone: each of those costs a request. */
    const listed = categories.filter(matches);
    const noneHidden = listed.every((label) => !hidden.includes(label));
    const allHidden = listed.every((label) => hidden.includes(label));
    const selectAll = () => onHidden(hidden.filter((label) => !listed.includes(label)));
    const deselectAll = () => onHidden([...new Set([...hidden, ...listed])]);

    return (
        <div className="compare-picker" ref={boxRef}>
            <button
                type="button"
                className="compare-picker-summary"
                aria-expanded={open}
                onClick={() => setOpen((was) => !was)}
            >
                <span>{shownCount} of {categories.length} shown</span>
                <span aria-hidden="true">▾</span>
            </button>
            {open && (
                <div className="compare-picker-list">
                    <input
                        className="compare-picker-search"
                        type="search"
                        value={query}
                        placeholder="Search categories"
                        aria-label="Search categories"
                        onChange={(event) => setQuery(event.target.value)}
                    />
                    <div className="compare-picker-actions">
                        <button
                            type="button"
                            className="compare-picker-action"
                            disabled={noneHidden}
                            title="Show every category listed here"
                            onClick={selectAll}
                        >
                            Select all
                        </button>
                        <button
                            type="button"
                            className="compare-picker-action"
                            disabled={allHidden}
                            title="Hide every category listed here"
                            onClick={deselectAll}
                        >
                            Deselect all
                        </button>
                    </div>
                    <div className="compare-picker-scroll">
                        {listed.map((label) => (
                            <label key={label} className="compare-picker-item">
                                <input
                                    type="checkbox"
                                    checked={!hidden.includes(label)}
                                    onChange={() => toggle(label)}
                                />
                                <span className="compare-picker-name" title={label}>{label}</span>
                            </label>
                        ))}
                        {other.categories.length > 0 && (
                            <>
                                <div className="compare-picker-group">
                                    In {OTHER_LABEL}
                                    {other.more > 0 && <span> · {other.more} more not listed</span>}
                                </div>
                                {other.categories.filter((row) => matches(row.category)).map((row) => (
                                    <label key={row.category} className="compare-picker-item">
                                        <input type="checkbox" checked={false} onChange={() => onKeep(row.category)} />
                                        <span className="compare-picker-name" title={row.category}>{row.category}</span>
                                        <span className="compare-picker-rows">{row.rows.toLocaleString()}</span>
                                    </label>
                                ))}
                            </>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

function NodeRow({ role, table, rows }) {
    return (
        <div className="compare-node-row">
            <span className={`compare-role compare-role--${role}`}>{ROLE_NAMES[role]}</span>
            <span className="compare-node-name" title={table}>{nodeName(table)}</span>
            {rows != null && <span className="compare-node-rows">{rows.toLocaleString()} rows</span>}
        </div>
    );
}

/* Each node's drift from root. Both are measured against the same fixed reference rather than one against
   the other - that is what makes nodes on different branches comparable at all. */
function DriftSummary({ tableA, tableB, driftA, driftB }) {
    return (
        <dl className="compare-changes">
            <div><dt title={tableA}>{nodeName(tableA)} · selection A</dt><dd>{formatDrift(driftA)}</dd></div>
            <div><dt title={tableB}>{nodeName(tableB)} · selection B</dt><dd>{formatDrift(driftB)}</dd></div>
        </dl>
    );
}

/**
 * Props:
 *  - pair: {a, b} node ids for selection A and selection B, as PGraphContext's comparisonPair names them
 *  - onClose: called on the close button, a backdrop click or Escape
 */
export default function CompareModal({ pair, onClose }) {
    const { nodes, serverNodesById } = usePgraph();
    const dialogRef = useRef(null);

    /* The window's size once pulled by an edge, or null for the stylesheet's. The plot measures its own
       canvas, so it redraws to fit as the window changes. */
    const [size, setSize] = useState(() => rememberedSize);
    // The edge being pulled, whose cursor the whole page shows until it is let go
    const [resizing, setResizing] = useState(null);
    useEffect(() => {
        rememberedSize = size;
    }, [size]);

    /* Pulls the window by one edge. The pointer is captured, so a drag that ends over the backdrop is not a
       click on it. The window can grow to fill the overlay, but not past it. */
    const startResize = (edge) => (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        const handle = event.currentTarget;
        const { dx, dy } = EDGES[edge];
        const overlay = dialogRef.current.parentElement;
        const style = getComputedStyle(overlay);
        const room = {
            width: overlay.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
            height: overlay.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom),
        };
        const box = dialogRef.current.getBoundingClientRect();
        const clamp = (value, key) => Math.round(Math.min(room[key], Math.max(Math.min(MIN_WINDOW[key], room[key]), value)));

        const move = (moveEvent) => setSize({
            width: clamp(box.width + 2 * dx * (moveEvent.clientX - event.clientX), "width"),
            height: clamp(box.height + 2 * dy * (moveEvent.clientY - event.clientY), "height"),
        });
        const end = () => {
            handle.removeEventListener("pointermove", move);
            handle.removeEventListener("pointerup", end);
            handle.removeEventListener("pointercancel", end);
            setResizing(null);
        };
        handle.setPointerCapture(event.pointerId);
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", end);
        handle.addEventListener("pointercancel", end);
        setResizing(edge);
    };

    const nodesById = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes]);

    const idA = pair.a;
    const idB = pair.b;
    const tableA = tableOf(nodesById[idA], idA);
    const tableB = tableOf(nodesById[idB], idB);

    /* Read by the real table rather than by what is drawn, so a node folded out of view - the current
       node inside a collapsed run - still has its metrics and its wrangle. */
    const dataFor = (table, id) => (serverNodesById?.[table] ?? nodesById[id])?.data;
    const dataA = dataFor(tableA, idA);
    const dataB = dataFor(tableB, idB);
    const metricsA = dataA?.metrics;
    const metricsB = dataB?.metrics;
    const distortionA = dataA?.distortion;
    const distortionB = dataB?.distortion;
    // Fetched as the modal opens, for the flags beside each drift - only a node that lost rows can have any
    const nullA = useDriftNull(tableA, distortionA?.facts?.rows_removed);
    const nullB = useDriftNull(tableB, distortionB?.facts?.rows_removed);
    const foldedCount =(id) => (nodesById[id]?.type === "collapsedNode" ? nodesById[id].data.run?.length : null);

    // Every attribute either side knows of, in the order the metrics list them
    const attributes = useMemo(() => [...new Set([
        ...Object.keys(metricsA?.columns ?? {}),
        ...Object.keys(metricsB?.columns ?? {}),
    ])], [metricsA, metricsB]);

    /* The same attributes ranked by how far their error rate moved, or by how far either node has drifted
       from root. Read from what each node already carries, so it costs no request - and ranked by error
       it gives the plot a sensible first attribute: the one the wrangles between these two touched most.
       Error and drift stay two numbers: a column no operation touched can show no error change and still
       have drifted, which is exactly what this list is for. */
    const [rankBy, setRankBy] = useState("error");
    const ranked = useMemo(() => attributes
        .map((name) => {
            const before = metricsA?.columns?.[name]?.total ?? null;
            const after = metricsB?.columns?.[name]?.total ?? null;
            const driftA = distortionA?.columns?.[name]?.value ?? null;
            const driftB = distortionB?.columns?.[name]?.value ?? null;
            return { name, before, after, delta: (after ?? 0) - (before ?? 0), driftA, driftB };
        })
        /* An attribute that neither node moved has nothing to say, so it is left out entirely. The test is
           for exactly zero rather than for what the row would print: a column no operation touched usually
           drifts by a fraction that shows as 0.000, and those are the rows the metric exists to surface. */
        .filter((attribute) => attribute.delta !== 0 || attribute.driftA || attribute.driftB)
        .sort((a, b) => (rankBy === "drift"
            ? Math.max(b.driftA ?? 0, b.driftB ?? 0) - Math.max(a.driftA ?? 0, a.driftB ?? 0)
            : Math.abs(b.delta) - Math.abs(a.delta))),
    [attributes, metricsA, metricsB, distortionA, distortionB, rankBy]);

    const [kind, setKind] = useState("histogram");
    /* The plot opens on what moved most. When nothing moved the ranking is empty, so it falls back to the
       attributes themselves rather than leaving the modal with nothing to plot. */
    const [x, setX] = useState(() => ranked[0]?.name ?? attributes[0] ?? "");
    const [y, setY] = useState(() => ranked[1]?.name ?? ranked[0]?.name ?? attributes[1] ?? attributes[0] ?? "");
    const [view, setView] = useState("side");
    const [measure, setMeasure] = useState("items");
    const [result, setResult] = useState({ key: null, data: null, error: null });

    /* Which of a categorical column's categories the Sankey draws. hidden is the reader's own doing and
       costs nothing - the rows are already here, so the bands simply go. kept names categories the server
       would otherwise fold into its catch-all, so changing it asks for the flows again. Both belong to one
       column of one pair: the choice is stamped with that, and another column reads it as never made. */
    const columnKey = [tableA, tableB, x].join("|");
    const [choice, setChoice] = useState({ key: null, hidden: NO_CATEGORIES, kept: null });
    const chosen = choice.key === columnKey ? choice : { hidden: NO_CATEGORIES, kept: null };
    const { hidden, kept } = chosen;
    const setHidden = useCallback((next) => setChoice((was) => ({
        key: columnKey,
        hidden: typeof next === "function" ? next(was.key === columnKey ? was.hidden : NO_CATEGORIES) : next,
        kept: was.key === columnKey ? was.kept : null,
    })), [columnKey]);

    const spec = PLOT_KINDS.find((plotKind) => plotKind.id === kind);
    // Drift's views follow the column - numeric or categorical, as root decided it
    const columnKind = (distortionA?.columns?.[x] ?? distortionB?.columns?.[x])?.kind;
    const views = kind === "drift" ? DRIFT_VIEWS[columnKind] ?? DRIFT_VIEWS.numeric : spec.views;
    // A view this kind does not offer falls back to its first, keeping the choice for later
    const activeView = views.includes(view) ? view : (kind === "drift" ? views[0] : "side");
    const usesMeasure = kind === "heatmap" || activeView === "difference";
    const yColumn = spec.axes === 2 ? y : null;

    /* Names the request the current options call for. A result is only current when it carries this
       key, which is how loading is known without any state of its own. */
    const requestKey = [tableA, tableB, kind, x, yColumn, kept?.join(",") ?? ""].join("|");
    const loading = Boolean(x) && result.key !== requestKey;
    const current = result.key === requestKey ? result : null;
    // While the next result loads, the last one of the same kind stays up, dimmed
    const plotData = result.data?.kind === kind ? result.data : null;

    // The Sankey's categories as the current result has them, and what its catch-all holds
    const plotCategories = useMemo(
        () => (plotData?.kind === "drift" ? flowCategories(plotData) : []), [plotData]);
    const plotOther = useMemo(
        () => (plotData?.kind === "drift" ? otherCategories(plotData) : { categories: [], more: 0 }), [plotData]);

    const hideCategory = useCallback((category) => setHidden((was) => (
        was.includes(category) ? was : [...was, category])), [setHidden]);

    /* Taking a category back out of the catch-all: the server has to redraw the flows for it, so the ask is
       the categories it already draws plus this one. It comes back shown, whatever it was before. */
    const keepCategory = (category) => setChoice({
        key: columnKey,
        hidden: hidden.filter((label) => label !== category),
        kept: [...(kept ?? plotCategories.filter((label) => label !== OTHER_LABEL)), category],
    });

    useEffect(() => {
        if (!x) return;

        const controller = new AbortController();
        const timer = setTimeout(async () => {
            try {
                const response = kind === "drift"
                    ? await getDriftComparison({ a: tableA, b: tableB, x, keep: kept }, controller.signal)
                    : await getNodeComparison(
                        { a: tableA, b: tableB, kind, x, y: yColumn },
                        controller.signal,
                    );
                setResult(response?.success
                    ? { key: requestKey, data: response, error: null }
                    : { key: requestKey, data: null, error: response?.error || "The comparison failed" });
            } catch (error) {
                // A request superseded by newer options is aborted on purpose, and is not a failure
                if (error.name !== "AbortError") {
                    setResult({ key: requestKey, data: null, error: error.message });
                }
            }
        }, FETCH_DELAY_MS);

        return () => {
            clearTimeout(timer);
            controller.abort();
        };
    }, [requestKey, tableA, tableB, kind, x, yColumn, kept]);

    useEffect(() => {
        dialogRef.current?.focus();
        const onKeyDown = (event) => {
            if (event.key === "Escape") onClose();
        };
        document.addEventListener("keydown", onKeyDown);
        return () => document.removeEventListener("keydown", onKeyDown);
    }, [onClose]);

    const rowsA = metricsA?.row_count;
    const rowsB = metricsB?.row_count;

    // Portaled to <body> so it sits above the fixed header, whose stacking context would trap it
    return createPortal(
        <div
            className={`compare-overlay ${resizing ? "compare-overlay--resizing" : ""}`}
            style={resizing ? { "--compare-resize-cursor": EDGES[resizing].cursor } : undefined}
            onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
        >
            <div
                ref={dialogRef}
                className="compare-window"
                style={size ?? undefined}
                role="dialog"
                aria-modal="true"
                aria-labelledby="compare-title"
                tabIndex={-1}
            >
                <header className="compare-header">
                    <div className="compare-heading">
                        <h2 id="compare-title" className="compare-title">Compare nodes</h2>
                        <div className="compare-subtitle">
                            <NodeSummary
                                role="a"
                                table={tableA}
                                data={dataA}
                                parentData={serverNodesById?.[dataA?.parent]?.data}
                                foldedCount={foldedCount(idA)}
                            />
                            <span className="compare-subtitle-arrow" aria-hidden="true">→</span>
                            <NodeSummary
                                role="b"
                                table={tableB}
                                data={dataB}
                                parentData={serverNodesById?.[dataB?.parent]?.data}
                                foldedCount={foldedCount(idB)}
                            />
                        </div>
                    </div>
                    <button type="button" className="compare-close" onClick={onClose} aria-label="Close comparison">×</button>
                </header>

                <div className="compare-body">
                    <aside className="compare-options" aria-label="Plot options">
                        <section className="compare-section">
                            <h3 className="compare-section-title">Nodes</h3>
                            <NodeRow role="a" table={tableA} rows={rowsA} />
                            <NodeRow role="b" table={tableB} rows={rowsB} />
                        </section>

                        <section className="compare-section">
                            <h3 className="compare-section-title">Plot</h3>
                            <Segmented label="Plot type" options={PLOT_KINDS} value={kind} onChange={setKind} />
                        </section>

                        <section className="compare-section">
                            <h3 className="compare-section-title">{spec.axes === 1 ? "Attribute" : "Attributes"}</h3>
                            {attributes.length === 0 ? (
                                <div className="compare-muted">These nodes carry no attribute metrics.</div>
                            ) : (
                                <>
                                    <AttributeSelect
                                        label={spec.axes === 1 ? "Column" : "X axis"}
                                        value={x}
                                        onChange={setX}
                                        attributes={attributes}
                                    />
                                    {spec.axes === 2 && (
                                        <AttributeSelect label="Y axis" value={y} onChange={setY} attributes={attributes} />
                                    )}
                                </>
                            )}
                        </section>

                        {/* A kind with one view has nothing to choose - a drift column is always drawn the one way */}
                        {views.length > 1 && (
                            <section className="compare-section">
                                <h3 className="compare-section-title">View</h3>
                                <Segmented
                                    label="View"
                                    options={views.map((id) => ({ id, label: VIEW_LABELS[id] }))}
                                    value={activeView}
                                    onChange={setView}
                                />
                            </section>
                        )}

                        {/* The Sankey's own categories: which ones it draws, and what the catch-all holds */}
                        {kind === "drift" && activeView === "flows" && plotCategories.length > 0 && (
                            <section className="compare-section">
                                <h3 className="compare-section-title">Categories</h3>
                                <CategoryPicker
                                    categories={plotCategories}
                                    hidden={hidden}
                                    other={plotOther}
                                    onHidden={setHidden}
                                    onKeep={keepCategory}
                                />
                            </section>
                        )}

                        {usesMeasure && (
                            <section className="compare-section">
                                <h3 className="compare-section-title">Measure</h3>
                                <select
                                    className="compare-select"
                                    value={measure}
                                    onChange={(event) => setMeasure(event.target.value)}
                                    aria-label="Measure"
                                >
                                    {Object.entries(MEASURES).map(([id, { label }]) => (
                                        <option key={id} value={id}>{label}</option>
                                    ))}
                                </select>
                            </section>
                        )}

                        <section className="compare-section">
                            <h3 className="compare-section-title compare-section-title--drift">
                                Distortion from root
                            </h3>
                            <DriftSummary
                                tableA={tableA}
                                tableB={tableB}
                                driftA={distortionA?.overall}
                                driftB={distortionB?.overall}
                            />
                        </section>

                        {ranked.length > 0 && (
                            <section className="compare-section">
                                <h3 className="compare-section-title">Most changed attributes</h3>
                                <Segmented label="Rank attributes by" options={RANKINGS} value={rankBy} onChange={setRankBy} />
                                <div className="compare-ranked-head" aria-hidden="true">
                                    <span>attribute</span>
                                    <span>error Δ</span>
                                    <span>drift · A / B</span>
                                </div>
                                <ol className="compare-ranked">
                                    {ranked.slice(0, RANKED_LIMIT).map((attribute) => (
                                        <li key={attribute.name}>
                                            <button
                                                type="button"
                                                className={`compare-ranked-item ${attribute.name === x ? "compare-ranked-item--active" : ""}`}
                                                onClick={() => setX(attribute.name)}
                                                title={`${attribute.name}: error rate ${formatRate(attribute.before)} → ${formatRate(attribute.after)}; `
                                                    + `drift from root ${formatDrift(attribute.driftA)} in selection A, `
                                                    + `${formatDrift(attribute.driftB)} in selection B. Click to plot it.`}
                                            >
                                                <span className="compare-ranked-name">{attribute.name}</span>
                                                <RateDelta delta={attribute.delta} />
                                                <span className="compare-ranked-drift">
                                                    {formatDrift(attribute.driftA)}
                                                    <DriftFlag result={nullA[attribute.name]} />
                                                    {" / "}
                                                    {formatDrift(attribute.driftB)}
                                                    <DriftFlag result={nullB[attribute.name]} />
                                                </span>
                                            </button>
                                        </li>
                                    ))}
                                </ol>
                            </section>
                        )}
                    </aside>

                    <section className={`compare-plot ${loading ? "compare-plot--loading" : ""}`} aria-busy={loading}>
                        <ComparisonPlot
                            data={plotData}
                            view={activeView}
                            measure={measure}
                            labelA={nodeName(tableA)}
                            labelB={nodeName(tableB)}
                            hidden={hidden}
                            onHide={hideCategory}
                        />
                        {loading && (
                            <div className="compare-plot-status"><span className="compare-plot-pill">Loading…</span></div>
                        )}
                        {!loading && current?.error && (
                            <div className="compare-plot-status">
                                <span className="compare-plot-pill compare-plot-pill--error">{current.error}</span>
                            </div>
                        )}
                        {!x && (
                            <div className="compare-plot-status"><span className="compare-plot-pill">Nothing to plot</span></div>
                        )}
                    </section>
                </div>

                {/* Every edge and corner pulls the window; a double-click puts it back to its usual size */}
                {Object.entries(EDGES).map(([edge, { cursor }]) => (
                    <div
                        key={edge}
                        className={`compare-resize compare-resize--${edge}`}
                        style={{ cursor }}
                        aria-hidden="true"
                        onPointerDown={startResize(edge)}
                        onDoubleClick={() => setSize(null)}
                    />
                ))}
            </div>
        </div>,
        document.body,
    );
}
