// CompareModal.jsx
// Opened from the header's Compare button while two nodes are paired in the graph: a shift-clicked
// baseline and the current node. Plot options down the left, the plot itself on the right.

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { usePgraph } from "../store/PGraphContext.jsx";
import { getDriftDetail, getNodeComparison } from "../utils/serverCalls.jsx";
import { MEASURES, describeWrangle, nodeName } from "../utils/comparison.js";
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

/* A folded run stands in for its last node - the state the run arrives at, and whose metrics it
   already reports - so that is the table it is compared as. */
function tableOf(node, id) {
    return node?.type === "collapsedNode" ? node.data.tail : id;
}

function formatRate(rate) {
    return rate == null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

const signedRows = (change) => `${change > 0 ? "+" : "−"}${Math.abs(change).toLocaleString()} rows`;

/* The Drift kind's data: each node's breakdown against root, the two fetched side by side */
async function getDriftComparison({ base, other, x }, signal) {
    const [baseDetail, otherDetail] = await Promise.all([
        getDriftDetail({ node: base, column: x }, signal),
        getDriftDetail({ node: other, column: x }, signal),
    ]);
    const failed = [baseDetail, otherDetail].find((response) => !response?.success);
    if (failed) return { success: false, error: failed?.error };
    return { success: true, kind: "drift", x, base: baseDetail, other: otherDetail };
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

function NodeRow({ role, table, rows }) {
    return (
        <div className="compare-node-row">
            <span className={`compare-role compare-role--${role}`}>{role === "base" ? "Baseline" : "Comparator"}</span>
            <span className="compare-node-name" title={table}>{nodeName(table)}</span>
            {rows != null && <span className="compare-node-rows">{rows.toLocaleString()} rows</span>}
        </div>
    );
}

/* Each node's drift from root. Both are measured against the same fixed reference rather than one against
   the other - that is what makes nodes on different branches comparable at all. */
function DriftSummary({ baseTable, otherTable, baseDrift, otherDrift }) {
    return (
        <dl className="compare-changes">
            <div><dt title={baseTable}>{nodeName(baseTable)} · baseline</dt><dd>{formatDrift(baseDrift)}</dd></div>
            <div><dt title={otherTable}>{nodeName(otherTable)} · comparator</dt><dd>{formatDrift(otherDrift)}</dd></div>
        </dl>
    );
}

/**
 * Props:
 *  - pair: {baseline, comparator} node ids, as PGraphContext's comparisonPair names them
 *  - onClose: called on the close button, a backdrop click or Escape
 */
export default function CompareModal({ pair, onClose }) {
    const { nodes, serverNodesById } = usePgraph();
    const dialogRef = useRef(null);

    const nodesById = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes]);

    const baseId = pair.baseline;
    const otherId = pair.comparator;
    const baseTable = tableOf(nodesById[baseId], baseId);
    const otherTable = tableOf(nodesById[otherId], otherId);

    /* Read by the real table rather than by what is drawn, so a node folded out of view - the current
       node inside a collapsed run - still has its metrics and its wrangle. */
    const dataFor = (table, id) => (serverNodesById?.[table] ?? nodesById[id])?.data;
    const baseData = dataFor(baseTable, baseId);
    const otherData = dataFor(otherTable, otherId);
    const baseMetrics = baseData?.metrics;
    const otherMetrics = otherData?.metrics;
    const baseDistortion = baseData?.distortion;
    const otherDistortion = otherData?.distortion;
    // Fetched as the modal opens, for the flags beside each drift - only a node that lost rows can have any
    const baseNull = useDriftNull(baseTable, baseDistortion?.facts?.rows_removed);
    const otherNull = useDriftNull(otherTable, otherDistortion?.facts?.rows_removed);
    const foldedCount =(id) => (nodesById[id]?.type === "collapsedNode" ? nodesById[id].data.run?.length : null);

    // Every attribute either side knows of, in the order the metrics list them
    const attributes = useMemo(() => [...new Set([
        ...Object.keys(baseMetrics?.columns ?? {}),
        ...Object.keys(otherMetrics?.columns ?? {}),
    ])], [baseMetrics, otherMetrics]);

    /* The same attributes ranked by how far their error rate moved, or by how far either node has drifted
       from root. Read from what each node already carries, so it costs no request - and ranked by error
       it gives the plot a sensible first attribute: the one the wrangles between these two touched most.
       Error and drift stay two numbers: a column no operation touched can show no error change and still
       have drifted, which is exactly what this list is for. */
    const [rankBy, setRankBy] = useState("error");
    const ranked = useMemo(() => attributes
        .map((name) => {
            const before = baseMetrics?.columns?.[name]?.total ?? null;
            const after = otherMetrics?.columns?.[name]?.total ?? null;
            const driftBase = baseDistortion?.columns?.[name]?.value ?? null;
            const driftOther = otherDistortion?.columns?.[name]?.value ?? null;
            return { name, before, after, delta: (after ?? 0) - (before ?? 0), driftBase, driftOther };
        })
        /* An attribute that neither node moved has nothing to say, so it is left out entirely. The test is
           for exactly zero rather than for what the row would print: a column no operation touched usually
           drifts by a fraction that shows as 0.000, and those are the rows the metric exists to surface. */
        .filter((attribute) => attribute.delta !== 0 || attribute.driftBase || attribute.driftOther)
        .sort((a, b) => (rankBy === "drift"
            ? Math.max(b.driftBase ?? 0, b.driftOther ?? 0) - Math.max(a.driftBase ?? 0, a.driftOther ?? 0)
            : Math.abs(b.delta) - Math.abs(a.delta))),
    [attributes, baseMetrics, otherMetrics, baseDistortion, otherDistortion, rankBy]);

    const [kind, setKind] = useState("histogram");
    /* The plot opens on what moved most. When nothing moved the ranking is empty, so it falls back to the
       attributes themselves rather than leaving the modal with nothing to plot. */
    const [x, setX] = useState(() => ranked[0]?.name ?? attributes[0] ?? "");
    const [y, setY] = useState(() => ranked[1]?.name ?? ranked[0]?.name ?? attributes[1] ?? attributes[0] ?? "");
    const [view, setView] = useState("side");
    const [measure, setMeasure] = useState("items");
    const [result, setResult] = useState({ key: null, data: null, error: null });

    const spec = PLOT_KINDS.find((plotKind) => plotKind.id === kind);
    // Drift's views follow the column - numeric or categorical, as root decided it
    const columnKind = (baseDistortion?.columns?.[x] ?? otherDistortion?.columns?.[x])?.kind;
    const views = kind === "drift" ? DRIFT_VIEWS[columnKind] ?? DRIFT_VIEWS.numeric : spec.views;
    // A view this kind does not offer falls back to its first, keeping the choice for later
    const activeView = views.includes(view) ? view : (kind === "drift" ? views[0] : "side");
    const usesMeasure = kind === "heatmap" || activeView === "difference";
    const yColumn = spec.axes === 2 ? y : null;

    /* Names the request the current options call for. A result is only current when it carries this
       key, which is how loading is known without any state of its own. */
    const requestKey = [baseTable, otherTable, kind, x, yColumn].join("|");
    const loading = Boolean(x) && result.key !== requestKey;
    const current = result.key === requestKey ? result : null;
    // While the next result loads, the last one of the same kind stays up, dimmed
    const plotData = result.data?.kind === kind ? result.data : null;

    useEffect(() => {
        if (!x) return;

        const controller = new AbortController();
        const timer = setTimeout(async () => {
            try {
                const response = kind === "drift"
                    ? await getDriftComparison({ base: baseTable, other: otherTable, x }, controller.signal)
                    : await getNodeComparison(
                        { base: baseTable, other: otherTable, kind, x, y: yColumn },
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
    }, [requestKey, baseTable, otherTable, kind, x, yColumn]);

    useEffect(() => {
        dialogRef.current?.focus();
        const onKeyDown = (event) => {
            if (event.key === "Escape") onClose();
        };
        document.addEventListener("keydown", onKeyDown);
        return () => document.removeEventListener("keydown", onKeyDown);
    }, [onClose]);

    const baseRows = baseMetrics?.row_count;
    const otherRows = otherMetrics?.row_count;

    // Portaled to <body> so it sits above the fixed header, whose stacking context would trap it
    return createPortal(
        <div
            className="compare-overlay"
            onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
        >
            <div
                ref={dialogRef}
                className="compare-window"
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
                                role="base"
                                table={baseTable}
                                data={baseData}
                                parentData={serverNodesById?.[baseData?.parent]?.data}
                                foldedCount={foldedCount(baseId)}
                            />
                            <span className="compare-subtitle-arrow" aria-hidden="true">→</span>
                            <NodeSummary
                                role="other"
                                table={otherTable}
                                data={otherData}
                                parentData={serverNodesById?.[otherData?.parent]?.data}
                                foldedCount={foldedCount(otherId)}
                            />
                        </div>
                    </div>
                    <button type="button" className="compare-close" onClick={onClose} aria-label="Close comparison">×</button>
                </header>

                <div className="compare-body">
                    <aside className="compare-options" aria-label="Plot options">
                        <section className="compare-section">
                            <h3 className="compare-section-title">Nodes</h3>
                            <NodeRow role="base" table={baseTable} rows={baseRows} />
                            <NodeRow role="other" table={otherTable} rows={otherRows} />
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
                                baseTable={baseTable}
                                otherTable={otherTable}
                                baseDrift={baseDistortion?.overall}
                                otherDrift={otherDistortion?.overall}
                            />
                        </section>

                        {ranked.length > 0 && (
                            <section className="compare-section">
                                <h3 className="compare-section-title">Most changed attributes</h3>
                                <Segmented label="Rank attributes by" options={RANKINGS} value={rankBy} onChange={setRankBy} />
                                <div className="compare-ranked-head" aria-hidden="true">
                                    <span>attribute</span>
                                    <span>error Δ</span>
                                    <span>drift · base / comp</span>
                                </div>
                                <ol className="compare-ranked">
                                    {ranked.slice(0, RANKED_LIMIT).map((attribute) => (
                                        <li key={attribute.name}>
                                            <button
                                                type="button"
                                                className={`compare-ranked-item ${attribute.name === x ? "compare-ranked-item--active" : ""}`}
                                                onClick={() => setX(attribute.name)}
                                                title={`${attribute.name}: error rate ${formatRate(attribute.before)} → ${formatRate(attribute.after)}; `
                                                    + `drift from root ${formatDrift(attribute.driftBase)} in the baseline, `
                                                    + `${formatDrift(attribute.driftOther)} in the comparator. Click to plot it.`}
                                            >
                                                <span className="compare-ranked-name">{attribute.name}</span>
                                                <RateDelta delta={attribute.delta} />
                                                <span className="compare-ranked-drift">
                                                    {formatDrift(attribute.driftBase)}
                                                    <DriftFlag result={baseNull[attribute.name]} />
                                                    {" / "}
                                                    {formatDrift(attribute.driftOther)}
                                                    <DriftFlag result={otherNull[attribute.name]} />
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
                            baseLabel={nodeName(baseTable)}
                            otherLabel={nodeName(otherTable)}
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
        </div>,
        document.body,
    );
}
