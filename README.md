# Buckaroo Visual Data Wrangler

## Overview
Buckaroo Visual Wrangler is a data visualization tool that enables users to visually detect errors in their data and apply data wranglers to clean the dataset. Users can choose from 3 provided datasets:
- StackOverflow survey (stackoverflow_db_uncleaned.csv)
- Chicago crimes (Crimes_-_One_year_prior_to_present_20250421.csv)
- Student loan complaints (complaints-2025-04-21_17_31.csv)

or upload their own. The user can also provide their own error detector and data wrangler functions to apply to the data. The user may explore their data using various visualization styles, such as heatmaps, scatterplots, or histograms. The user may select data by clicking on the plots and applying various wrangling techniques. After performing the desired wrangling actions, the user may export a python script of those actions to run on the dataset outside of the tool.

## Quick Start (VLDB Demo Version)

If you want to see an early version of buckaroo (without going through any set up), you can try out an in-memory client-only version [here](https://shape-vis.github.io/BuckarooVisualWrangler/). This is the version that was documented in our [VLDB2025 demo](https://arxiv.org/abs/2507.16073) paper and has some slight differences from the current version.

## How to run the code (how to start)
In Terminal, cd to the BuckarooVisualWrangler directory. Run this line: python -m http.server. The tool is now running locally on your machine, so open a browser and go to http://localhost:8000. The browser will first take you to the home page (index.html) and will prompt you to click on a dataset option or upload your own. Once you select an option, you will be redirected to the main page (data_cleaning_vis_tool.html) where all the widgets will pop up and a 3x3 matrix plotting the data. Now you can take several actions, such as:
- Select different attributes/columns to plot from the "Select Attributes 3/3" dropdown button
- Select an attribute to group by 
- Add a predicate to a column
- Explore the attribute summaries and re-order them by a different error type
- Explore the top 10 most dirty rows of data in the table
- Enable "Select data" and experiment clicking on various bars and bins in the plots
- Transform selected data by making a selection and exploring the preview plots to see what happens when a wrangling action is performed
- Export a python script of the actions you took

## How to start as an app with frontend,server,db
### Background info
- Use this setup the environment after cloning the repo
- requirements.txt lays out the project dependencies for flask (server) to talk with the db (postgresql)
### Setup venv
- Setup a venv python environment in the top-level dir
1. Install pyenv, install python
    `pyenv exec python3 -m venv .venv`
    
2. Start the venv:
    `source .venv/bin/activate`
    
3. Install the requirements:
    `pip install -r requirements.txt`
    

### To run flask server
-This runs the flask server in dev mode
    `flask run`

### download postgresql
- This is assuming you are using a Mac, and that you have HomeBrew installed, install this from home directory on your system (we are running the db locally during scaling dev)

    `brew install postgresql`   



## Organization of code (MVC)
The code is organized according to a Model-View-Controller Design.

### Model
The dataModel.js class contains all functionality for maintaining the dataset. Any preprocessing, filtering, or data transformations are called in this class. The other classes query the model for the current dataset. The model also runs the error detectors and wranglers, as well as tracks the actions the user takes on the dataset. The exported script is built in this class.

### View
The scatterplotMatrixView.js class contains all plotting functionality. It contains 4 methods for plotting the 4 types of plots: plotMatrix (plots histograms), drawHeatMap, drawScatterplot, and switchToLineChart. The view also draws other UI elements, such as the attribute summaries, dirty data table, and dataset configuration menus. The view also renders the preview plots in the Data Repair Toolkit. The view consists of a lot of repeated plotting code due to the data being both numeric and categorical. Within each plotting method, four cases are handled: 
- both x & y are numeric 
- x is categorical & y is numeric 
- x is numeric & y is categorical
- both x & y are categorical. 

Additionally, within each case, there are two conditions:
- the data is grouped by a group by attribute
- the data is not grouped

As a result, the view code contains a lot of repetition to handle all these cases individually.

### Controller
The controller contains functions to handle all user interaction with the UI, such as data selection, clicking buttons, and selecting attributes. After each user action, the controller will apply the action and then call the view to re-render with the new data or information. The controller is the first object created and contains references to both the view and model.

### Script
The script handles the user dataset selection or file upload. Once it gets the dataset, it adds an ID column in the first index, which is used throughout the code to identify rows in selection, wrangling, etc. If an ID column already exists, it uses that. **Importantly, the script selects only the first 200 rows from the uploaded dataset.** This was a design choice in implementation to speed up the rendering time. If this is changed, the exportPythonScript function will need to be updated as well, since it selects only the first 200 rows.

### Detectors
detectors.json contains error detector objects. Each object contains an ID, Name, and File path to a .js file that contains a function that will detect the error. All .js error decectors can be found in the detectors file. These error detectors are run after initialization of the controller in the script and build an error map that assigns an error type (if it exists) to each row in the dataset. This modularity of the detectors allows a user to add their own detectors to the project.

### Wranglers
wranglers.json contains data wranlger objects. Each object contains an ID, Name, and File path to a .js file that contains a function that will run the wrangler to handle the dirty data. all .js wranglers can be found in the wranglers file. These wranglers are loaded in with the detectors and are called when the user selects data and clicks a button to repair the data (i.e. remove data, impute an average for a data value). Again, modularity allows a user to add their own wrangling functions to the project.

### Index
index.html is the home page where the user is prompted to select or upload a dataset.

### Other HTML
data_cleaning_vis_tool.html contains all the elements shown in the browser after the user picks a dataset.

### styles.css
styles.css contains all styling for the html.

## Future Work
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

## Troubleshooting
Sometimes I would get errors that would popup inconsistently and don't exist in the code. Whenever this happens, I would just do a hard refresh (cdm-shift-R on Mac) and the error would resolve. I'm sure if you look into it more, there is a more permanent fix, but I would just always do a hard refresh and it would resolve. If the plotting matrix isn't showing up, open the console in dev tools and see if there's an error. Almost always, this is resolved by a hard refresh. Some examples of these random errors are:
- net::ERR_CONTENT_LENGTH_MISMATCH 200 (OK)
- Unexpected end of input (I'm not sure why this pops up because I would check and could never find missing curly braces, parantheses, etc.)
- Invalid or unexpected token

You can also try clearing the cache in your browser and this seemed to keep the errors away for longer.
