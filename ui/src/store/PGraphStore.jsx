import { createContext, useContext } from "react";

export const PGraphContext = createContext(null);

export function usePgraph() {
    return useContext(PGraphContext);
}
