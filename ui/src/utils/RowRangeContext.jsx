import { createContext, useContext, useState } from "react";

export const RowRangeContext = createContext(null);

export function RowRangeProvider({ children }) {
    const [useRange, setUseRange] = useState(false);
    const [minId, setMinId] = useState(0);
    const [maxId, setMaxId] = useState(10000);

    function setRowRange(newUseRange, newMin, newMax) {
        setUseRange(newUseRange);
        setMinId(newMin);
        setMaxId(newMax);
    }

    return (
        <RowRangeContext.Provider value={{ useRange, minId, maxId, setRowRange }}>
            {children}
        </RowRangeContext.Provider>
    );
}

export function useRowRange() {
    return useContext(RowRangeContext);
}
