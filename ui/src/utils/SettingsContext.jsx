import { createContext, useContext, useState } from "react";

export const SettingsContext = createContext();

export function SettingsProvider({ children }) {
    const [axisTextSize, setAxisTextSizeState] = useState(8);
    const [selectedAnomalyMethods, setSelectedAnomalyMethodsState] = useState(["zscore"]);
    const [rarityThreshold, setRarityThresholdState] = useState(0.05);

    function setAxisTextSize(size) {
        setAxisTextSizeState(size);
        document.documentElement.style.setProperty("--axis-text-size", size + "px");
    }

    function setSelectedAnomalyMethods(methods) {
        const normalized = Array.isArray(methods)
            ? [...new Set(methods.map(method => String(method).trim().toLowerCase()))]
            : [];

        setSelectedAnomalyMethodsState(normalized.length > 0 ? normalized : ["zscore"]);
    }

    function setRarityThreshold(value) {
        const parsed = Number(value);
        if (Number.isNaN(parsed)) {
            setRarityThresholdState(0.05);
            return;
        }

        const clamped = Math.max(0, Math.min(1, parsed));
        setRarityThresholdState(clamped);
    }

    return (
        <SettingsContext.Provider value={{
            axisTextSize,
            setAxisTextSize,
            selectedAnomalyMethods,
            setSelectedAnomalyMethods,
            rarityThreshold,
            setRarityThreshold,
        }}>
            {children}
        </SettingsContext.Provider>
    );
}

export const useSettings = () => useContext(SettingsContext);
