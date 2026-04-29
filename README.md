# Buckaroo Visual Data Wrangler

## Overview
Buckaroo Visual Wrangler is a data visualization tool that enables users to visually detect errors in their data and apply data wranglers to clean the dataset. Users can choose from 3 provided datasets:
- StackOverflow survey (stackoverflow_db_uncleaned.csv)
- Chicago crimes (Crimes_-_One_year_prior_to_present_20250421.csv)
- Student loan complaints (complaints-2025-04-21_17_31.csv)

 The user may explore their data using various visualization styles, such as heatmaps, scatterplots, or histograms. The user may select data by clicking on the plots and applying various wrangling techniques. After performing the desired wrangling actions, the user may export a python script of those actions to run on the dataset outside of the tool.

## Quick Start (VLDB Demo Version)

If you want to see an early version of buckaroo (without going through any set up), you can try out an in-memory client-only version [here](https://shape-vis.github.io/BuckarooVisualWrangler/). This is the version that was documented in our [VLDB2025 demo](https://arxiv.org/abs/2507.16073) paper and has some slight differences from the current version.

## 2026 - How to Start
### ( very rudimentary - more needs to be added for specific postgres issues and OS variations)

- we are assuming you will have python3, and postgreSQL installed on your machine, if you do not then make sure to install those before doing the below steps

1. navigate to ``/app`` and create a new file called: ``database.json``
2. set up a user and db in postgres you will use for this app --- (this project requires a local installation of postgreSQL)
3. do ```./run.sh```, this will prompt the construction of your  ```database.json```
4. now you should have a .venv built for the project to run in, and a database.json created, if this didn't work you need to set up the parameters in database.json manually 
5. make sure you have npm installed and it's installed/accessible in the .venv
6. if your terminal does not have (.venv) at the start of it's name then, you need to active the .venv that was just created
7. run ```./start.py ``` in the venv to start the flask server 
8. open a new terminal, ```cd ui```
9. ```npm run dev``` in the to start the front-end

#### other startup notes:

1. A very efficient setup is to use Jetbrains Pycharm, and setup a compound debug config using a Javascript Debug config, npm config, and a Python config all in one so that you can do full-stack debugging.
2. Jetbrains Pycharm also allows for postgres integration so that you can see the tables and the state of the database while developing. 

## Dev Notes - last update: April 29, 2026

There is a doc called DEVNOTES.md which can be helpful to understand the arch of the app, and how things flow. This isn't comprehensive, but explains a lot. Definitely worth a skim at least when getting into the codebase. If other developers on Buckaroo change any of the core functionality in ``main``, please update this doc so that future students or others doing development on Buckaroo can continue to reference the DEVNOTES.md in the future :). 



## Improvements Available: 
- Integrate refactor-detector-port into main without breaking functionality in main
- Make dirty rows table infinitely scrollable (right now it just shows the top 10 rows, but want it to scroll to show the next 10 top rows and so on)
- The tool currently bins numerical values, however, it does not bin string values. Thus, any strings like dates, unique IDs etc. will all receive their own tick mark on the axis, resulting in a crowded and often unreadable plot. Future work on this project should handle dates in a more sophisticated way, such as binning by month or year. We discussed even binning all clean data into one bin and then leaving any data with errors unbinned so it can easily be spotted. Could also select a subset of the clean data to show and then keep all the dirty data to repair. Could also bin by error type.
- Make dirty row table headers clickable to sort by. So if a user clicks on "Age" for example, the table will show the top 10 rows with an error in the Age column.
- Python Script export non-existent - needs to be re-implemented

