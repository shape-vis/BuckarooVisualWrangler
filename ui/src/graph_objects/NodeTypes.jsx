import { useContext, useEffect, useRef, useState } from "react";
import "../styles/Nodes.css"
import { Handle, Position, NodeResizer } from "@xyflow/react";
import {IconButton} from "../elements/Buttons.jsx";
import "../styles/Buttons.css"
import MatrixView from "../panels/SelectionPanel.jsx";
import { ViewContext } from "../pages/Buckaroo.jsx";
import { usePgraph } from "../store/PGraphContext.jsx";
import { TableNameProvider } from "../store/TableNameContext.jsx";

const NATURAL_W = 800;
const NATURAL_H = 600;

function ScaledMatrix() {
    const containerRef = useRef(null);
    const [scale, setScale] = useState({ x: 1, y: 1 });

    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        const obs = new ResizeObserver(() => {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                setScale({ x: r.width / NATURAL_W, y: r.height / NATURAL_H });
            }
        });
        obs.observe(el);
        return () => obs.disconnect();
    }, []);

    return (
        <div ref={containerRef} className="note-node-embedded-matrix">
            <div
                className="note-node-embedded-matrix-inner"
                style={{
                    width: NATURAL_W,
                    height: NATURAL_H,
                    transform: `scale(${scale.x}, ${scale.y})`,
                }}
            >
                <MatrixView />
            </div>
        </div>
    );
}

function NodeBody({ id, data }) {
    const { activeView } = useContext(ViewContext);
    const { toggleNodePlots, collapseNode, setNodeNote } = usePgraph();
    const showPlots = !!data.showPlots;
    const showEmbedded = activeView === "embedded" && showPlots;

    const [editingNote, setEditingNote] = useState(false);
    const [draftNote, setDraftNote] = useState(data.note || "");

    const handlePlotToggle = (e) => {
        e.stopPropagation();
        toggleNodePlots(id);
    };

    const handleCollapse = (e) => {
        e.stopPropagation();
        collapseNode(id);
    };

    const handlePencilClick = (e) => {
        e.stopPropagation();
        setDraftNote(data.note || "");
        setEditingNote((v) => !v);
    };

    const handleSaveNote = (e) => {
        e.stopPropagation();
        setNodeNote(id, draftNote.trim());
        setEditingNote(false);
    };

    const handleCancelNote = (e) => {
        e.stopPropagation();
        setEditingNote(false);
    };

    const stopPropagation = (e) => e.stopPropagation();

    return (
        <>
            {showEmbedded && (
                <NodeResizer
                    minWidth={320}
                    minHeight={260}
                    lineClassName="note-node-resizer-line"
                    handleClassName="note-node-resizer-handle"
                />
            )}
            <div className={showEmbedded ? "note-node--embedded-active" : undefined}>
                <div className={"node-node-label"}>
                    <h3>{data.label}</h3>
                    <div className={"note-node-icon-container"}>
                        <IconButton
                            className="node-sub-buttons"
                            onClick={handlePencilClick}
                            title={data.note ? "Edit note" : "Add note"}
                        >
                            &#9998;
                        </IconButton>
                        <IconButton
                            className={showPlots ? "node-sub-button-chart-active" : "node-sub-button-chart"}
                            onClick={handlePlotToggle}
                            title={showPlots ? "Hide plots" : "Show plots"}
                        >
                            &#9602;&#9605;&#9603;&#9607;&#9601;
                        </IconButton>
                        {showEmbedded && (
                            <IconButton
                                className="node-sub-button-collapse"
                                onClick={handleCollapse}
                                title="Collapse node to label size"
                            >
                                &#8854;
                            </IconButton>
                        )}
                    </div>
                </div>
                {editingNote && (
                    <div
                        className="node-note-editor nodrag"
                        onMouseDown={stopPropagation}
                        onClick={stopPropagation}
                    >
                        <textarea
                            className="node-note-textarea nodrag"
                            value={draftNote}
                            onChange={(e) => setDraftNote(e.target.value)}
                            onMouseDown={stopPropagation}
                            onKeyDown={stopPropagation}
                            placeholder="Short note..."
                            rows={3}
                            autoFocus
                        />
                        <div className="node-note-buttons">
                            <button className="node-note-btn node-note-btn--save" onClick={handleSaveNote}>Save</button>
                            <button className="node-note-btn" onClick={handleCancelNote}>Cancel</button>
                        </div>
                    </div>
                )}
                {!editingNote && data.note && (
                    <div className="node-note-display" title={data.note}>{data.note}</div>
                )}
                {showEmbedded && (
                    <TableNameProvider initialTableName={id}>
                        <ScaledMatrix />
                    </TableNameProvider>
                )}
            </div>
        </>
    );
}

export function NoteNode({ id, data, isConnectable }) {
    return (
        <>
            <Handle type="target" position={Position.Top} isConnectable={isConnectable}/>
            <NodeBody id={id} data={data} />
            <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
        </>
    );
}

export function RootNoteNode({ id, data, isConnectable }) {
    return (
        <>
            <NodeBody id={id} data={data} />
            <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
        </>
    );
}
