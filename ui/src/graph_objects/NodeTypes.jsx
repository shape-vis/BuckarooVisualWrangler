import { useState } from "react";
import "../styles/Nodes.css"
import { Handle, Position } from "@xyflow/react";
import { IconButton } from "../elements/Buttons.jsx";
import "../styles/Buttons.css"
import { usePgraph } from "../store/PGraphContext.jsx";
import { useLLMOrchestrator } from "../store/LLMOrchestratorContext.jsx";

function NodeBody({ id, data }) {
    const { setNodeNote, setNodeLabel } = usePgraph();
    const { selectedNodeId, selectNode, startAnalysis, status } = useLLMOrchestrator();

    const [editingNote, setEditingNote] = useState(false);
    const [draftNote, setDraftNote] = useState(data.note || "");
    const [editingLabel, setEditingLabel] = useState(false);
    const [draftLabel, setDraftLabel] = useState(data.label || "");

    const isSelected = selectedNodeId === id;
    const isAnalyzingThisNode = isSelected && status !== "idle" && status !== "error";

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

    const handleLabelDoubleClick = (e) => {
        e.stopPropagation();
        setDraftLabel(data.label || "");
        setEditingLabel(true);
    };

    const commitLabel = () => {
        const next = draftLabel.trim();
        if (next && next !== data.label) {
            setNodeLabel(id, next);
        }
        setEditingLabel(false);
    };

    const handleLabelKeyDown = (e) => {
        e.stopPropagation();
        if (e.key === "Enter") {
            e.preventDefault();
            commitLabel();
        } else if (e.key === "Escape") {
            e.preventDefault();
            setEditingLabel(false);
        }
    };

    const handleAnalyzeClick = (e) => {
        e.stopPropagation();
        startAnalysis(id);
    };

    const stopPropagation = (e) => e.stopPropagation();

    return (
        <div onClick={(e) => { e.stopPropagation(); selectNode(id); }}>
            <div className={"node-node-label"}>
                {editingLabel ? (
                    <input
                        className="node-label-input nodrag"
                        value={draftLabel}
                        onChange={(e) => setDraftLabel(e.target.value)}
                        onBlur={commitLabel}
                        onKeyDown={handleLabelKeyDown}
                        onMouseDown={stopPropagation}
                        onClick={stopPropagation}
                        onDoubleClick={stopPropagation}
                        autoFocus
                    />
                ) : (
                    <h3 onDoubleClick={handleLabelDoubleClick} title="Double-click to rename">
                        {data.label}
                    </h3>
                )}
                <div className={"note-node-icon-container"}>
                    <IconButton
                        className="node-sub-buttons"
                        onClick={handlePencilClick}
                        title={data.note ? "Edit note" : "Add note"}
                    >
                        &#9998;
                    </IconButton>
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
            {isSelected && !data.isShadow && (
                <div className="node-llm-action nodrag" onMouseDown={stopPropagation}>
                    <button
                        className="node-llm-analyze-btn"
                        onClick={handleAnalyzeClick}
                        disabled={isAnalyzingThisNode}
                    >
                        {isAnalyzingThisNode ? "Wrangling…" : "Wrangle with BisonBot"}
                    </button>
                </div>
            )}
        </div>
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
