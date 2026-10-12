import {useState} from "react";
import "../../styles/SupportPlot.css";

/**
 * The frame every sub-node plot card shares - error plots and drift plots, in the modal's gallery and in the
 * sub-node: a title, the plot, and the card's buttons. Change Columns swaps the title for the column pickers;
 * each pick is reported at once and the plot follows, so Done only puts the title back.
 *
 * Props:
 *  - title: what the card shows
 *  - pickers: the column pickers shown while changing columns - ColumnPicker elements
 *  - actions: anything more for the footer, beside Change Columns
 *  - children: the plot
 */
export function SupportPlotCard({title, pickers, actions = null, children}) {
    const [editing, setEditing] = useState(false);

    return (
        <div className="support-plot-card">
            <div className="support-plot-head">
                {editing ? (
                    <div className="support-plot-pickers">{pickers}</div>
                ) : (
                    <span className="support-plot-title" title={title}>{title}</span>
                )}
            </div>

            <div className="support-plot-chart">{children}</div>

            <div className="support-plot-actions">
                {actions}
                <button type="button" className="support-plot-action" onClick={() => setEditing((was) => !was)}>
                    {editing ? "Done" : "Change Columns"}
                </button>
            </div>
        </div>
    );
}

export function ColumnPicker({label, value, choices, onChange}) {
    return (
        <label className="support-plot-picker">
            <span>{label}</span>
            <select value={value} onChange={(event) => onChange(event.target.value)}>
                {choices.map((column) => <option key={column} value={column}>{column}</option>)}
            </select>
        </label>
    );
}
