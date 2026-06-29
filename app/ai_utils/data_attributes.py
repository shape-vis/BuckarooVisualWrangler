import numpy as np
import pandas as pd
import json

from pandas.core.arrays import categorical

from app.db_utils.execute_sql import fetch_sql



# TODO: change name to data profile instead of ai_utils / related
# TODO: Make this work with this with server_utils/data_attribute_summary_integration.py to create a data profile class that handles this shit
# This one would just be data profile class while ^^^^ uses it to get the data attribute summaries to show stuff

# maybe move this to a utils script or something?
def load_table_to_df(table_name, engine):
    rows = fetch_sql(f'SELECT * FROM "{table_name}"', False, engine)
    cols = fetch_sql(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}' ORDER BY ordinal_position", False, engine)
    df = pd.DataFrame(rows, columns=[row[0] for row in cols] if cols else None)

    return df

def to_scalar(val):
    if val is None:
        return None
    if isinstance(val, pd.DataFrame):
        if val.empty:
            return None
        return to_scalar(val.iloc[0, 0])  # first row, first column
    if isinstance(val, pd.Series):
        return None if val.empty else to_scalar(val.iloc[0])
    if isinstance(val, (list, tuple)) and len(val) > 0:
        return to_scalar(val[0])
    if hasattr(val, 'item'):
        return val.item()
    return val

class DataProfile:
    # TODO: add a way to figure out where the changes were made (more efficient updating of data attributes
    def __init__(self, table_name, engine=None, main_df=None, error_df=None):
        self.table_name = table_name
        self.data_profile_table_name = "data_profile_" + table_name
        self.engine = engine
        self.main_df = main_df
        self.error_df = error_df
        self.default_attributes = ['mean', 'median', 'min', 'max', 'n_categories', 'mode']
        self.name_to_func = {
            'mean': self.calculate_mean,
            'median': self.calculate_median,
            'min': self.calculate_min,
            'max': self.calculate_max, #TODO: add more,
            'n_categories': self.calculate_num_categories,
            'mode': self.calculate_mode
        }
        self.attribute_type_assignment = { # TODO: fix this name it sucks lol
            'numeric': ['mean', 'median', 'min', 'max', 'mode'],
            'categorical': ['n_categories',
                            'mode']
        }


        if self.main_df is None:
            assert engine is not None, f"engine cannot be None if main_df is None"
            self.main_df = load_table_to_df(table_name, engine)

        if self.error_df is None:
            assert engine is not None, f"engine cannot be None if error_df is None"
            self.error_df = load_table_to_df(f"errors_{table_name}", engine)


    def get_col_data(self, column_name, attribute_name):
        assert (attribute_name in self.attribute_type_assignment['categorical'] or attribute_name in self.attribute_type_assignment['numeric']), f"Invalid attribute name {attribute_name}"

        if attribute_name in self.attribute_type_assignment['categorical']:
            col_data = self.main_df[column_name].fillna('N/A')
        if attribute_name in self.attribute_type_assignment['numeric']:
            col_data = pd.to_numeric(self.main_df[column_name], errors='coerce').dropna()

        return col_data



    def look_up_stat_from_profile(self, attribute_name, column_name):
        data_profile_table_name = "dp_" + self.table_name
        try:
            query = f'SELECT {attribute_name} FROM "{data_profile_table_name}" WHERE column_name = "{column_name}"'
            stat = fetch_sql(query, False, self.engine)

            # TODO: make sure that when nothing matches the query, this still will work
            if stat is None:
                assert False, "AHHHHHHHHHHHHHHHHHHHHHHHHHHHH THIS SHOULDNT BE HAPPENING!!!!!!!!!"
            elif stat.empty: # TODO: idk what I'm doing here
                return None
            return stat
        except Exception as e:
            print(f"Attribute {attribute_name} not found from data profile.")



    def query_summary_stat_from_main_df(self, stat_query, column_name):
        # TODO: fix this probably
        query = f'SELECT {stat_query}("{column_name}") FROM "{self.table_name}"'
        stat = fetch_sql(query, True, self.engine)
        return stat


    def calculate_column_attribute(self, attribute_name, column_name, look_up_stat=True):
        if look_up_stat:
            look_up_value = self.look_up_stat_from_profile(attribute_name, column_name)

            if look_up_value is not None:
                return to_scalar(look_up_value)

        calculate_attribute_func = self.name_to_func[attribute_name]
        return to_scalar(calculate_attribute_func(column_name))

    # TODO: save stat off to table if newly calculated
    def calculate_mean(self, column_name):
        col_data = self.get_col_data(column_name, 'mean')
        try:
            avg = self.query_summary_stat_from_main_df('AVG', column_name)
        except Exception as e:
            print(f"Error fetching the mean for table {self.table_name} at column {column_name}: {e}")

            print("Calculating mean manually using data...")

            avg = col_data.mean()
            print(f"Updating mean value for column {column_name} in data profile")

        return avg


    def calculate_median(self, column_name):
        col_data = self.get_col_data(column_name, 'median')

        try:
            median = self.query_summary_stat_from_main_df('MEDIAN', column_name)
        except Exception as e:
            print(f"Error fetching the median for table {self.table_name} at column {column_name}: {e}")

            print("Calculating median manually using data...")

            median = col_data.median()

            print(f"Updating median value for column {column_name} in data profile")

        return median


    def calculate_max(self, column_name):
        col_data = self.get_col_data(column_name, 'max')
        try:
            maximum = self.query_summary_stat_from_main_df('MAX', column_name)
        except Exception as e:
            print(f"Error fetching the maximum for table {self.table_name} at column {column_name}: {e}")

            print("Calculating maximum manually using data...")

            maximum = col_data.max()

            print(f"Updating maximum value for column {column_name} in data profile")

        return maximum

    def calculate_min(self, column_name):

        col_data = self.get_col_data(column_name, 'min')
        try:
            minimum = self.query_summary_stat_from_main_df('MIN', column_name)
        except Exception as e:
            print(f"Error fetching the minimum for table {self.table_name} at column {column_name}: {e}")

            print("Calculating minimum manually using data...")

            minimum = col_data.min()

            print(f"Updating minimum value for column {column_name} in data profile")

        return minimum

    def calculate_num_categories(self, column_name):
        col_data = self.get_col_data(column_name, 'n_categories')
        try:
            query = f'SELECT COUNT(DISTINCT "{column_name}") FROM "{self.table_name}"'
            n_categories = fetch_sql(query, True, self.engine)
        except Exception as e:
            print(f"Error fetching the n_categories for table {self.table_name} at column {column_name}: {e}")

            print("Calculating n_categories manually using data...")

            n_categories = col_data.nunique()

            print(f"Updating n_categories value for column {column_name} in data profile")

        return n_categories


    def calculate_mode(self, column_name):
        print("Calculating mode manually using data...")
        col_data = self.get_col_data(column_name, 'mode')
        mode = col_data.mode()

        return mode

    # TODO: calculate some stats relating to the error df

















