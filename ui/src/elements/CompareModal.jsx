// CompareModal.jsx
// Opened from the header's Compare button while two nodes are paired in the graph: a shift-clicked
// baseline and the current node. Plot options down the left, the plot itself on the right.

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { usePgraph } from "../store/PGraphContext.jsx";
import { getNodeComparison } from "../utils/serverCalls.jsx";
import { MEASURES } from "../utils/comparison.js";
import { truncateText } from "../utils/textUtils.js";
import ComparisonPlot from "../visualizations/ComparisonPlot.jsx";
import "../styles/CompareModal.css";

/* Each plot kind offers the views that make sense for it: a scatter has no bins to subtract, and a
   heatmap overlay would be two grids painted over one another. */
const PLOT_KINDS = [
    { id: "histogram", label: "Histogram", axes: 1, views: ["side", "overlay", "difference"] },
    { id: "heatmap", label: "Heatmap", axes: 2, views: ["side", "difference"] },
    { id: "scatter", label: "Scatter", axes: 2, views: ["side", "overlay"] },
];

const VIEW_LABELS = { side: "Side by side", overlay: "Overlay", difference: "Difference" };

// How many attributes the most-changed list offers
const RANKED_LIMIT = 8;

// The bins slider fires on every step it is dragged through, so a request waits for it to settle
const FETCH_DELAY_MS = 150;

/* Node tables are named "<node id>_<base name>", so the id - n0a, n2b - names a node compactly. The
   full table name stays available in a title attribute. */
function nodeName(id) {
    const match = id?.match(/^(n\d[a-z])_/);
    return match ? match[1] : truncateText(id, 16);
}

/* A folded run stands in for its last node - the state the run arrives at, and whose metrics it
   already reports - so that is the table it is compared as. */
function tableOf(node, id) {
    return node?.type === "collapsedNode" ? node.data.tail : id;
}

