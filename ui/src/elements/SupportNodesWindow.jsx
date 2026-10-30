// SupportNodesWindow.jsx
// One of the Plots view's windows, opened from a node's support button or the header's Add Support Nodes. Two
// sections, styled apart so neither is mistaken for the other: adding - pick a kind of supporting sub-node, fill in
// that kind's settings, and add it beside the node or its incoming edge, which the section says plainly at its
// top - and what the node already has, to look over and remove.
// Docked as the Plots view's Support tab or popped out into a window of its own, as the compare window is.

import {useCallback, useState} from "react";
import {createPortal} from "react-dom";
import PlotsWindow from "./PlotsWindow.jsx";
import {usePgraph} from "../store/PGraphContext.jsx";
import {HostWindowContext} from "../store/HostWindowContext.jsx";
import {useDockableWindow} from "../store/plotsWindows.js";
import {SUPPORT_WINDOW_ID} from "../store/supportNodes.js";
import {
    SUPPORT_NODE_TYPE_LIST, anchorOf, findSameSupport, getSupportType, recordSizeOf,
} from "../graph_objects/supportNodes/registry.js";
import {nodeName} from "../utils/comparison.js";
import "../styles/SupportNodesWindow.css";

const WINDOW_LABEL = "Support nodes";

/**
 * The window, rendered once beside the views and outside the container a wrangle remounts, so it survives one.
 * Shown while a host is chosen; its content is portalled into the window's own element, which useDockableWindow
 * moves between its tab and its popup.
 */
export default function SupportNodesWindow() {
    const {supportWindowHost, closeSupportWindow} = usePgraph();
    const dock = useDockableWindow({
        id: SUPPORT_WINDOW_ID,
        label: WINDOW_LABEL,
        open: Boolean(supportWindowHost),
        onClose: closeSupportWindow,
    });

    const {popOut} = dock;
    const popOutWindow = useCallback(() => popOut(WINDOW_LABEL), [popOut]);

    if (!supportWindowHost) return null;

    return createPortal(
        <HostWindowContext.Provider value={dock.hostWindow}>
            <PlotsWindow
                className="support-window"
                title="Support nodes"
                titleId="support-window-title"
                // subtitle="Plots and readouts kept beside a node, or beside the edge into it"
                placement={dock.placement}
                onPopOut={popOutWindow}
                onDock={dock.dockIn}
                onClose={dock.close}
            >
                {/* Keyed on the host, so each node starts from a fresh form */}
                <SupportNodesForm key={supportWindowHost} hostId={supportWindowHost} />
            </PlotsWindow>
        </HostWindowContext.Provider>,
        dock.hostEl,
    );
}

// The kinds the window offers. Some are only ever made elsewhere - Save in the compare window makes Compare ones
const ADDABLE_KINDS = SUPPORT_NODE_TYPE_LIST.filter((option) => option.addable !== false);

// How much larger than on the graph a kind is previewed here, so its numbers and chart read comfortably
const PREVIEW_SCALE = 1.8;

/* What a kind without a gallery will look like beside this node: its sub-node, drawn for the host as the graph
   will draw it - only larger, and only a picture, so nothing in it reacts to the pointer. */
function SupportPreview({type, hostId, host, config}) {
    const Body = type.Body;
    if (!Body) return null;

    const record = {id: `support:preview:${type.id}`, hostId, kind: type.id, side: "auto", config};
    const graphSize = recordSizeOf(record);
    const size = {
        width: Math.round(graphSize.width * PREVIEW_SCALE),
        height: Math.round(graphSize.height * PREVIEW_SCALE),
    };

    return (
        <figure className="support-window-preview">
            <figcaption className="support-window-preview-caption">Preview</figcaption>
            <div className="support-node support-window-preview-node" style={{width: size.width}} aria-hidden="true">
                <div className="support-node-header">
                    <span className="support-node-title">{type.label}</span>
                </div>
                <Body record={record} host={host} size={size} />
            </div>
        </figure>
    );
}

/* The adding section's heading, which says where what is added goes: beside the node, or - for a kind that hangs
   beside the edge into it - beside that edge, named by the two nodes it joins. */
function AddTitle({hostId, host, anchor}) {
    let target = <strong>node {nodeName(hostId)}</strong>;
    let from = null;
    if (anchor === "edge") {
        target = <strong>the edge into {nodeName(hostId)}</strong>;
        const parent = host?.data?.parent;
        if (parent && parent !== "root") {
            from = <span className="support-window-add-from"> (from {nodeName(parent)})</span>;
        }
    }

    return (
        <h3 id="support-window-add-title" className="support-window-section-title support-window-add-title">
            Add support nodes to {target}{from}
        </h3>
    );
}

