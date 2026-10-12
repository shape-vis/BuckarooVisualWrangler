import {useContext} from "react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {ViewContext} from "../../pages/Buckaroo.jsx";
import ErrorPlotCard from "./ErrorPlotCard.jsx";
import {SupportPlotGallery} from "./SupportPlotGallery.jsx";

/**
 * The error-plot kind of supporting sub-node: one error plot of its host node's table - a histogram of a
 * column or a heatmap of two - drawn as the repair preview draws them.
 *
 * It is picked from a gallery rather than set up through a form: one card for each attribute selected in the
 * attribute panel, and one for each pair of them - the plots the main Plots view shows, for this node's data.
 * Each card's columns can be changed before it is added, and the sub-node's after.
 *
 * The sub-node's plot is only a picture. To select and wrangle, the Open in its header takes the plot to the
 * standard plot view, where brushing and repair already live - see supportOpen.js.
 *
 * Its config is {plot: "histogram" | "heatmap", columns: [x] | [x, y]}.
 */

// The host's columns, in the order its metrics list them
const columnsOf = (serverNodesById, hostId) => Object.keys(serverNodesById?.[hostId]?.data?.metrics?.columns ?? {});

/**
 * The modal's picker for this kind: the selected attributes' histograms, then their pairs' heatmaps, for the
 * host's data. Attributes the host does not have are left out.
 */
export function ErrorPlotGallery({hostId, onAdd}) {
    const {selectedAttributes = []} = useContext(ViewContext) ?? {};
    const {serverNodesById} = usePgraph();

    const columnChoices = columnsOf(serverNodesById, hostId);
    const attributes = selectedAttributes.filter((attribute) => columnChoices.includes(attribute));
    const cards = [
        ...attributes.map((x) => ({id: `histogram:${x}`, plot: "histogram", columns: [x]})),
        ...attributes.flatMap((x, i) => attributes.slice(i + 1)
            .map((y) => ({id: `heatmap:${x}:${y}`, plot: "heatmap", columns: [x, y]}))),
    ];

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

export function ErrorPlotBody({record}) {
    const {serverNodesById, updateSupportNode} = usePgraph();
    const {plot, columns} = record.config;

    return (
        <div className="support-plot-body">
            <ErrorPlotCard
                table={record.hostId}
                plot={plot}
                columns={columns}
                columnChoices={columnsOf(serverNodesById, record.hostId)}
                onColumns={(next) => updateSupportNode(record.id, (current) => ({config: {...current.config, columns: next}}))}
            />
        </div>
    );
}
