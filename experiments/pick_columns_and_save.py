import pandas as pd

src = 'provided_datasets/(original)crimes___one_year_prior_to_present_20250421.csv'
dst = 'provided_datasets/crimes___one_year_prior_to_present_20250421.csv'

# 1) load, 2) sanitize column names, 3) drop unwanted columns, 4) save
df = (
    pd.read_csv(src)
      .rename(columns=lambda c: c.strip().lower())                # strip & lowercase
      .drop(columns=['case#', 'date  of occurrence', 'block',     # drop
                     'location', 'fbi cd', 'location description'])
)

df.to_csv(dst, index=False)

'crimes___one_year_prior_to_present_20250421'