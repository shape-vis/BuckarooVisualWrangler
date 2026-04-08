import { useState, useEffect } from "react";
import Modal from "./Modal.jsx";
import { useRowRange } from "../store/RowRangeContext.jsx";
import { useSettings } from "../store/SettingsContext.jsx";
import "../styles/SettingsModal.css";

export default function SettingsModal({ visible, onClose }) {
    const { useRange, minId, maxId, setRowRange } = useRowRange();
    const { axisTextSize, setAxisTextSize } = useSettings();

    const [localUseRange, setLocalUseRange] = useState(useRange);
    const [localMin, setLocalMin] = useState(minId);
    const [localMax, setLocalMax] = useState(maxId);

    useEffect(() => {
        if (visible) {
            setLocalUseRange(useRange);
            setLocalMin(minId);
            setLocalMax(maxId);
        }
    }, [visible]);

    function handleApply() {
        if (localUseRange) {
            const parsedMin = parseInt(localMin, 10);
            const parsedMax = parseInt(localMax, 10);
            if (isNaN(parsedMin) || isNaN(parsedMax) || parsedMin < 0 || parsedMax <= parsedMin) return;
            setRowRange(true, parsedMin, parsedMax);
        } else {
            setRowRange(false, localMin, localMax);
        }
        onClose();
    }

    return (
        <Modal visible={visible}>
            <h2>Plot Settings</h2>

            {/* <div className="settings-row">
                <label className="settings-label">Data Range</label>
                <div className="settings-toggle">
                    <button
                        className={`settings-toggle-btn ${!localUseRange ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => setLocalUseRange(false)}
                    >
                        Whole Dataset
                    </button>
                    <button
                        className={`settings-toggle-btn ${localUseRange ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => setLocalUseRange(true)}
                    >
                        ID Range
                    </button>
                </div>
            </div>

            {localUseRange && (
                <>
                    <div className="settings-row">
                        <label className="settings-label">Min Row ID</label>
                        <input
                            className="settings-input"
                            type="number"
                            value={localMin}
                            min={0}
                            onChange={e => setLocalMin(e.target.value)}
                        />
                    </div>
                    <div className="settings-row">
                        <label className="settings-label">Max Row ID</label>
                        <input
                            className="settings-input"
                            type="number"
                            value={localMax}
                            min={1}
                            onChange={e => setLocalMax(e.target.value)}
                        />
                    </div>
                </>
            )} */}

            <div className="settings-row">
                <label className="settings-label">Axis Text Size</label>
                <div className="settings-toggle">
                    <button
                        className={`settings-toggle-btn ${axisTextSize === 7 ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => setAxisTextSize(7)}
                    >S</button>
                    <button
                        className={`settings-toggle-btn ${axisTextSize === 9 ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => setAxisTextSize(9)}
                    >M</button>
                    <button
                        className={`settings-toggle-btn ${axisTextSize === 12 ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => setAxisTextSize(12)}
                    >L</button>
                </div>
            </div>

            <div className="settings-actions">
                <button className="settings-btn settings-btn--apply" onClick={handleApply}>
                    Apply
                </button>
                <button className="settings-btn settings-btn--cancel" onClick={onClose}>
                    Cancel
                </button>
            </div>
        </Modal>
    );
}
