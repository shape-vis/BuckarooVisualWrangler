import {useContext} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {ViewContext} from "../../pages/Buckaroo.jsx";
import DriftPlotCard from "./DriftPlotCard.jsx";
import {SupportPlotGallery} from "./SupportPlotGallery.jsx";
import {hostColumns} from "./registry.js";

/**
 * The drift-plot kind of supporting sub-node: how far its host's data has moved from root on one column, drawn
 * as the compare window draws drift but for the one node - see DriftPlotCard.
 *
 * Picked from a gallery, as error plots are: a card for each attribute selected in the attribute panel, its
 * column changeable before it is added and the sub-node's after. The Open in its header shows it in the plot
 * analysis view - the compare window - where a column picked carries back (see supportOpen.js).
 *
 * Its config is {column}.
 */

export function DriftGallery({hostId, onAdd}) {
    const {selectedAttributes = []} = useContext(ViewContext) ?? {};
    const {serverNodesById} = usePgraph();

    const columnChoices = hostColumns(serverNodesById?.[hostId]);
    const cards = selectedAttributes
        .filter((attribute) => columnChoices.includes(attribute))
        .map((column) => ({id: `drift:${column}`, columns: [column]}));

    return (
        <SupportPlotGallery
            wide
            cards={cards}
            onAdd={(card, columns) => onAdd({column: columns[0]})}
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

export function DriftBody({record, host}) {
    const {updateSupportNode} = usePgraph();

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
