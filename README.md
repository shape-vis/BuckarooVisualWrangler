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


## Future Work - OLD - Dated Spring '25
List of small tasks to start with: 
- Make dirty rows table infinitely scrollable (right now it just shows the top 10 rows, but want it to scroll to show the next 10 top rows and so on)
- There's a large gap between the top of the dirty rows table and the bottom of the matrix. It shows up on my laptop, but goes away when projecting on a screen. I wanted to get around to finding a consistent spacing for these containers. The styling for the dirty rows table is in styles.css (#dirty-rows-container)
- Add the error type to the tooltip on hover. If there is no error type, don't say anything, or say "Clean"/"No errors." Right now, tooltips just show the column names and count.
- When switching between the 3 different chart types on a cell, the axis labels are redrawn every time, so the labels get darker and darker each time you switch the chart type. This should be a simple fix to remove any additions of labels to the plot when switching between chart views.

Below are some To Dos as discussed with the Professors as well as things I think will make Buckaroo better:
- The tool currently bins numerical values, however, it does not bin string values. Thus, any strings like dates, unique IDs etc. will all receive their own tick mark on the axis, resulting in a crowded and often unreadable plot. Future work on this project should handle dates in a more sophisticated way, such as binning by month or year. We discussed even binning all clean data into one bin and then leaving any data with errors unbinned so it can easily be spotted. Could also select a subset of the clean data to show and then keep all the dirty data to repair. Could also bin by error type. 
- Selection of points on the scatterplot is not fully implemented. Future work should attach brushing to the scatterplots to allow users to select a region of points to wrangle. There is already a handleBrush method in the controller to build off of.
- Make dirty row table headers clickable to sort by. So if a user clicks on "Age" for example, the table will show the top 10 rows with an error in the Age column.
- Python script is currently hard-coded to convert Javascript/Arquero data transformations into Python. Need to make this dynamic so it can include Python logic when new wranglers are added.
- Eventually, we want to move the visualization logic into modules, just like the detectors and wranglers. This way the user can utilize visualizations that best work with their dataset.


