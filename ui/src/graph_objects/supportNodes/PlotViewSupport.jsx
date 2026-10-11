import {useState} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {useCompare} from "../../store/CompareContext.jsx";
import {describeWrangle, nodeName, referenceBase, viewsFor} from "../../utils/comparison.js";
import {driftZoomKey, settingsOf} from "../../utils/comparisonSpec.js";
import {useComparisonData} from "../../visualizations/useComparisonData.js";
import ComparisonPlot from "../../visualizations/ComparisonPlot.jsx";
import {PLOT_VIEW_DEFAULTS, describePlotView, isSinglePlot, specOfPlotView} from "./plotView.js";
import "../../styles/ComparePanel.css";
import "../../styles/PlotViewSupport.css";

/**
 * The plot-view kind of supporting sub-node - see plotView.js for what its settings mean.
 *
 * PlotViewConfigForm asks its questions one at a time: each answer brings up the next it leads to, and
 * changing an earlier one keeps the later answers for when they apply again. PlotViewBody draws the
 * comparison through the compare panel's own plot and data: in full when the settings fix a single plot,
 * as a preview otherwise, and either way it opens in the compare panel.
 */

function Choice({question, options, value, onChange}) {
    return (
        <div className="plot-view-step">
            <span className="plot-view-question">{question}</span>
            <div className="plot-view-choices" role="radiogroup" aria-label={question}>
                {options.map((option) => (
                    <button
                        key={option.id}
                        type="button"
                        role="radio"
                        aria-checked={value === option.id}
                        className={`plot-view-choice ${value === option.id ? "plot-view-choice--active" : ""}`}
                        title={option.title}
                        onClick={() => onChange(option.id)}
                    >
                        {option.label}
                    </button>
                ))}
            </div>
        </div>
    );
}

function ColumnSelect({label, value, columns, onChange}) {
    return (
        <label className="support-form-field plot-view-column">
            {label}
            <select value={value} onChange={(event) => onChange(event.target.value)}>
                <option value="" disabled>Choose a column</option>
                {columns.map((column) => <option key={column} value={column}>{column}</option>)}
            </select>
        </label>
    );
}

const NODE_CHOICES = [
    {id: "pair", label: "Compare two nodes"},
    {id: "single", label: "Just this node"},
];
const SCOPE_CHOICES = [
    {id: "full", label: "Full comparison", title: "Every option the compare window has"},
    {id: "specific", label: "Specific view", title: "Choose what it shows"},
];
const MEASURE_CHOICES = [
    {id: "error", label: "Error"},
    {id: "drift", label: "Drift"},
    {id: "both", label: "Both"},
];
const ERROR_PLOT_CHOICES = [
    {id: "histogram", label: "Histogram"},
    {id: "heatmap", label: "Heatmap"},
];
const COLUMN_CHOICES = [
    {id: "all", label: "All columns", title: "Keep the column picker, as the compare window has it"},
    {id: "one", label: "One column"},
];

