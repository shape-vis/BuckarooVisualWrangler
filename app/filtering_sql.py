from execute_sql import execute_sql

"""
Manages a persistent PostgreSQL filtering table that tracks which row IDs satisfy the
currently active set of filters. This table is then joined against by DBOperations to
scope all histogram and scatterplot queries to only the matching rows.
"""

class FilteringSQL:
    def __init__(self, main_table_name, engine):
        self.applied_filters = {}
        self.cur_filter_index = 0
        self.table_exists = False
        self.engine = engine
        self.main_table_name = main_table_name
        self.filtering_table_name = f"{self.main_table_name}_filtering"


    def add_filters(self, sql_filters: list) -> dict:
        """
        Adds a list of new filters to the set of filters and updates the table of satisfying indices.
        :return: a success message and the internal indices of added filters.
        """

        condensed_sql_filter = " AND ".join(sql_filters)
        try:
            if len(self.applied_filters) == 0:
                self.table_exists = True

                # Create fresh filtering table and compute satisfying indices.
                table_creation_query = self.create_filtering_table(condensed_sql_filter)
                execute_sql(table_creation_query, self.engine)
            else:
                # New satisfying indices have to be a subset of indices that already satisfy the other filters.
                new_satisfying_indices = f"""
                DELETE FROM "{self.filtering_table_name}"
                USING "{self.main_table_name}"
                WHERE "{self.filtering_table_name}".ID = "{self.main_table_name}".ID AND NOT ({condensed_sql_filter});
                """
                execute_sql(new_satisfying_indices, self.engine)

            added_filter_indices = []
            # Keep track of filters and an internal index.
            for sql_filter in sql_filters:
                self.applied_filters[self.cur_filter_index] = sql_filter
                added_filter_indices.append(self.cur_filter_index)
                self.cur_filter_index += 1

            return {"Success": True, "Index": added_filter_indices}
        except Exception as e:
            return {"Success": False, "Error": str(e)}


    def create_filtering_table(self, sql_filtering: str):
        """
        Creates the SQL for new filtering table in the postgres database with initial satisfying indices.
        :return: the SQL for the filtering table.
        """

        return f"""
                DROP TABLE IF EXISTS "{self.filtering_table_name}";
    
                CREATE TABLE "{self.filtering_table_name}" AS
                SELECT "ID"
                FROM "{self.main_table_name}"
                WHERE {sql_filtering};
    
                ALTER TABLE "{self.filtering_table_name}"
                ADD PRIMARY KEY ("ID");
                """


    def delete_filters(self, filter_indices: list) -> dict:
        """
        Deletes one or more filters from the filter table and updates the table of satisfying indices.
        For efficiency, gives the option to delete multiple filters at once to not need to recreate the filter
        table several times if the user knows they want to delete more than 1 filter.
        :return: the index of the new filter if success.
        """

        if len(self.applied_filters) == 0:
            return {"Success": False, "Error": "No filter to delete"}

        try:
            for filter_index in filter_indices:
                self.applied_filters.pop(filter_index)

            # Lazily delete the filter table when removing all filters.
            if len(self.applied_filters) == 0:
                self.cur_filter_index = 0
                self.table_exists = False
            else:
                remaining_filters = " AND ".join(self.applied_filters.values())
                table_creation_query = self.create_filtering_table(remaining_filters)
                execute_sql(table_creation_query, self.engine)

            return {"Success": True, "Error": ""}
        except Exception as e:
            return {"Success": False, "Error": str(e)}

