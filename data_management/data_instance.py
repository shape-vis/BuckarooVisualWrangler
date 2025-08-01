
from data_management.data_integration import generate_1d_histogram_data, generate_2d_histogram_data

"""Need to have this class store:

    Wrangle performed
    rows affected
    regular table
    error table
    """
class DataInstance:
    def __init__(self,wrangle_performed,rows_affected,regular_table,error_table):
        self.wrangle_performed = wrangle_performed
        self.rows_affected = rows_affected
        self.regular_table = regular_table
        self.error_table = error_table

    """Setters"""
    def set_wrangle_performed(self, wrangle_performed):
        self.wrangle_performed = wrangle_performed
    def set_rows_affected(self, rows_affected):
        self.rows_affected = rows_affected
    def set_regular_table(self, regular_table):
        self.regular_table = regular_table
    def set_error_table(self, error_table):
        self.error_table = error_table

    """Getters"""
    def get_wrangle_performed(self):
        return self.wrangle_performed
    def get_rows_affected(self):
        return self.rows_affected
    def get_regular_table(self):
        return self.regular_table
    def get_error_table(self):
        return self.error_table