function SupportNodesForm({hostId}) {
    const {supportNodes, addSupportNode, removeSupportNode, serverNodesById, comparisonPair} = usePgraph();
    const host = serverNodesById[hostId];
    const attached = supportNodes.filter((record) => record.hostId === hostId);

    // A kind's starting settings, which can depend on the host and on what is selected in the graph
    const configFor = (next) => {
        const defaults = getSupportType(next)?.defaultConfig;
        let config = defaults;
        if (typeof defaults === "function") {
            config = defaults({hostId, comparisonPair, serverNodesById});
        }
        return config ?? {};
    };
    // Why one of a kind with these settings would be a second copy of one the node has, if it would
    const duplicateReason = (option, optionConfig) => {
        if (!findSameSupport(attached, hostId, option.id, optionConfig)) return null;
        return `${nodeName(hostId)} already has this ${option.label.toLowerCase()}.`;
    };

    // Why each kind cannot be added here, if it cannot - the root has no incoming edge, for one. A kind picked from
    // a gallery is checked card by card instead, since each card is a different one
    const reasons = {};
    for (const option of ADDABLE_KINDS) {
        let reason = option.unavailable?.({host, records: attached}) ?? null;
        if (!reason && !option.Gallery) {
            reason = duplicateReason(option, configFor(option.id));
        }
        reasons[option.id] = reason;
    }

    // Opens on the first kind that can be added, so the form is not greeted by a refusal
    const [kind, setKind] = useState(() => {
        const firstAvailable = ADDABLE_KINDS.find((option) => !reasons[option.id]);
        const opening = firstAvailable ?? ADDABLE_KINDS[0];
        return opening?.id ?? null;
    });
    const [config, setConfig] = useState(() => configFor(kind));

    const type = getSupportType(kind);
    const ConfigForm = type?.ConfigForm;
    // A kind picked from a gallery adds straight from its cards, in place of the settings form and Add
    const Gallery = type?.Gallery;
    // The settings form can change what one would show, so it is checked as it stands, not only as it started
    let reason = reasons[kind];
    if (!reason && type && !Gallery) {
        reason = duplicateReason(type, config);
    }
    // Whether a gallery's card would add a second copy of one the node has
    const isAdded = (chosen) => Boolean(findSameSupport(attached, hostId, kind, chosen));
    // What the settings still need before one can be added, if anything
    let incomplete = null;
    if (!reason) {
        incomplete = type?.incomplete?.(config) ?? null;
    }
    // A gallery is only shown when this kind can be added here at all
    const showGallery = Boolean(Gallery) && !reason;
    // A gallery a card a page has the window to itself, so its plots can fill it
    const paged = showGallery && Boolean(type?.galleryPaged);

    const pickKind = (next) => {
        setKind(next);
        setConfig(configFor(next));
    };

    const add = () => {
        if (!type || reason || incomplete) return;
        addSupportNode(hostId, type.id, config);
        setConfig(configFor(type.id));
    };

    return (
        <div className={`support-window-body ${paged ? "support-window-body--fill" : ""}`}>
            <section
                className="support-window-section support-window-section--add"
                aria-labelledby="support-window-add-title"
            >
                <AddTitle hostId={hostId} host={host} anchor={anchorOf({kind})} />

                <div className="support-window-main">
                    <ul className="support-window-kinds" role="listbox" aria-label="Kind of sub-node">
                        {ADDABLE_KINDS.map((option) => (
                            <li key={option.id}>
                                <button
                                    type="button"
                                    role="option"
                                    aria-selected={option.id === kind}
                                    className={[
                                        "support-window-kind",
                                        option.id === kind ? "support-window-kind--active" : "",
                                        reasons[option.id] ? "support-window-kind--unavailable" : "",
                                    ].filter(Boolean).join(" ")}
                                    onClick={() => pickKind(option.id)}
                                >
                                    {option.label}
                                </button>
                            </li>
                        ))}
                    </ul>

                    <div className="support-window-config">
                        {type ? (
                            <>
                                <p className="support-window-description">{type.description}</p>
                                {reason && <p className="support-window-reason">{reason}</p>}
                                {showGallery && (
                                    <Gallery
                                        hostId={hostId}
                                        onAdd={(chosen) => addSupportNode(hostId, type.id, chosen)}
                                        isAdded={isAdded}
                                        paged={paged}
                                    />
                                )}
                                {!Gallery && (
                                    <>
                                        {ConfigForm && !reason && (
                                            <ConfigForm value={config} onChange={setConfig} hostId={hostId} />
                                        )}
                                        {!reason && !incomplete && (
                                            <SupportPreview type={type} hostId={hostId} host={host} config={config} />
                                        )}
                                        {incomplete && <p className="support-window-incomplete">{incomplete}</p>}
                                        <button
                                            type="button"
                                            className="support-window-add"
                                            onClick={add}
                                            disabled={Boolean(reason || incomplete)}
                                        >
                                            Add {type.label.toLowerCase()}
                                        </button>
                                    </>
                                )}
                            </>
                        ) : (
                            <p className="support-window-description">No kinds of sub-node are registered.</p>
                        )}
                    </div>
                </div>
            </section>

            <section
                className="support-window-section support-window-section--added"
                aria-labelledby="support-window-added-title"
            >
                <h3 id="support-window-added-title" className="support-window-section-title">
                    Support Nodes added to {nodeName(hostId)}: <span className="support-window-count">{attached.length}</span>
                </h3>
                {attached.length === 0 ? (
                    <p className="support-window-empty">None yet - what you add above is listed here.</p>
                ) : (
                    <ul className="support-window-attached">
                        {attached.map((record) => (
                            <AttachedRow key={record.id} record={record} onRemove={removeSupportNode} />
                        ))}
                    </ul>
                )}
            </section>
        </div>
    );
}

/* One sub-node the node already has: its badge's picture, its kind and where it hangs, what it shows, and the way
   to remove it */
function AttachedRow({record, onRemove}) {
    const type = getSupportType(record.kind);
    const Badge = type?.Badge;
    const label = type?.label ?? record.kind;
    const summary = type?.summary?.(record) ?? "";

    let where = "beside the node";
    if (anchorOf(record) === "edge") {
        where = "beside the incoming edge";
    }

    return (
        <li className="support-window-attached-row">
            <span className="support-window-attached-glyph" aria-hidden="true">
                {Badge && <Badge record={record} />}
            </span>
            <span className="support-window-attached-text">
                <span className="support-window-attached-label">
                    {label}
                    <span className="support-window-side"> · {where}</span>
                </span>
                {summary && <span className="support-window-attached-summary" title={summary}>{summary}</span>}
            </span>
            <button type="button" className="support-window-remove" onClick={() => onRemove(record.id)}>Remove</button>
        </li>
    );
}
