import { createContext, useContext, useState } from "react";

export const SettingsContext = createContext();

export function SettingsProvider({ children }) {
    const [axisTextSize, setAxisTextSizeState] = useState(8);

    function setAxisTextSize(size) {
        setAxisTextSizeState(size);
        document.documentElement.style.setProperty("--axis-text-size", size + "px");
    }

    return (
        <SettingsContext.Provider value={{ axisTextSize, setAxisTextSize }}>
            {children}
        </SettingsContext.Provider>
    );
}

export const useSettings = () => useContext(SettingsContext);
