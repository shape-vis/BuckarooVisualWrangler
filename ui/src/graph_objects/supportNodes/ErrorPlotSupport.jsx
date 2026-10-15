import {useContext, useEffect, useRef, useState} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {useTableName} from "../../store/TableNameContext.jsx";
import {useSelection} from "../../store/SelectionContext.jsx";
import {CANDIDATE_LOCKED, useRepair} from "../../store/RepairContext.jsx";
import {errorColors} from "../../store/errorColors.js";
import {ViewContext} from "../../pages/Buckaroo.jsx";
import FocusedPlot from "../../visualizations/FocusedPlot.jsx";
import ErrorPlotCard from "./ErrorPlotCard.jsx";
import {SupportPlotGallery} from "./SupportPlotGallery.jsx";
import {hostColumns} from "./registry.js";

/**
 * The error-plot kind of supporting sub-node: one error plot of its host node's table - a histogram of a
 * column or a heatmap of two - drawn as the repair preview draws them.
 *
 * It is picked from a gallery rather than set up through a form: one card for each attribute selected in the
 * attribute panel, and one for each pair of them - the plots the main Plots view shows, for this node's data.
 * Each card's columns can be changed before it is added, and the sub-node's after.
 *
 * The sub-node's plot is only a picture until Repair in its header: that makes its node the current one and
 * grows the sub-node into the attribute matrix's own plot of the same columns - the one the Plots view zooms
 * to - so brushing it selects rows exactly as the matrix does, and Repair selection stages the repairs under the
 * node. Done puts it back. It stays a picture whenever its node is not the current one, since a selection and a
 * repair are always of the current node - see supportActions.js.
 *
 * Its config is {plot: "histogram" | "heatmap", columns: [x] | [x, y]}.
 */

/** One histogram card per attribute, then one heatmap card for each pair of them. */
function galleryCards(attributes) {
    const cards = [];

    for (const x of attributes) {
        cards.push({id: `histogram:${x}`, plot: "histogram", columns: [x]});
    }

    for (let i = 0; i < attributes.length; i++) {
        for (let j = i + 1; j < attributes.length; j++) {
            const x = attributes[i];
            const y = attributes[j];
            cards.push({id: `heatmap:${x}:${y}`, plot: "heatmap", columns: [x, y]});
        }
    }

    return cards;
}

/**
 * The support-nodes window's picker for this kind: the selected attributes' histograms, then their pairs'
 * heatmaps, for the host's data. Attributes the host does not have are left out.
 */
export function ErrorPlotGallery({hostId, onAdd}) {
    const {selectedAttributes = []} = useContext(ViewContext) ?? {};
    const {serverNodesById} = usePgraph();

    const columnChoices = hostColumns(serverNodesById?.[hostId]);
    const attributes = selectedAttributes.filter((attribute) => columnChoices.includes(attribute));
    const cards = galleryCards(attributes);

    return (
        <SupportPlotGallery
            cards={cards}
            onAdd={(card, columns) => onAdd({plot: card.plot, columns})}
            emptyHint="Select attributes in the attribute panel to see their plots for this node here."
            renderCard={({card, columns, setColumns, enabled, addButton}) => (
                <ErrorPlotCard
                    table={hostId}
                    plot={card.plot}
                    columns={columns}
                    columnChoices={columnChoices}
                    onColumns={setColumns}
                    enabled={enabled}
                    actions={addButton}
                />
            )}
        />
    );
}

/** The selection line under the plot being wrangled on: how many rows are selected, or how to select some. */
function selectionText(rowIds) {
    const count = rowIds?.length ?? 0;
    if (count === 0) return "Brush or click the plot to select rows";
    if (count === 1) return "1 row selected";
    return `${count.toLocaleString()} rows selected`;
}

/** Why Repair selection is off, or what it does. */
function repairTitle({repairLocked, hasSelection, busy}) {
    if (repairLocked) return `${CANDIDATE_LOCKED}.`;
    if (!hasSelection) return "Select rows in the plot first";
    if (busy) return "Working…";
    return "Stage every repair of the selected rows as candidates under this node";
}

/* The error plot while it is wrangled on: the matrix's own plot of its columns, filling the sub-node, with the
   selection and Repair under it. A histogram is the matrix's diagonal cell; a heatmap its cell below the
   diagonal, x across and y down. */
function WrangleErrorPlot({record}) {
    const {endWrangling} = usePgraph();
    const {highlightedRowIds} = useSelection();
    const {busy, hasSelection, repairLocked, triggerRepairSelection} = useRepair();
    const {plot, columns} = record.config;

    // The plot is laid out from the room the sub-node gives it, which a resize changes
    const boxRef = useRef(null);
    const [box, setBox] = useState(null);
    useEffect(() => {
        const observer = new ResizeObserver(([entry]) => {
            const width = Math.round(entry.contentRect.width);
            const height = Math.round(entry.contentRect.height);
            setBox((was) => {
                if (was?.width === width && was?.height === height) return was;
                return {width, height};
            });
        });
        observer.observe(boxRef.current);
        return () => observer.disconnect();
    }, []);

    let cell = {i: 0, j: 0, xCol: columns[0], yCol: columns[0]};
    if (plot === "heatmap") {
        cell = {i: 1, j: 0, xCol: columns[0], yCol: columns[1]};
    }

    const stop = (event) => event.stopPropagation();

    return (
        // nodrag, nopan and nowheel keep the graph from moving under a brush
        <div className="support-wrangle nodrag nopan nowheel" onDoubleClick={stop}>
            <div className="support-wrangle-plot" ref={boxRef}>
                {box && (
                    <svg width={box.width} height={box.height}>
                        <FocusedPlot
                            i={cell.i}
                            j={cell.j}
                            xCol={cell.xCol}
                            yCol={cell.yCol}
                            w={box.width}
                            h={box.height}
                            errorColors={errorColors}
                        />
                    </svg>
                )}
            </div>
            <div className="support-wrangle-footer">
                <span className="support-wrangle-selection">{selectionText(highlightedRowIds)}</span>
                <button
                    type="button"
                    className="support-node-inline-action support-node-inline-action--primary"
                    onClick={(event) => { stop(event); triggerRepairSelection(); }}
                    disabled={busy || !hasSelection || repairLocked}
                    title={repairTitle({repairLocked, hasSelection, busy})}
                >
                    Repair selection
                </button>
                <button
                    type="button"
                    className="support-node-inline-action"
                    onClick={(event) => { stop(event); endWrangling(); }}
                    title="Shrink this back to its picture"
                >
                    Done
                </button>
            </div>
        </div>
    );
}

export function ErrorPlotBody({record, host}) {
    const {updateSupportNode, wranglingSupportId} = usePgraph();
    const {tableName} = useTableName();
    const {plot, columns} = record.config;

    // Wrangled on only while its node is the current one, which every selection and repair is of
    const wrangling = wranglingSupportId === record.id && record.hostId === tableName;
    if (wrangling) return <WrangleErrorPlot record={record} />;

    const changeColumns = (next) => updateSupportNode(record.id, (current) => ({
        config: {...current.config, columns: next},
    }));

    return (
        <div className="support-plot-body">
            <ErrorPlotCard
                table={record.hostId}
                plot={plot}
                columns={columns}
                columnChoices={hostColumns(host)}
                onColumns={changeColumns}
            />
        </div>
    );
}
