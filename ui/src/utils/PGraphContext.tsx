import { createContext, useContext, useState} from "react";

export const PGraphContext = createContext();

export function PGraphProvider({ initialSingleState, children }) {
    const [pGraph, setPGraph] = useState( initialSingleState || "no_graph");
    return (
        <PGraphContext.Provider value={{ pGraph, setPGraph}}>
            {children}
        </PGraphContext.Provider>
    )
}