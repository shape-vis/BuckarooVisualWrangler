

def remove_data(df,ids):
    """
    Takes the df passed in, and removes the ids from it, then re-runs the detectors on the entire df
    :param df:
    :param ids:
    :return:
    """
    wrangled_df = df.copy()
    indices_to_drop = wrangled_df[wrangled_df["ID"].isin(ids)].index
    wrangled_df.drop(indices_to_drop, inplace=True)
    return wrangled_df
