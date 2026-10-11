// ComparePanel.jsx
// Opened from the header's Compare button while two nodes are paired in the graph: a shift-clicked
// selection A and the current node as selection B. Plot options down the left, the plot itself on the right.
// Shown docked as the Plots view's Compare tab or popped out into a window of its own - CompareContext
// decides where, and this never needs to know beyond which window it is in (useHostWindow).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePgraph } from "../store/PGraphContext.jsx";
import { useHostWindow } from "../store/HostWindowContext.jsx";
import {
    MEASURES, OTHER_LABEL, PLOT_KINDS, ROLE_NAMES, VIEW_LABELS, commonAncestor, describeWrangle, flowCategories,
    nodeName, otherCategories, viewsFor,
} from "../utils/comparison.js";
import { SPEC_VERSION, driftZoomKey, settingsOf, specFromSettings } from "../utils/comparisonSpec.js";
import { useComparisonData } from "../visualizations/useComparisonData.js";
import { formatDrift } from "../utils/drift.js";
import ComparisonPlot from "../visualizations/ComparisonPlot.jsx";
import "../styles/ComparePanel.css";

const RANKINGS = [{ id: "error", label: "Error change" }, { id: "drift", label: "Drift" }];

/* The two states the most-changed list's error change runs between. A → B compares the selections
   directly; the root options show how far one selection has come from the upload, so a change both
   selections share does not cancel out of the column. */
const ERROR_DELTAS = [
    { id: "ab", label: "Selection A → Selection B", from: "a", to: "b" },
    { id: "rootA", label: "Root → Selection A", from: "root", to: "a" },
    { id: "rootB", label: "Root → Selection B", from: "root", to: "b" },
];
const STATE_NAMES = { root: "root", a: "selection A", b: "selection B" };
// With one node there is no other to measure against, only how far it has come from the upload
const SINGLE_ERROR_DELTAS = [{ id: "rootB", label: "Root → this node", from: "root", to: "b" }];

// How many attributes the most-changed list offers
const RANKED_LIMIT = 8;

// Settings changes are reported once they settle, rather than on every step of a drag
const REPORT_DELAY_MS = 400;

// One empty list, so a column with nothing hidden hands the plot the same array every render
const NO_CATEGORIES = [];

