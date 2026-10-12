// SupportNodesModal.jsx
// Opened from a node's support button: pick a kind of supporting sub-node, fill in that kind's settings, and
// add it beside the node or its incoming edge. Also lists the sub-nodes the node already has, to remove them.

import {useEffect, useState} from "react";
import {createPortal} from "react-dom";
import Modal from "./Modal.jsx";
import {usePgraph} from "../store/PGraphContext.jsx";
import {SUPPORT_NODE_TYPE_LIST, anchorOf, getSupportType} from "../graph_objects/supportNodes/registry.js";
import {nodeName} from "../utils/comparison.js";
import "../styles/SupportNodesModal.css";

/* Rendered once, beside the graph, and shown while a host is chosen. Portalled to the body: React Flow
   transforms everything inside its canvas, and a fixed overlay inside a transformed element is fixed to that
   element rather than to the window. */
export default function SupportNodesModal() {
    const {supportModalHost, closeSupportModal} = usePgraph();

    useEffect(() => {
        if (!supportModalHost) return undefined;
        const onKey = (event) => { if (event.key === "Escape") closeSupportModal(); };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [supportModalHost, closeSupportModal]);

    if (!supportModalHost) return null;

    // Keyed on the host, so each opening starts from a fresh form
    return createPortal(
        <Modal visible>
            <SupportNodesForm key={supportModalHost} hostId={supportModalHost} onClose={closeSupportModal} />
        </Modal>,
        document.body,
    );
}

// The kinds the modal offers. Some are only ever made elsewhere - Save in the compare window makes Compare ones
const ADDABLE_KINDS = SUPPORT_NODE_TYPE_LIST.filter((option) => option.addable !== false);

function SupportNodesForm({hostId, onClose}) {
    const {supportNodes, addSupportNode, removeSupportNode, serverNodesById, comparisonPair} = usePgraph();
    const host = serverNodesById[hostId];
    const attached = supportNodes.filter((record) => record.hostId === hostId);

    // Why each kind cannot be added here, if it cannot - the root has no incoming edge, for one
    const reasons = Object.fromEntries(ADDABLE_KINDS.map((option) => (
        [option.id, option.unavailable?.({host, records: attached}) ?? null])));

    // Opens on the first kind that can be added, so the form is not greeted by a refusal
    const [kind, setKind] = useState(
        () => (ADDABLE_KINDS.find((option) => !reasons[option.id]) ?? ADDABLE_KINDS[0])?.id ?? null);
    // A kind's starting settings, which can depend on the host and on what is selected in the graph
    const configFor = (next) => {
        const defaults = getSupportType(next)?.defaultConfig;
        return (typeof defaults === "function" ? defaults({hostId, comparisonPair, serverNodesById}) : defaults) ?? {};
    };
    const [config, setConfig] = useState(() => configFor(kind));

    const type = getSupportType(kind);
    const ConfigForm = type?.ConfigForm;
    // A kind picked from a gallery adds straight from its cards, in place of the settings form and Add
    const Gallery = type?.Gallery;
    const reason = reasons[kind];
    // What the settings still need before one can be added, if anything
    const incomplete = reason ? null : type?.incomplete?.(config) ?? null;

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
        <div className={`support-modal ${Gallery ? "support-modal--wide" : ""}`}>
            <div className="support-modal-header">
                <h2>Supporting nodes · {nodeName(hostId)}</h2>
                <button type="button" className="support-modal-close" onClick={onClose} title="Close">×</button>
            </div>

            <div className="support-modal-body">
                <ul className="support-modal-kinds" role="listbox" aria-label="Kind of sub-node">
                    {ADDABLE_KINDS.map((option) => (
                        <li key={option.id}>
                            <button
                                type="button"
                                role="option"
                                aria-selected={option.id === kind}
                                className={[
                                    "support-modal-kind",
                                    option.id === kind ? "support-modal-kind--active" : "",
                                    reasons[option.id] ? "support-modal-kind--unavailable" : "",
                                ].filter(Boolean).join(" ")}
                                onClick={() => pickKind(option.id)}
                            >
                                {option.label}
                            </button>
                        </li>
                    ))}
                </ul>

                <div className="support-modal-config">
                    {type ? (
                        <>
                            <p className="support-modal-description">{type.description}</p>
                            {reason && <p className="support-modal-reason">{reason}</p>}
                            {Gallery ? (
                                !reason && <Gallery hostId={hostId} onAdd={(chosen) => addSupportNode(hostId, type.id, chosen)} />
                            ) : (
                                <>
                                    {ConfigForm && !reason && <ConfigForm value={config} onChange={setConfig} hostId={hostId} />}
                                    {incomplete && <p className="support-modal-incomplete">{incomplete}</p>}
                                    <button
                                        type="button"
                                        className="support-modal-add"
                                        onClick={add}
                                        disabled={Boolean(reason || incomplete)}
                                    >
                                        Add {type.label.toLowerCase()}
                                    </button>
                                </>
                            )}
                        </>
                    ) : (
                        <p className="support-modal-description">No kinds of sub-node are registered.</p>
                    )}
                </div>
            </div>

            <div className="support-modal-attached">
                <h3>On this node</h3>
                {attached.length === 0 ? (
                    <p className="support-modal-empty">None yet</p>
                ) : (
                    <ul>
                        {attached.map((record) => (
                            <li key={record.id} className="support-modal-attached-row">
                                <span>
                                    {getSupportType(record.kind)?.label ?? record.kind}
                                    <span className="support-modal-side">
                                        {" · "}{anchorOf(record) === "edge" ? "incoming edge" : "beside node"}
                                    </span>
                                </span>
                                <button type="button" onClick={() => removeSupportNode(record.id)}>Remove</button>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    );
}
