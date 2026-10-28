import { useState, useEffect } from "react";
import Modal from "./Modal.jsx";
import { useRowRange } from "../store/RowRangeContext.jsx";
import { useSettings } from "../store/SettingsContext.jsx";
import "../styles/SettingsModal.css";

const AXIS_TEXT_SIZES = [
    { label: "S", size: 7 },
    { label: "M", size: 9 },
    { label: "L", size: 12 },
];

export default function SettingsModal({ visible, onClose }) {
    const { useRange, minId, maxId, setRowRange } = useRowRange();
    const { axisTextSize, setAxisTextSize } = useSettings();

    // The row-range controls are hidden for now, but Apply still writes the
    // current range back through setRowRange, so the local copy is kept.
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

            <div className="settings-row">
                <label className="settings-label">Axis Text Size</label>
                <div className="settings-toggle">
                    {AXIS_TEXT_SIZES.map(({ label, size }) => {
                        const activeClass = axisTextSize === size ? "settings-toggle-btn--active" : "";
                        return (
                            <button
                                key={label}
                                className={`settings-toggle-btn ${activeClass}`}
                                onClick={() => setAxisTextSize(size)}
                            >{label}</button>
                        );
                    })}
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