'''



# Gets the data attributes that are given to LLM
def get_data_attributes(tablename):
    from app import engine

    # TODO: already a similar loop in data_attribute_summary_integration.py
    # line 85, maybe somehow combine these? Idk if it makes sense to put ai
    # related things in there though?
    # build_attribute_distributions() very similar; combine into same function in future
    main_rows = fetch_sql(f'SELECT * FROM "{tablename}"', False, engine)

    main_cols = fetch_sql(
        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{tablename}' ORDER BY ordinal_position",
        False, engine)

    main_df = pd.DataFrame(main_rows, columns=[row[0] for row in main_cols] if main_cols else None)

    data_attributes = {}
    for col in main_df.columns:
        data_attributes[col] = get_col_attributes(main_df, col)

    return data_attributes

def save_data_attributes(tablename, json_path="data_attributes.json"):
    data_attributes = get_data_attributes(tablename)
    with open(f'app/ai_utils/{json_path}', 'w') as outfile:
        json.dump(data_attributes, outfile)

# TODO: maybe use scipy so it's more efficient?
def get_median_absolute_deviation(col_data, median):
    median_residuals = col_data - median
    abs_median_residuals = np.abs(median_residuals)
    mad = int(np.median(abs_median_residuals))
    return mad

# Returns a list: [lower_fence, upper_fence]
def get_tukeys_fences(col_data, iqr):
    q1 = np.percentile(col_data, 25)
    q3 = np.percentile(col_data, 75)
    lower_fence = (q1 - 1.5 * (iqr)).item()
    upper_fence = (q3 + 1.5 * (iqr)).item()

    return (lower_fence, upper_fence)

def get_col_attributes(df, col):
    col_attributes = {}
    col_data = df[col]

    col_attributes['data_type'] = str(col_data.dtype)
    col_attributes['num_na'] = int(col_data.isnull().sum())
    col_attributes['count'] = int(col_data.count())

    if is_categorical(col_data):
        col_data = df[col].fillna('N/A')
        col_attributes['num_unique'] = int(col_data.nunique())
        # TODO: maybe do proportion instead?
        col_attributes['category_count'] = col_data.value_counts().to_dict()
    else:
        col_data = pd.to_numeric(df[col], errors='coerce').dropna()
        col_attributes['mean'] = col_data.mean().item()
        col_attributes['median'] = col_data.median().item()
        col_attributes['min'] = col_data.min().item()
        col_attributes['max'] = col_data.max().item()
        # ik a lot of these do the same things but idk which one to choose
        # --- measures of dispersion
        col_attributes['var'] = col_data.var().item()
        col_attributes['iqr'] = (col_data.quantile(0.75) - col_data.quantile(0.25)).item()
        col_attributes['std'] = col_data.std().item()
        col_attributes['skew'] = col_data.skew().item()
        col_attributes['median_absolute_deviation'] = get_median_absolute_deviation(col_data, col_attributes['median'])
        # -------

        # List where first val is lower fence, second is upper fence
        # Can't be tuple bc jsons don't support tuples
        col_attributes['tukeys_fence'] = get_tukeys_fences(col_data, col_attributes['iqr'])
    return col_attributes




'''