function formatRate(rate) {
    return rate == null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

const signedRows = (change) => `${change > 0 ? "+" : "−"}${Math.abs(change).toLocaleString()} rows`;

/* A sentence for the wrangle that produced a node: "Imputed age", "Deleted rows selected on age ×
   income". An op this does not know still reads, as the op and its columns. */
function describeWrangle(wrangle) {
    if (!wrangle) return null;
    if (wrangle.op === "root") return "Original upload";

    const columns = wrangle.columns?.join(" × ");
    if (wrangle.op === "impute") return columns ? `Imputed ${columns}` : "Imputed values";
    if (wrangle.op === "delete") return columns ? `Deleted rows selected on ${columns}` : "Deleted rows";
    return columns ? `${wrangle.op} · ${columns}` : wrangle.op;
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

/* What happened between the two states for the columns on screen. Rows removed and added are
   table-wide; values changed and error rates are per plotted column. */
function ChangeSummary({ changes, columns, baseColumns, otherColumns }) {
    if (!changes) return <div className="compare-muted">Comparing…</div>;

    return (
        <dl className="compare-changes">
            <div><dt>Rows removed</dt><dd>{changes.removed.toLocaleString()}</dd></div>
            <div><dt>Rows added</dt><dd>{changes.added.toLocaleString()}</dd></div>
            {columns.map((column) => (
                <div key={`changed-${column}`}>
                    <dt title={column}>Values changed in {column}</dt>
                    <dd>{(changes.changed[column] ?? 0).toLocaleString()}</dd>
                </div>
            ))}
            {columns.map((column) => (
                <div key={`rate-${column}`}>
                    <dt title={column}>Error rate of {column}</dt>
                    <dd>{formatRate(baseColumns?.[column]?.total)} → {formatRate(otherColumns?.[column]?.total)}</dd>
                </div>
            ))}
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

    // Swapping only re-orients this modal; the graph's pair stays as the user set it
    const [swapped, setSwapped] = useState(false);
    const baseId = swapped ? pair.comparator : pair.baseline;
    const otherId = swapped ? pair.baseline : pair.comparator;
    const baseTable = tableOf(nodesById[baseId], baseId);
    const otherTable = tableOf(nodesById[otherId], otherId);

    /* Read by the real table rather than by what is drawn, so a node folded out of view - the current
       node inside a collapsed run - still has its metrics and its wrangle. */
    const dataFor = (table, id) => (serverNodesById?.[table] ?? nodesById[id])?.data;
    const baseData = dataFor(baseTable, baseId);
    const otherData = dataFor(otherTable, otherId);
    const baseMetrics = baseData?.metrics;
    const otherMetrics = otherData?.metrics;
    const foldedCount = (id) => (nodesById[id]?.type === "collapsedNode" ? nodesById[id].data.run?.length : null);

    // Every attribute either side knows of, in the order the metrics list them
    const attributes = useMemo(() => [...new Set([
        ...Object.keys(baseMetrics?.columns ?? {}),
        ...Object.keys(otherMetrics?.columns ?? {}),
    ])], [baseMetrics, otherMetrics]);

    /* The same attributes ranked by how far their error rate moved. Read from the metrics each node
       already carries, so it costs no request - and it gives the plot a sensible first attribute: the
       one the wrangles between these two nodes touched most. */
    const ranked = useMemo(() => attributes
        .map((name) => {
            const before = baseMetrics?.columns?.[name]?.total ?? null;
            const after = otherMetrics?.columns?.[name]?.total ?? null;
            return { name, before, after, delta: (after ?? 0) - (before ?? 0) };
        })
        .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)),
    [attributes, baseMetrics, otherMetrics]);

    const [kind, setKind] = useState("histogram");
    const [x, setX] = useState(() => ranked[0]?.name ?? "");
    const [y, setY] = useState(() => ranked[1]?.name ?? ranked[0]?.name ?? "");
    const [view, setView] = useState("side");
    const [measure, setMeasure] = useState("items");
    const [bins, setBins] = useState(10);
    const [result, setResult] = useState({ key: null, data: null, error: null });

    const spec = PLOT_KINDS.find((plotKind) => plotKind.id === kind);
    // A view this kind does not offer falls back to side by side, keeping the choice for later
    const activeView = spec.views.includes(view) ? view : "side";
    const usesMeasure = kind === "heatmap" || activeView === "difference";
    const usesBins = kind !== "scatter";
    const yColumn = spec.axes === 2 ? y : null;
    const columns = [...new Set([x, yColumn].filter(Boolean))];

    /* Names the request the current options call for. A result is only current when it carries this
       key, which is how loading is known without any state of its own. */
    const requestKey = [baseTable, otherTable, kind, x, yColumn, usesBins ? bins : null].join("|");
    const loading = Boolean(x) && result.key !== requestKey;
    const current = result.key === requestKey ? result : null;
    // While the next result loads, the last one of the same kind stays up, dimmed
    const plotData = result.data?.kind === kind ? result.data : null;

    useEffect(() => {
        if (!x) return;

        const controller = new AbortController();
        const timer = setTimeout(async () => {
            try {
                const response = await getNodeComparison(
                    { base: baseTable, other: otherTable, kind, x, y: yColumn, bins },
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
    }, [requestKey, baseTable, otherTable, kind, x, yColumn, bins]);

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
    const rowChange = (baseRows != null && otherRows != null) ? otherRows - baseRows : null;

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
                            <div className="compare-pair-footer">
                                {rowChange !== null && (
                                    <span className="compare-row-change">
                                        {rowChange === 0 ? "Same row count" : signedRows(rowChange)}
                                    </span>
                                )}
                                <button
                                    type="button"
                                    className="compare-swap"
                                    onClick={() => setSwapped((isSwapped) => !isSwapped)}
                                    title="Swap which node is the baseline"
                                >
                                    ⇄ Swap
                                </button>
                            </div>
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

                        <section className="compare-section">
                            <h3 className="compare-section-title">View</h3>
                            <Segmented
                                label="View"
                                options={spec.views.map((id) => ({ id, label: VIEW_LABELS[id] }))}
                                value={activeView}
                                onChange={setView}
                            />
                        </section>

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

                        {usesBins && (
                            <section className="compare-section">
                                <h3 className="compare-section-title">
                                    Bins <span className="compare-section-value">{bins}</span>
                                </h3>
                                <input
                                    className="compare-range"
                                    type="range"
                                    min={4}
                                    max={30}
                                    value={bins}
                                    onChange={(event) => setBins(Number(event.target.value))}
                                    aria-label="Number of bins"
                                />
                            </section>
                        )}

                        <section className="compare-section">
                            <h3 className="compare-section-title">What changed</h3>
                            <ChangeSummary
                                changes={current?.data?.changes}
                                columns={columns}
                                baseColumns={baseMetrics?.columns}
                                otherColumns={otherMetrics?.columns}
                            />
                        </section>

                        {ranked.length > 0 && (
                            <section className="compare-section">
                                <h3 className="compare-section-title">Most changed attributes</h3>
                                <ol className="compare-ranked">
                                    {ranked.slice(0, RANKED_LIMIT).map((attribute) => (
                                        <li key={attribute.name}>
                                            <button
                                                type="button"
                                                className={`compare-ranked-item ${attribute.name === x ? "compare-ranked-item--active" : ""}`}
                                                onClick={() => setX(attribute.name)}
                                                title={`${attribute.name}: error rate ${formatRate(attribute.before)} → ${formatRate(attribute.after)}. Click to plot it.`}
                                            >
                                                <span className="compare-ranked-name">{attribute.name}</span>
                                                <RateDelta delta={attribute.delta} />
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
