from re import error


class DataState:
    """
    This class is used to manage the state of the app as the user makes modifications to the datatable during their wrangling
    session -> Later this functionality will need to operate on the database directly instead of dataframes

    it works by using two stacks, the current state will be at the top of the right
    stack

    for undo: pop from left stack, push to top of right stack, return that
    for redo: pop from right stack, push to top of left stack, return top of right
    for current table: return top of left stack

    """

    def __init__(self):
        # state stack comprises of a dictionary of dataframes, {"df":df,"error_df":error_df,"error_dist":error_dist_df}
        self.left_state_stack = []
        self.right_state_stack = []
        self.original_error_table = None
        self.original_df = None
        self.original_cached_for_current_session = False
        self.current_error_dist = None

    """
    Setter,Getter functions for the data state management
    """

    def push_left_table_stack(self, table):
        self.left_state_stack.append(table)
    def push_right_table_stack(self, table):
        self.right_state_stack.append(table)
    def pop_left_table_stack(self):
        return self.left_state_stack.pop()
    def pop_right_table_stack(self):
        return self.right_state_stack.pop()

    def set_original_error_table(self, original_error_table):
        self.original_error_table = original_error_table
    def get_original_error_table(self):
        return self.original_error_table

    def set_original_df(self, original_df):
        self.original_df = original_df
    def get_original_df(self):
        return self.original_df


    #give the top df on the right stack
    def get_current_state(self):
        if len(self.right_state_stack) > 0:
            return self.right_state_stack[-1]
        else:
            return None
    def set_current_state(self, table_instance):
        if len(self.right_state_stack) > 0:
            self.push_left_table_stack(self.right_state_stack.pop())
            self.push_right_table_stack(table_instance)
        else:
            self.push_right_table_stack(table_instance)

    """
    Class function for redo, undo
    """
    def undo(self):
        if len(self.left_state_stack) > 0:
            prev_state = self.left_state_stack.pop()
            self.right_state_stack.append(prev_state)

    def redo(self):
        right_table_stack_len = len(self.right_state_stack)
        if right_table_stack_len > 1:
            next_state = self.right_state_stack.pop()
            self.left_state_stack.append(next_state)


