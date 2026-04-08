import { createContext, useContext, useCallback, useRef, useState } from "react";

const LoadingContext = createContext();

export function LoadingProvider({ children }) {
    const countRef = useRef(0);
    const [isLoading, setIsLoading] = useState(false);

    const addLoader = useCallback(() => {
        countRef.current += 1;
        setIsLoading(true);
    }, []);

    const removeLoader = useCallback(() => {
        countRef.current = Math.max(0, countRef.current - 1);
        if (countRef.current === 0) setIsLoading(false);
    }, []);

    return (
        <LoadingContext.Provider value={{ isLoading, addLoader, removeLoader }}>
            {children}
        </LoadingContext.Provider>
    );
}

export function useLoading() {
    return useContext(LoadingContext);
}
