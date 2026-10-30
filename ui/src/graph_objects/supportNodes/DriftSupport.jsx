import {useContext} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {ViewContext} from "../../pages/Buckaroo.jsx";
import DriftPlotCard from "./DriftPlotCard.jsx";
import DriftMiniature from "./DriftMiniature.jsx";
import {SupportPlotGallery} from "./SupportPlotGallery.jsx";
import {fitsFullPlot} from "./compareView.js";
import {hostColumns} from "./registry.js";

/**
 * The drift-plot kind of supporting sub-node: how far its host's data has moved from root on one column, drawn
 * as the compare window draws drift but for the one node - see DriftPlotCard.
 *
 * Picked from a gallery, as error plots are: a card for each attribute selected in the attribute panel, its
 * column changeable before it is added and the sub-node's after. A drift plot has a lot to show, so the gallery
 * gives it the whole window, a page each, when the window asks for that (paged - see the registry's
 * galleryPaged). The Open in its header shows it in the plot analysis view - the compare window - where a column
 * picked carries back (see supportActions.js).
 *
 * Its config is {column}.
 */

export function DriftGallery({hostId, onAdd, isAdded, paged = false}) {
    const {selectedAttributes = []} = useContext(ViewContext) ?? {};
    const {serverNodesById} = usePgraph();

    const columnChoices = hostColumns(serverNodesById?.[hostId]);
    const cards = selectedAttributes
        .filter((attribute) => columnChoices.includes(attribute))
        .map((column) => ({id: `drift:${column}`, label: column, columns: [column]}));

    return (
        <SupportPlotGallery
            paged={paged}
            cards={cards}
            onAdd={(card, columns) => onAdd({column: columns[0]})}
            isAdded={(card, columns) => isAdded?.({column: columns[0]})}
            emptyHint="Select attributes in the attribute panel to see their drift for this node here."
            renderCard={({columns, setColumns, enabled, addButton}) => (
                <DriftPlotCard
                    table={hostId}
                    column={columns[0]}
                    columnChoices={columnChoices}
                    onColumn={(column) => setColumns([column])}
                    enabled={enabled}
                    actions={addButton}
                />
            )}
        />
    );
}

/* The sub-node zooms semantically, as a compare sub-node does: too small for the whole plot, it shows the plot in
   miniature - its real ridgeline or Sankey, small and bare, with its column's name over it - rather than a plot
   squeezed past reading. The expand button in its header switches between the two (see SupportNode). */
export function DriftBody({record, host, size}) {
    const {updateSupportNode} = usePgraph();

    if (!fitsFullPlot(size)) {
        return (
            <div className="support-plot-body">
                <DriftMiniature a={record.hostId} b={record.hostId} column={record.config.column} />
            </div>
        );
    }

    const changeColumn = (column) => updateSupportNode(record.id, (current) => ({
        config: {...current.config, column},
    }));

    return (
        <div className="support-plot-body">
            <DriftPlotCard
                table={record.hostId}
                column={record.config.column}
                columnChoices={hostColumns(host)}
                onColumn={changeColumn}
            />
        </div>
    );
}
