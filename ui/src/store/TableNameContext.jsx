import { createContext, useContext, useState } from "react";

const TableNameContext = createContext();

export function TableNameProvider({ initialTableName, children }) {
    const [tableName, setTableName] = useState(initialTableName || "unknown_table");
    return (
        <TableNameContext.Provider value={{ tableName, setTableName }}>
            {children}
        </TableNameContext.Provider>
    );
}

export function useTableName() {
    return useContext(TableNameContext);
}
