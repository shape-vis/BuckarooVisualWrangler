import { useState, useEffect, useRef } from "react";
import Modal from "./Modal.jsx";
import { useRowRange } from "../utils/RowRangeContext.jsx";
import { useSettings } from "../utils/SettingsContext.jsx";
import "./SettingsModal.css";

const RARITY_PRESETS = [0.01, 0.05, 0.10, 0.15];
const MIN_RARITY = 0.01;
const MAX_RARITY = 0.15;
const RARITY_STEP = 0.0001;

export default function SettingsModal({ visible, onClose }) {
    const { useRange, minId, maxId, setRowRange } = useRowRange();
    const {
        axisTextSize,
        setAxisTextSize,
        selectedAnomalyMethods,
        setSelectedAnomalyMethods,
        rarityThreshold,
        setRarityThreshold,
    } = useSettings();

    const [localUseRange, setLocalUseRange] = useState(useRange);
    const [localMin, setLocalMin] = useState(minId);
    const [localMax, setLocalMax] = useState(maxId);
    const [localAxisTextSize, setLocalAxisTextSize] = useState(axisTextSize);
    const [localAnomalyMethods, setLocalAnomalyMethods] = useState(selectedAnomalyMethods);
    const [localRarityThreshold, setLocalRarityThreshold] = useState(rarityThreshold);
    const previewStartRef = useRef({
        axisTextSize,
        selectedAnomalyMethods,
        rarityThreshold,
    });

    useEffect(() => {
        if (visible) {
            previewStartRef.current = {
                axisTextSize,
                selectedAnomalyMethods,
                rarityThreshold,
            };
            setLocalUseRange(useRange);
            setLocalMin(minId);
            setLocalMax(maxId);
            setLocalAxisTextSize(axisTextSize);
            setLocalAnomalyMethods(selectedAnomalyMethods);
            setLocalRarityThreshold(rarityThreshold);
        }
    }, [visible, useRange, minId, maxId, axisTextSize, selectedAnomalyMethods, rarityThreshold]);

    function handleAxisTextSizeChange(size) {
        setLocalAxisTextSize(size);
        setAxisTextSize(size);
    }

    function toggleAnomalyMethod(method) {
        setLocalAnomalyMethods(prev => {
            let nextMethods;

            if (prev.includes(method)) {
                if (prev.length === 1) {
                    return prev;
                }
                nextMethods = prev.filter(currentMethod => currentMethod !== method);
            } else {
                nextMethods = [...prev, method];
            }

            setSelectedAnomalyMethods(nextMethods);
            return nextMethods;
        });
    }

    function handleApply() {
        if (localUseRange) {
            const parsedMin = parseInt(localMin, 10);
            const parsedMax = parseInt(localMax, 10);
            if (isNaN(parsedMin) || isNaN(parsedMax) || parsedMin < 0 || parsedMax <= parsedMin) return;
            setRowRange(true, parsedMin, parsedMax);
        } else {
            setRowRange(false, localMin, localMax);
        }
        setSelectedAnomalyMethods(localAnomalyMethods);
        setRarityThreshold(localRarityThreshold);
        onClose();
    }

    function handleCancel() {
        setAxisTextSize(previewStartRef.current.axisTextSize);
        setSelectedAnomalyMethods(previewStartRef.current.selectedAnomalyMethods);
        setRarityThreshold(previewStartRef.current.rarityThreshold);
        onClose();
    }

    function handleRaritySliderChange(event) {
        const nextValue = Number(event.target.value);
        setLocalRarityThreshold(nextValue);
        setRarityThreshold(nextValue);
    }

    function handlePresetClick(value) {
        setLocalRarityThreshold(value);
        setRarityThreshold(value);
    }

    function formatPercent(value) {
        return `${(value * 100).toFixed(2)}%`;
    }

    return (
        <Modal visible={visible}>
            <h2 style={{ marginTop: 0, marginBottom: 20 }}>Plot Settings</h2>

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
                        className={`settings-toggle-btn ${localAxisTextSize === 7 ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => handleAxisTextSizeChange(7)}
                    >S</button>
                    <button
                        className={`settings-toggle-btn ${localAxisTextSize === 9 ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => handleAxisTextSizeChange(9)}
                    >M</button>
                    <button
                        className={`settings-toggle-btn ${localAxisTextSize === 12 ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => handleAxisTextSizeChange(12)}
                    >L</button>
                </div>
            </div>

            <div className="settings-row">
                <label className="settings-label">Anomaly Methods</label>
                <div className="settings-toggle">
                    <button
                        className={`settings-toggle-btn ${localAnomalyMethods.includes("zscore") ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => toggleAnomalyMethod("zscore")}
                    >
                        Z-Score
                    </button>
                    <button
                        className={`settings-toggle-btn ${localAnomalyMethods.includes("mad") ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => toggleAnomalyMethod("mad")}
                    >
                        MAD
                    </button>
                    <button
                        className={`settings-toggle-btn ${localAnomalyMethods.includes("iqr") ? "settings-toggle-btn--active" : ""}`}
                        onClick={() => toggleAnomalyMethod("iqr")}
                    >
                        IQR
                    </button>
                </div>
            </div>

            <div className="settings-row">
                <label className="settings-label">Rarity Threshold</label>
                <div className="settings-slider-block">
                    <div className="settings-slider-value">{formatPercent(localRarityThreshold)}</div>
                    <input
                        className="settings-slider"
                        type="range"
                        min={MIN_RARITY}
                        max={MAX_RARITY}
                        step={RARITY_STEP}
                        list="rarity-threshold-presets"
                        value={localRarityThreshold}
                        onChange={handleRaritySliderChange}
                    />
                    <datalist id="rarity-threshold-presets">
                        {RARITY_PRESETS.map(value => (
                            <option key={value} value={value} label={`${value * 100}%`} />
                        ))}
                    </datalist>
                    <div className="settings-slider-presets">
                        {RARITY_PRESETS.map(value => (
                            <button
                                key={value}
                                className={`settings-preset-btn ${Math.abs(localRarityThreshold - value) < (RARITY_STEP / 2) ? "settings-preset-btn--active" : ""}`}
                                onClick={() => handlePresetClick(value)}
                            >
                                {Math.round(value * 100)}%
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            <div className="settings-actions">
                <button className="settings-btn settings-btn--apply" onClick={handleApply}>
                    Apply
                </button>
                <button className="settings-btn settings-btn--cancel" onClick={handleCancel}>
                    Cancel
                </button>
            </div>
        </Modal>
    );
}
