import unittest
import pandas as pd

from data_management.data_instance import DataInstance
from data_management.data_state import DataState


class TestDataState(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.data_state = DataState()
        self.sample_df1 = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
        self.sample_df2 = pd.DataFrame({'A': [7, 8, 9], 'B': [10, 11, 12]})
        self.sample_error_df = pd.DataFrame({'error': ['err1', 'err2']})

        self.data_instance1 = DataInstance("operation1", 3, self.sample_df1, self.sample_error_df)
        self.data_instance2 = DataInstance("operation2", 5, self.sample_df2, self.sample_error_df)

    def test_initialization(self):
        """Test DataState initializes with empty stacks."""
        self.assertEqual(len(self.data_state.left_state_stack), 0)
        self.assertEqual(len(self.data_state.right_state_stack), 0)
        self.assertIsNone(self.data_state.original_error_table)
        self.assertIsNone(self.data_state.original_df)
        self.assertFalse(self.data_state.original_cached_for_current_session)

    def test_push_pop_left_stack(self):
        """Test pushing and popping from left stack."""
        self.data_state.push_left_table_stack(self.data_instance1)
        self.assertEqual(len(self.data_state.left_state_stack), 1)

        popped = self.data_state.pop_left_table_stack()
        self.assertEqual(popped, self.data_instance1)
        self.assertEqual(len(self.data_state.left_state_stack), 0)

    def test_push_pop_right_stack(self):
        """Test pushing and popping from right stack."""
        self.data_state.push_right_table_stack(self.data_instance1)
        self.assertEqual(len(self.data_state.right_state_stack), 1)

        popped = self.data_state.pop_right_table_stack()
        self.assertEqual(popped, self.data_instance1)
        self.assertEqual(len(self.data_state.right_state_stack), 0)

    def test_original_error_table_operations(self):
        """Test setting and getting original error table."""
        self.data_state.set_original_error_table(self.sample_error_df)
        pd.testing.assert_frame_equal(self.data_state.get_original_error_table(), self.sample_error_df)

    def test_original_df_operations(self):
        """Test setting and getting original dataframe."""
        self.data_state.set_original_df(self.sample_df1)
        pd.testing.assert_frame_equal(self.data_state.get_original_df(), self.sample_df1)

    def test_get_current_state_empty_stack(self):
        """Test getting current state when right stack is empty."""
        self.assertIsNone(self.data_state.get_current_state())

    def test_get_current_state_with_data(self):
        """Test getting current state with data in right stack."""
        self.data_state.push_right_table_stack(self.data_instance1)
        self.data_state.push_right_table_stack(self.data_instance2)

        current = self.data_state.get_current_state()
        self.assertEqual(current, self.data_instance2)

    def test_set_current_state_empty_right_stack(self):
        """Test setting current state when right stack is empty."""
        self.data_state.set_current_state(self.data_instance1)

        self.assertEqual(len(self.data_state.right_state_stack), 1)
        self.assertEqual(len(self.data_state.left_state_stack), 0)
        self.assertEqual(self.data_state.get_current_state(), self.data_instance1)

    def test_set_current_state_with_existing_data(self):
        """Test setting current state when right stack has data."""
        self.data_state.push_right_table_stack(self.data_instance1)
        self.data_state.set_current_state(self.data_instance2)

        self.assertEqual(len(self.data_state.right_state_stack), 1)
        self.assertEqual(len(self.data_state.left_state_stack), 1)
        self.assertEqual(self.data_state.get_current_state(), self.data_instance2)
        self.assertEqual(self.data_state.left_state_stack[0], self.data_instance1)

    def test_undo_with_history(self):
        """Test undo when there's history in left stack."""
        self.data_state.push_left_table_stack(self.data_instance1)
        self.data_state.push_right_table_stack(self.data_instance2)

        # Undo should move from left to right stack
        self.data_state.undo()

        self.assertEqual(len(self.data_state.left_state_stack), 0)
        self.assertEqual(len(self.data_state.right_state_stack), 2)
        self.assertEqual(self.data_state.get_current_state(), self.data_instance1)

    def test_undo_without_history(self):
        """Test undo when there's no history in left stack."""
        self.data_state.push_right_table_stack(self.data_instance1)

        # Undo should do nothing when left stack is empty
        self.data_state.undo()

        self.assertEqual(len(self.data_state.left_state_stack), 0)
        self.assertEqual(len(self.data_state.right_state_stack), 1)
        self.assertEqual(self.data_state.get_current_state(), self.data_instance1)

    def test_redo_with_multiple_states(self):
        """Test redo when there are multiple states in right stack."""
        self.data_state.push_right_table_stack(self.data_instance1)
        self.data_state.push_right_table_stack(self.data_instance2)

        # Redo should move from right to left stack
        self.data_state.redo()

        self.assertEqual(len(self.data_state.left_state_stack), 1)
        self.assertEqual(len(self.data_state.right_state_stack), 1)
        self.assertEqual(self.data_state.left_state_stack[0], self.data_instance2)
        self.assertEqual(self.data_state.get_current_state(), self.data_instance1)

    def test_redo_with_single_state(self):
        """Test redo when there's only one state in right stack."""
        self.data_state.push_right_table_stack(self.data_instance1)

        # Redo should do nothing when right stack has only one item
        self.data_state.redo()

        self.assertEqual(len(self.data_state.left_state_stack), 0)
        self.assertEqual(len(self.data_state.right_state_stack), 1)
        self.assertEqual(self.data_state.get_current_state(), self.data_instance1)

    def test_undo_redo_sequence(self):
        """Test a complete undo-redo sequence."""
        # Set up initial state
        self.data_state.set_current_state(self.data_instance1)
        self.data_state.set_current_state(self.data_instance2)

        # Should have: left=[instance1], right=[instance2]
        self.assertEqual(len(self.data_state.left_state_stack), 1)
        self.assertEqual(len(self.data_state.right_state_stack), 1)
        self.assertEqual(self.data_state.get_current_state(), self.data_instance2)

        # Undo
        self.data_state.undo()
        # Should have: left=[], right=[instance2, instance1]
        self.assertEqual(len(self.data_state.left_state_stack), 0)
        self.assertEqual(len(self.data_state.right_state_stack), 2)
        self.assertEqual(self.data_state.get_current_state(), self.data_instance1)

        # Redo
        self.data_state.redo()
        # Should have: left=[instance1], right=[instance2]
        self.assertEqual(len(self.data_state.left_state_stack), 1)
        self.assertEqual(len(self.data_state.right_state_stack), 1)
        self.assertEqual(self.data_state.get_current_state(), self.data_instance2)

    def test_stack_operations_exception_handling(self):
        """Test that popping from empty stacks raises IndexError."""
        with self.assertRaises(IndexError):
            self.data_state.pop_left_table_stack()

        with self.assertRaises(IndexError):
            self.data_state.pop_right_table_stack()

    def test_undo_redo_edge_cases(self):
        """Test edge cases for undo/redo operations."""
        # Test multiple undos when left stack becomes empty
        self.data_state.push_left_table_stack(self.data_instance1)
        self.data_state.push_right_table_stack(self.data_instance2)

        # First undo should work
        self.data_state.undo()
        self.assertEqual(len(self.data_state.left_state_stack), 0)

        # Second undo should do nothing
        self.data_state.undo()
        self.assertEqual(len(self.data_state.left_state_stack), 0)
        self.assertEqual(len(self.data_state.right_state_stack), 2)

        # Test multiple redos when right stack becomes single item
        self.data_state.redo()
        self.assertEqual(len(self.data_state.right_state_stack), 1)

        # Second redo should do nothing
        self.data_state.redo()
        self.assertEqual(len(self.data_state.right_state_stack), 1)
        self.assertEqual(len(self.data_state.left_state_stack), 1)


if __name__ == '__main__':
    unittest.main()