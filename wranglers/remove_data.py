

def remove_data(df,ids):
    """
    Takes the df passed in, and removes the ids from it, then re-runs the detectors on the entire df
    :param df:
    :param ids:
    :return:
    """
    wrangled_df = df.copy()
    print(wrangled_df)
    #convert the strings into numbers so that pandas can apply the mask easily
    for i in range(len(ids)):
        ids[i] = int(ids[i])
    indices_to_drop = wrangled_df[wrangled_df['ID'].isin(ids)].index
    wrangled_df.drop(indices_to_drop, inplace=True)
    print(wrangled_df)
    return wrangled_df
