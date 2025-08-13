# Buckaroo Visual Data Wrangler

## Overview
Buckaroo Visual Wrangler is a data visualization tool that enables users to visually detect errors in their data and apply data wranglers to clean the dataset. Users can choose from 3 provided datasets:
- StackOverflow survey (stackoverflow_db_uncleaned.csv)
- Chicago crimes (Crimes_-_One_year_prior_to_present_20250421.csv)
- Student loan complaints (complaints-2025-04-21_17_31.csv)

or upload their own. The user can also provide their own error detector and data wrangler functions to apply to the data. The user may explore their data using various visualization styles, such as heatmaps, scatterplots, or histograms. The user may select data by clicking on the plots and applying various wrangling techniques. After performing the desired wrangling actions, the user may export a python script of those actions to run on the dataset outside of the tool.

## How to run the code (how to start)

### Background info
- requirements.txt lays out the project dependencies for flask (server) to talk with the db (postgresql)

### Run the app (after cloning the repo)

1. chmod +x run.sh
2. ./run.sh
3. Answer the setup questions which will configure your db connection to the app - this assumes you have
    already installed postgresql on your machine. If you have not see: https://www.postgresql.org/, and then run this script again.
4. Open the url output in the console to use the app in browser 

## UG Student Dev Tip:
    If you are using an IDE, like Pycharm, use the debugger mode in the IDE to debug the view. To debug the server, 
    we recommend using Insomnia, https://insomnia.rest/, and writing endpoint tests to verify functionality of endpoints.
    Alternatively, you can also debug the view by using dev tools in a browser of your liking.

## Organization of the view code (MVC)
The view is organized according to a Model-View-Controller Design.
The overall structure consists of a main server in Flask, https://flask.palletsprojects.com/en/stable/,
which talks to the view and the database via endpoints. If you are a developer, see the developer videos, and the Dev Doc.

### Model (view)
The dataModel.js class contains functionality for maintaining the dataset in the view. Any preprocessing, filtering, or data transformations _CAN_ be called in this class, _BUT_ the state of the project is currently migrating as much
of this as possible to operate in the server/on the postgresql DB directly, see the status table in the Dev Doc of what features have been migrated already. The model _CAN_ also run the error detectors and wranglers, but these are not being used anymore, (they are run in the server) and should soon be deleted from the repo.
The exported script is built in this class, but needs work to integrate correctly with the full-stack version of the app.

The exportPythonScript function will need to be updated as well, since it selects only the first 200 rows (hardcoded).

### View (view)
The `scatterplotMatrixView.js` class governs the view. It interfaces with almost all files in `/js` 
as well as initiates the drawing and rendering of the plots and panels in `/visualizations`.

### Controller
The controller contains functions to handle all user interaction with the UI, such as data selection, clicking buttons, and selecting attributes. After each user action, the controller will apply the action and then call the view to re-render with the new data or information. The controller is the first object created and contains references to both the view and model.

### DataSelection.js
This handles the user dataset selection whether they choose to use a pre-selected dataset or file upload. 

### Detectors
detectors.json contains the old error detector objects. Now the detectors run at the beginning of app startup in the server
right after the user selects a dataset. These error detectors are run after initialization of the controller in the script and build an error map that assigns an error type (if it exists) to each row in the dataset. 
This modularity of the detectors allows a user to add their own detectors to the project.

The old detectors (javascript implementation), and the json file objects corresponding to them  
each contain an ID, Name, and File path to a .js file that contains a function that will detect the error. 
All old .js error detectors can be found in the detectors file. 


### Wranglers
wranglers.json contains the old data wrangler objects. 
Each object contains an ID, Name, and File path to a .js file that contains a function that will run the wrangler to handle the dirty data. all .js wranglers can be found in the wranglers file. 
These wranglers are loaded in with the detectors and are called when the user selects data and clicks a button to repair the data (i.e. remove data, impute an average for a data value). 
Again, modularity allows a user to add their own wrangling functions to the project.

Now these are also in the server, and can operate on the dataframe implementation, but not the database as of yet. In the 
buckaroo-sql branch, there is a hacky implementation of the project which runs detectors and wranglers on the DB directly.

### Index
index.html is the home page where the user is prompted to select or upload a dataset.

### Other HTML
data_cleaning_vis_tool.html contains all the elements shown in the browser after the user picks a dataset.

### styles.css
styles.css contains all styling for the html.

## Organization of the server
The server is organized into a few different groups of file types:
1. Route Files - these are the endpoints which handle user interactions with the UI, there is a file for dataframe endpoints, DB endpoints, wrangler endpoints, and generic endpoints
2. Service Helpers - backend logic needed to deliver on endpoint services throughout the app
3. Detectors dir - this is the group of detectors that currently run on the dataset upon app startup
4. Wranglers dir - this is the group of implemented wranglers which operate on the dataframe, which can be connected to the view for DF wrangling
5. Tests - this is the current test suite for the app
6. Data Management - contains files which format dataframe data into JSON formats the view can consume, and also has a state manager to support undo,redo, and to keep track of the data state during wrangles


## Future Work
List of small tasks to start with: 
- Make dirty rows table infinitely scrollable (right now it just shows the top 10 rows, but want it to scroll to show the next 10 top rows and so on)
- When switching between the 3 different chart types on a cell, the axis labels are redrawn every time, so the labels get darker and darker each time you switch the chart type. This should be a simple fix to remove any additions of labels to the plot when switching between chart views.

Below are some To Dos as discussed with the Professors as well as things I think will make Buckaroo better:
- The tool currently bins numerical values, however, it does not bin string values. Thus, any strings like dates, unique IDs etc. will all receive their own tick mark on the axis, resulting in a crowded and often unreadable plot. Future work on this project should handle dates in a more sophisticated way, such as binning by month or year. We discussed even binning all clean data into one bin and then leaving any data with errors unbinned so it can easily be spotted. Could also select a subset of the clean data to show and then keep all the dirty data to repair. Could also bin by error type. 
- Selection of points on the scatterplot is not fully implemented. Future work should attach brushing to the scatterplots to allow users to select a region of points to wrangle. There is already a handleBrush method in the controller to build off of.
- Make dirty row table headers clickable to sort by. So if a user clicks on "Age" for example, the table will show the top 10 rows with an error in the Age column.
- Python script is currently hard-coded to convert Javascript/Arquero data transformations into Python. Need to make this dynamic so it can include Python logic when new wranglers are added.

## Large Future Features to Start With
- Connect dataframe wrangle routes to the UI so wrangling on the front end can be done on the dataframes in the server
- Finish the chart of features found in the Dev Doc
- There is a large bug when you try to use other datasets besides StackOverflow, this would be a big first bug to fix