function formatRate(rate) {
    return rate == null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

const signedRows = (change) => `${change > 0 ? "+" : "−"}${Math.abs(change).toLocaleString()} rows`;

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
                    disabled={option.disabled}
                    title={option.title}
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
   those asks the server for it as a band of its own, so those cost a request and the rest do not.
   onKeep takes a list, so the catch-all's own select all is one request; canFold says some category has been
   taken out of it, which onFoldAll puts back. */
function CategoryPicker({ categories, hidden, other, onHidden, onKeep, canFold, onFoldAll }) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState("");
    const boxRef = useRef(null);
    const hostWindow = useHostWindow();

    // A click anywhere else closes the list, as a select would - anywhere in the window the panel is in
    useEffect(() => {
        if (!open) return undefined;
        const onDown = (event) => {
            if (!boxRef.current?.contains(event.target)) setOpen(false);
        };
        hostWindow.document.addEventListener("mousedown", onDown);
        return () => hostWindow.document.removeEventListener("mousedown", onDown);
    }, [open, hostWindow]);

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

    /* The catch-all's own pair. Select all takes out every category the search leaves listed under it, in one
       request; deselect all folds back everything taken out so far, search or not, since once out they are
       listed with the rest and nothing marks where they came from. */
    const listedOther = other.categories.filter((row) => matches(row.category));

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
                        {(other.categories.length > 0 || canFold) && (
                            <>
                                <div className="compare-picker-group">
                                    <span>
                                        In {OTHER_LABEL}
                                        {other.more > 0 && <span> · {other.more} more not listed</span>}
                                    </span>
                                    <span className="compare-picker-group-actions">
                                        <button
                                            type="button"
                                            className="compare-picker-action"
                                            disabled={listedOther.length === 0}
                                            title={`Draw every category listed in ${OTHER_LABEL} as its own band`}
                                            onClick={() => onKeep(listedOther.map((row) => row.category))}
                                        >
                                            Select all
                                        </button>
                                        <button
                                            type="button"
                                            className="compare-picker-action"
                                            disabled={!canFold}
                                            title={`Fold every category taken out of ${OTHER_LABEL} back into it`}
                                            onClick={onFoldAll}
                                        >
                                            Deselect all
                                        </button>
                                    </span>
                                </div>
                                {listedOther.map((row) => (
                                    <label key={row.category} className="compare-picker-item">
                                        <input type="checkbox" checked={false} onChange={() => onKeep([row.category])} />
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

function NodeRow({ role, table, rows, label = ROLE_NAMES[role] }) {
    return (
        <div className="compare-node-row">
            <span className={`compare-role compare-role--${role}`}>{label}</span>
            <span className="compare-node-name" title={table}>{nodeName(table)}</span>
            {rows != null && <span className="compare-node-rows">{rows.toLocaleString()} rows</span>}
        </div>
    );
}

/* Each node's drift from root. Both are measured against the same fixed reference rather than one against
   the other - that is what makes nodes on different branches comparable at all. */
function DriftSummary({ tableA, tableB, driftA, driftB, single }) {
    return (
        <dl className="compare-changes">
            {!single && <div><dt title={tableA}>{nodeName(tableA)} · selection A</dt><dd>{formatDrift(driftA)}</dd></div>}
            <div>
                <dt title={tableB}>{nodeName(tableB)}{single ? "" : " · selection B"}</dt>
                <dd>{formatDrift(driftB)}</dd>
            </div>
        </dl>
    );
}

/**
 * Props:
 *  - initialSpec: the comparison object to open on - see ui/src/utils/comparisonSpec.js. Its a and b are
 *    node tables, a folded run already resolved to its tail. Read once: the panel owns its settings after.
 *    The same table as both a and b is a single-node comparison: one node's plots, measured against root.
 *  - restrict: what a plot-view sub-node fixed, or null for every option - {kinds: plot kind ids offered, or
 *    null for all; columns: {[kind]: {x, y}} for each kind whose columns are fixed}. See PlotViewSupport.jsx
 *  - placement: "docked" or "window", which decides whether it offers to pop out or to dock
 *  - savedTo: the graph nodes this comparison is kept on as plot-view sub-nodes, or null when it is not
 *  - onSpecChange: called with the comparison object once its settings settle, while it is kept on any
 *  - onSave: called with the comparison object to keep it on its nodes; offered while savedTo is null
 *  - onPopOut, onDock, onClose: CompareContext's own, called straight from their buttons' clicks
 */
export default function ComparePanel({
    initialSpec, restrict = null, placement, savedTo = null, onSpecChange, onSave, onPopOut, onDock, onClose,
}) {
    const { nodes, serverNodesById } = usePgraph();
    const hostWindow = useHostWindow();

    const tableA = initialSpec.a;
    const tableB = initialSpec.b;
    const single = tableA === tableB;

    /* Read by the real table rather than by what is drawn, so a node folded out of view - the current
       node inside a collapsed run - still has its metrics and its wrangle. */
    const dataA = serverNodesById?.[tableA]?.data;
    const dataB = serverNodesById?.[tableB]?.data;
    const metricsA = dataA?.metrics;
    const metricsB = dataB?.metrics;
    const distortionA = dataA?.distortion;
    const distortionB = dataB?.distortion;
    // A table the graph shows folded away is the last node of that run
    const foldedCount = (table) => nodes.find((node) => node.type === "collapsedNode" && node.data.tail === table)
        ?.data.run?.length ?? null;

    // Every attribute either side knows of, in the order the metrics list them
    const attributes = useMemo(() => [...new Set([
        ...Object.keys(metricsA?.columns ?? {}),
        ...Object.keys(metricsB?.columns ?? {}),
    ])], [metricsA, metricsB]);

    // Root is the node whose parent is the "root" sentinel, found by table so a folded root still has its metrics
    const metricsRoot = useMemo(() => Object.values(serverNodesById ?? {})
        .find((node) => node.data?.parent === "root")?.data?.metrics, [serverNodesById]);

    /* The same attributes ranked by how far their error rate moved between the two states errorDelta names,
       or by how far either node has drifted from root. Read from what each node already carries, so it costs
       no request - and ranked by error it gives the plot a sensible first attribute: the one the wrangles
       between these two touched most. Error and drift stay two numbers: a column no operation touched can
       show no error change and still have drifted, which is exactly what this list is for. */
    const [rankBy, setRankBy] = useState(initialSpec.rankBy);
    const [errorDeltaChoice, setErrorDeltaId] = useState(initialSpec.errorDelta);
    const errorDeltas = single ? SINGLE_ERROR_DELTAS : ERROR_DELTAS;
    const errorDelta = errorDeltas.find((option) => option.id === errorDeltaChoice) ?? errorDeltas[0];
    const errorDeltaId = errorDelta.id;
    const ranked = useMemo(() => attributes
        .map((name) => {
            const metricsOf = { root: metricsRoot, a: metricsA, b: metricsB };
            const { from, to } = (single ? SINGLE_ERROR_DELTAS : ERROR_DELTAS).find((option) => option.id === errorDeltaId);
            const before = metricsOf[from]?.columns?.[name]?.total ?? null;
            const after = metricsOf[to]?.columns?.[name]?.total ?? null;
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
    [attributes, metricsRoot, metricsA, metricsB, distortionA, distortionB, rankBy, errorDeltaId, single]);

    // The plot kinds on offer - every one, unless a sub-node chose which - and the one drawn among them
    const kinds = PLOT_KINDS.filter((option) => !restrict?.kinds || restrict.kinds.includes(option.id));
    const [kindChoice, setKind] = useState(initialSpec.kind);
    const kind = kinds.some((option) => option.id === kindChoice) ? kindChoice : kinds[0].id;
    /* What the Drift views measure from: root, or the two selections' common ancestor - which leaves out the
       history they share, so only what happened after their branches parted is drawn. When they only meet at
       root the two are the same, and the choice is kept for a pair where they are not. */
    const [reference, setReference] = useState(initialSpec.reference);
    const ancestor = useMemo(() => commonAncestor(serverNodesById, tableA, tableB), [serverNodesById, tableA, tableB]);
    const ancestorIsRoot = !ancestor || serverNodesById?.[ancestor]?.data?.parent === "root";
    const base = kind === "drift" && reference === "ancestor" && !ancestorIsRoot ? ancestor : null;
    const references = [
        { id: "root", label: "Root" },
        {
            id: "ancestor",
            label: ancestorIsRoot ? "Common ancestor" : `Common ancestor · ${nodeName(ancestor)}`,
            disabled: ancestorIsRoot,
            title: ancestorIsRoot
                ? "These two selections only meet at root"
                : `Measure from ${ancestor}, where these two selections' branches part`,
        },
    ];
    /* A new comparison opens on what moved most. When nothing moved the ranking is empty, so it falls back to
       the attributes themselves rather than leaving the panel with nothing to plot. */
    const [xChoice, setX] = useState(() => initialSpec.x || (ranked[0]?.name ?? attributes[0] ?? ""));
    const [yChoice, setY] = useState(() => initialSpec.y
        || (ranked[1]?.name ?? ranked[0]?.name ?? attributes[1] ?? attributes[0] ?? ""));
    // A sub-node can fix the column - or a heatmap's two - for each kind it offers
    const locked = restrict?.columns?.[kind] ?? null;
    const x = locked?.x || xChoice;
    const y = locked?.y || yChoice;
    const [view, setView] = useState(initialSpec.view);
    const [measure, setMeasure] = useState(initialSpec.measure);

    /* Which of a categorical column's categories the Sankey draws. hidden is the reader's own doing and
       costs nothing - the rows are already here, so the bands simply go. kept names categories the server
       would otherwise fold into its catch-all, so changing it asks for the flows again. Both belong to one
       column of one pair: the choice is stamped with that, and another column reads it as never made. */
    const columnKey = [tableA, tableB, x].join("|");
    const [choice, setChoice] = useState(() => ({
        key: initialSpec.x ? [tableA, tableB, initialSpec.x].join("|") : null,
        hidden: initialSpec.hidden.length ? initialSpec.hidden : NO_CATEGORIES,
        kept: initialSpec.kept,
    }));
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
    const { views, activeView } = viewsFor({ kind, view, columnKind, single });
    const usesMeasure = kind === "heatmap" || activeView === "difference";
    const yColumn = spec.axes === 2 ? y : null;

    // While the next result loads, the last one of the same kind stays up, dimmed
    const { loading, current, plotData } = useComparisonData({
        a: tableA, b: tableB, kind, x, y: yColumn, keep: kept, base,
    });

    // The Sankey's categories as the current result has them, and what its catch-all holds
    const plotCategories = useMemo(
        () => (plotData?.kind === "drift" ? flowCategories(plotData) : []), [plotData]);
    const plotOther = useMemo(
        () => (plotData?.kind === "drift" ? otherCategories(plotData) : { categories: [], more: 0 }), [plotData]);

    const hideCategory = useCallback((category) => setHidden((was) => (
        was.includes(category) ? was : [...was, category])), [setHidden]);

    /* Taking categories back out of the catch-all: the server has to redraw the flows for them, so the ask is
       the categories it already draws plus these. They come back shown, whatever they were before. */
    const keepCategories = (categories) => setChoice({
        key: columnKey,
        hidden: hidden.filter((label) => !categories.includes(label)),
        kept: [...(kept ?? plotCategories.filter((label) => label !== OTHER_LABEL)), ...categories],
    });

    /* Putting them all back. Only taking a category out ever sets kept, so clearing it returns the server's
       own choice of categories, with everything taken out folded back in. */
    const foldAllCategories = () => setChoice({ key: columnKey, hidden, kept: null });

    /* How far a drift plot is zoomed, stamped with what it was zoomed for, as the plot keys it. Held here
       rather than in the plot so the comparison object carries it. */
    const [zoom, setZoom] = useState(() => ({
        key: initialSpec.zoom ? driftZoomKey({ x, a: tableA, b: tableB, base }) : null,
        range: initialSpec.zoom,
    }));
    // Read from the settings rather than the result, so a zoom counts as soon as it is chosen or restored
    const zoomKey = kind === "drift" ? driftZoomKey({ x, a: tableA, b: tableB, base }) : null;

    /* The comparison object for what is on screen: what saving keeps, and what reopening it restores. */
    const currentSpec = {
        version: SPEC_VERSION,
        anchor: initialSpec.anchor ?? tableB,
        a: tableA,
        b: tableB,
        kind,
        x,
        y: yColumn,
        view: activeView,
        measure,
        reference,
        hidden,
        kept,
        rankBy,
        errorDelta: errorDeltaId,
        zoom: zoomKey && zoom.key === zoomKey ? zoom.range : null,
    };
    const settings = settingsOf(currentSpec);

    /* While the comparison is kept on graph nodes, they follow what it shows: its settings are reported once
       they settle. Only a change is reported - not the settings it opened on. */
    const reported = useRef(settings);
    useEffect(() => {
        if (!onSpecChange || settings === reported.current) return undefined;
        const timer = hostWindow.setTimeout(() => {
            reported.current = settings;
            onSpecChange(specFromSettings(settings));
        }, REPORT_DELAY_MS);
        return () => hostWindow.clearTimeout(timer);
    }, [settings, onSpecChange, hostWindow]);

    const rowsA = metricsA?.row_count;
    const rowsB = metricsB?.row_count;

    return (
        <div className="compare-panel" role="region" aria-labelledby="compare-title">
            <header className="compare-header">
                <div className="compare-heading">
                    <h2 id="compare-title" className="compare-title">{single ? "Node plots" : "Compare nodes"}</h2>
                    <div className="compare-subtitle">
                        {!single && (
                            <>
                                <NodeSummary
                                    role="a"
                                    table={tableA}
                                    data={dataA}
                                    parentData={serverNodesById?.[dataA?.parent]?.data}
                                    foldedCount={foldedCount(tableA)}
                                />
                                <span className="compare-subtitle-arrow" aria-hidden="true">→</span>
                            </>
                        )}
                        <NodeSummary
                            role="b"
                            table={tableB}
                            data={dataB}
                            parentData={serverNodesById?.[dataB?.parent]?.data}
                            foldedCount={foldedCount(tableB)}
                        />
                    </div>
                </div>
                <div className="compare-actions">
                    {/* Once kept on its nodes it follows along by itself, so there is nothing more to save */}
                    {savedTo ? (
                        <span className="compare-saved" title="Changes here carry over to the plot-view sub-nodes it is kept on">
                            Kept on {savedTo.map(nodeName).join(", ")}
                        </span>
                    ) : onSave && (
                        <button
                            type="button"
                            className="compare-action"
                            onClick={() => onSave(currentSpec)}
                            disabled={!x}
                            title="Keep this comparison beside both nodes in the graph, as plot-view sub-nodes"
                        >
                            Save
                        </button>
                    )}
                    {placement === "window" ? (
                        <button type="button" className="compare-action" onClick={onDock} title="Put the comparison back in the Plots view">
                            Dock
                        </button>
                    ) : (
                        <button type="button" className="compare-action" onClick={onPopOut} title="Open the comparison in a window of its own">
                            Pop out
                        </button>
                    )}
                    <button type="button" className="compare-close" onClick={onClose} aria-label="Close comparison">×</button>
                </div>
            </header>

            <div className="compare-body">
                <aside className="compare-options" aria-label="Plot options">
                    <section className="compare-section">
                        <h3 className="compare-section-title">{single ? "Node" : "Nodes"}</h3>
                        {!single && <NodeRow role="a" table={tableA} rows={rowsA} />}
                        <NodeRow role="b" table={tableB} rows={rowsB} label={single ? "This node" : undefined} />
                    </section>

                    {/* A sub-node that settled on one kind has no other to switch to */}
                    {kinds.length > 1 && (
                        <section className="compare-section">
                            <h3 className="compare-section-title">Plot</h3>
                            <Segmented label="Plot type" options={kinds} value={kind} onChange={setKind} />
                        </section>
                    )}

                    {/* Hidden once a sub-node fixed the column, as the most-changed list below is */}
                    {!locked && <section className="compare-section">
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
                    </section>}

                    {/* One node is only ever measured from root */}
                    {kind === "drift" && !single && (
                        <section className="compare-section">
                            <h3 className="compare-section-title">Measured against</h3>
                            <Segmented
                                label="Measured against"
                                options={references}
                                value={base ? "ancestor" : "root"}
                                onChange={setReference}
                            />
                        </section>
                    )}

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
                                onKeep={keepCategories}
                                canFold={kept != null}
                                onFoldAll={foldAllCategories}
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
                            single={single}
                        />
                    </section>

                    {/* For picking a column, so it goes once a sub-node has fixed it */}
                    {ranked.length > 0 && !locked && (
                        <section className="compare-section">
                            <h3 className="compare-section-title">Most changed attributes</h3>
                            <Segmented label="Rank attributes by" options={RANKINGS} value={rankBy} onChange={setRankBy} />
                            <label className="compare-field">
                                <span className="compare-field-label">Error Δ between</span>
                                <select
                                    className="compare-select"
                                    value={errorDeltaId}
                                    onChange={(event) => setErrorDeltaId(event.target.value)}
                                >
                                    {errorDeltas.map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
                                </select>
                            </label>
                            <div className="compare-ranked-head" aria-hidden="true">
                                <span>attribute</span>
                                <span>error Δ</span>
                                <span>{single ? "drift" : "drift · A / B"}</span>
                            </div>
                            <ol className="compare-ranked">
                                {ranked.slice(0, RANKED_LIMIT).map((attribute) => (
                                    <li key={attribute.name}>
                                        <button
                                            type="button"
                                            className={`compare-ranked-item ${attribute.name === x ? "compare-ranked-item--active" : ""}`}
                                            onClick={() => setX(attribute.name)}
                                            title={`${attribute.name}: error rate ${formatRate(attribute.before)} in `
                                                + `${STATE_NAMES[errorDelta.from]} → ${formatRate(attribute.after)} in `
                                                + `${STATE_NAMES[errorDelta.to]}; `
                                                + (single
                                                    ? `drift from root ${formatDrift(attribute.driftB)}. Click to plot it.`
                                                    : `drift from root ${formatDrift(attribute.driftA)} in selection A, `
                                                        + `${formatDrift(attribute.driftB)} in selection B. Click to plot it.`)}
                                        >
                                            <span className="compare-ranked-name">{attribute.name}</span>
                                            <RateDelta delta={attribute.delta} />
                                            <span className="compare-ranked-drift">
                                                {single
                                                    ? formatDrift(attribute.driftB)
                                                    : `${formatDrift(attribute.driftA)} / ${formatDrift(attribute.driftB)}`}
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
                        zoom={zoom}
                        onZoom={setZoom}
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
        </div>
    );
}