export function PlotViewConfigForm({value, onChange, hostId}) {
    const {serverNodesById} = usePgraph();
    const config = {...PLOT_VIEW_DEFAULTS, ...value};
    const set = (patch) => onChange({...config, ...patch});

    // Every other node, in the graph's own order - root first - named with the wrangle that made it
    const others = Object.values(serverNodesById ?? {}).filter((node) => node.id !== hostId);
    // The columns either node has, so a column only one of them kept can still be chosen
    const columnsOf = (table) => Object.keys(serverNodesById?.[table]?.data?.metrics?.columns ?? {});
    const columns = [...new Set([
        ...columnsOf(hostId),
        ...(config.nodes === "pair" && config.other ? columnsOf(config.other) : []),
    ])];

    const pair = config.nodes === "pair";
    const specific = config.scope === "specific";
    const error = specific && (config.measure === "error" || config.measure === "both");
    const drift = specific && (config.measure === "drift" || config.measure === "both");

    return (
        <div className="plot-view-form">
            <Choice
                question="1 · Compare two nodes, or focus on this one?"
                options={NODE_CHOICES}
                value={config.nodes}
                onChange={(nodes) => set({nodes})}
            />

            {pair && (
                <label className="support-form-field plot-view-step">
                    <span className="plot-view-question">2 · Which other node? It is selection A, this one selection B</span>
                    <select value={config.other ?? ""} onChange={(event) => set({other: event.target.value || null})}>
                        <option value="" disabled>Choose a node</option>
                        {others.map((node) => (
                            <option key={node.id} value={node.id}>
                                {nodeName(node.id)} · {describeWrangle(node.data?.wrangle) ?? node.id}
                            </option>
                        ))}
                    </select>
                </label>
            )}

            {config.nodes && (!pair || config.other) && (
                <Choice
                    question={`${pair ? 3 : 2} · Full comparison, or something specific?`}
                    options={SCOPE_CHOICES}
                    value={config.scope}
                    onChange={(scope) => set({scope})}
                />
            )}

            {specific && (
                <Choice
                    question={`${pair ? 4 : 3} · Error, drift, or both?`}
                    options={MEASURE_CHOICES}
                    value={config.measure}
                    onChange={(measure) => set({measure})}
                />
            )}

            {error && (
                <div className="plot-view-group">
                    <span className="plot-view-group-title">Error</span>
                    <Choice
                        question="Histogram or heatmap?"
                        options={ERROR_PLOT_CHOICES}
                        value={config.errorPlot}
                        onChange={(errorPlot) => set({errorPlot})}
                    />
                    {config.errorPlot && (
                        <Choice
                            question="All columns, or one?"
                            options={COLUMN_CHOICES}
                            value={config.errorColumns}
                            onChange={(errorColumns) => set({errorColumns})}
                        />
                    )}
                    {config.errorPlot && config.errorColumns === "one" && (
                        <div className="plot-view-columns">
                            <ColumnSelect
                                label={config.errorPlot === "heatmap" ? "X axis" : "Column"}
                                value={config.errorX}
                                columns={columns}
                                onChange={(errorX) => set({errorX})}
                            />
                            {config.errorPlot === "heatmap" && (
                                <ColumnSelect
                                    label="Y axis"
                                    value={config.errorY}
                                    columns={columns}
                                    onChange={(errorY) => set({errorY})}
                                />
                            )}
                        </div>
                    )}
                </div>
            )}

            {drift && (
                <div className="plot-view-group">
                    <span className="plot-view-group-title">Drift</span>
                    <Choice
                        question="All columns, or one?"
                        options={COLUMN_CHOICES}
                        value={config.driftColumns}
                        onChange={(driftColumns) => set({driftColumns})}
                    />
                    {config.driftColumns === "one" && (
                        <div className="plot-view-columns">
                            <ColumnSelect
                                label="Column"
                                value={config.driftX}
                                columns={columns}
                                onChange={(driftX) => set({driftX})}
                            />
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

/* The comparison's plot, through the compare panel's own data and drawing. Zoom and hidden categories are
   the reader's to change here, and start from the comparison's; the caller keys this on the comparison, so a
   change made in the compare panel starts it afresh. */
function PlotViewPlot({spec, compact}) {
    const {serverNodesById} = usePgraph();
    const {kind, a, b} = spec;
    const x = spec.x;
    const y = kind === "heatmap" ? spec.y : null;
    const base = referenceBase(spec, serverNodesById);
    const columnKind = (serverNodesById?.[b]?.data?.distortion?.columns?.[x]
        ?? serverNodesById?.[a]?.data?.distortion?.columns?.[x])?.kind;
    const {activeView} = viewsFor({kind, view: spec.view, columnKind, single: a === b});
    const {loading, current, plotData} = useComparisonData({a, b, kind, x, y, keep: spec.kept, base});

    const [zoom, setZoom] = useState(() => ({
        key: spec.zoom && kind === "drift" ? driftZoomKey({x, a, b, base}) : null,
        range: spec.zoom,
    }));
    const [hidden, setHidden] = useState(spec.hidden);

    return (
        // nowheel and nopan keep the graph from zooming or panning under a plot being read
        <div className={`plot-view-plot compare-plot nowheel nopan ${loading ? "compare-plot--loading" : ""}`}>
            <ComparisonPlot
                data={plotData}
                view={activeView}
                measure={spec.measure}
                labelA={nodeName(a)}
                labelB={nodeName(b)}
                hidden={hidden}
                onHide={(category) => setHidden((was) => (was.includes(category) ? was : [...was, category]))}
                zoom={zoom}
                onZoom={setZoom}
                compact={compact}
            />
            {!loading && current?.error && (
                <div className="compare-plot-status">
                    <span className="compare-plot-pill compare-plot-pill--error">{current.error}</span>
                </div>
            )}
            {!x && <div className="compare-plot-status"><span className="compare-plot-pill">Nothing to plot</span></div>}
        </div>
    );
}

export function PlotViewBody({record, host}) {
    const {openPlotView} = useCompare();
    const config = {...PLOT_VIEW_DEFAULTS, ...record.config};
    const spec = specOfPlotView({...record, config}, Object.keys(host?.data?.metrics?.columns ?? {}));
    const single = isSinglePlot(config);
    const nodes = spec.a === spec.b ? nodeName(spec.b) : `${nodeName(spec.a)} → ${nodeName(spec.b)}`;

    return (
        <div className="plot-view-body">
            <div className="plot-view-summary">
                <span className="plot-view-summary-text" title={`${nodes} · ${describePlotView(config)}`}>
                    {nodes} · {describePlotView(config)}
                </span>
                <button
                    type="button"
                    className="plot-view-open"
                    onClick={() => openPlotView(record)}
                    title="Open in the compare window, with the options this view leaves open"
                >
                    Open
                </button>
            </div>
            <PlotViewPlot key={settingsOf(spec)} spec={spec} compact={!single} />
        </div>
    );
}
