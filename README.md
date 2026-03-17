# Buckaroo Visual Data Wrangler

## Overview
Buckaroo Visual Wrangler is a data visualization tool that enables users to visually detect errors in their data and apply data wranglers to clean the dataset. Users can choose from 3 provided datasets:
- StackOverflow survey (stackoverflow_db_uncleaned.csv)
- Chicago crimes (Crimes_-_One_year_prior_to_present_20250421.csv)
- Student loan complaints (complaints-2025-04-21_17_31.csv)

 The user may explore their data using various visualization styles, such as heatmaps, scatterplots, or histograms. The user may select data by clicking on the plots and applying various wrangling techniques. After performing the desired wrangling actions, the user may export a python script of those actions to run on the dataset outside of the tool.

## Quick Start (VLDB Demo Version)

If you want to see an early version of buckaroo (without going through any set up), you can try out an in-memory client-only version [here](https://shape-vis.github.io/BuckarooVisualWrangler/). This is the version that was documented in our [VLDB2025 demo](https://arxiv.org/abs/2507.16073) paper and has some slight differences from the current version.

## 2026 - How to Start - (to be added)


## Improvements Available: 

- Make dirty rows table infinitely scrollable (right now it just shows the top 10 rows, but want it to scroll to show the next 10 top rows and so on)
- The tool currently bins numerical values, however, it does not bin string values. Thus, any strings like dates, unique IDs etc. will all receive their own tick mark on the axis, resulting in a crowded and often unreadable plot. Future work on this project should handle dates in a more sophisticated way, such as binning by month or year. We discussed even binning all clean data into one bin and then leaving any data with errors unbinned so it can easily be spotted. Could also select a subset of the clean data to show and then keep all the dirty data to repair. Could also bin by error type.
- Make dirty row table headers clickable to sort by. So if a user clicks on "Age" for example, the table will show the top 10 rows with an error in the Age column.
- Python Script export non-existent - needs to be re-implemented

