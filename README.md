# Buckaroo Visual Data Wrangler

## Overview
Buckaroo Visual Wrangler is a data visualization tool that enables users to visually detect errors in their data and apply data wranglers to clean the dataset. Users can choose from 3 provided datasets or upload their own. The user can also provide their own error detector and data wrangler functions to apply to the data. The user may explore their data using various visualization styles, such as heatmaps, scatterplots, or histograms. The user may select data by clicking on the plots and applying various wrangling techniques. After performing the desired wrangling actions, the user may export a python script of those actions to run on the dataset outside of the tool.

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
Additionally, within each case, there are two conditions, the data is grouped by a group by attribute, or it is not. As a result, the view code contains a lot of repetition to handle all these cases individually.

### Controller
The controller contains functions to handle all user interaction with the UI, such as data selection, clicking buttons, and selecting attributes. After each user action, the controller will apply the action and then call the view to re-render with the new data or information. The controller is the first object created and contains references to both the view and model.

### Script
The script handles the user dataset selection or file upload. Once it gets the dataset, it adds an ID column in the first index, which is used throughout the code to identify rows in selection, wrangling, etc. If an ID column already exists, it uses that. **Importantly, the script selects only the first 200 rows from the uploaded dataset.** This was a design choice in implementation to speed up the rendering time. If this is changed, the exportPythonScript function will need to be updated as well, since it selects only the first 200 rows as well.

### Index
index.html is the home page where the user is prompted to select or upload a dataset.

### Other HTML
data_cleaning_vis_tool.html contains all the elements shown in the browser after the user picks a dataset.

### styles.css
styles.css contains all styling for the html.

## Future Work
The tool currently bins numerical values, however, it does not bin string values. Thus, any strings like dates, unique IDs, etc. will all receive their own tick mark on the axis, resulting in a crowded and often unreadable plot. Future work on this project should handle dates in a more sophisticated way, such as binning by month or year. Selection of points on the scatterplot is not fully implemented. Future work should attach brushing to the scatterplots to allow users to select a region of points to wrangle.



