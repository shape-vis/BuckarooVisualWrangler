# Buckaroo Visual Data Wrangler

## Overview
Buckaroo Visual Wrangler is a data visualization tool that helps users inspect,
explain, and repair data-quality problems. The current application combines:

- adaptive column profiling with confidence intervals and semantic safeguards;
- detector-guided visual inspection and provenance-aware repair;
- profiler-guided semantic-quality row grouping; and
- reproducible Pandas export of the selected repair path.

Users can choose from 3 provided datasets:
- StackOverflow survey (stackoverflow_db_uncleaned.csv)
- Chicago crimes (Crimes_-_One_year_prior_to_present_20250421.csv)
- Student loan complaints (complaints-2025-04-21_17_31.csv)

 The user may explore their data using various visualization styles, such as heatmaps, scatterplots, or histograms. The user may select data by clicking on the plots and applying various wrangling techniques. After performing the desired wrangling actions, the user may export a python script of those actions to run on the dataset outside of the tool.

## Quick Start (VLDB Demo Version)

If you want to see an early version of buckaroo (without going through any set up), you can try out an in-memory client-only version [here](https://shape-vis.github.io/BuckarooVisualWrangler/). This is the version that was documented in our [VLDB2025 demo](https://arxiv.org/abs/2507.16073) paper and has some slight differences from the current version.

## Local Development

Prerequisites: Python 3.12, Node.js/npm, and Docker Desktop (or another
PostgreSQL 15 installation).

The Compose file starts PostgreSQL only. Run the Flask backend and Vite
frontend in separate terminals:

```powershell
# Terminal 1: database
docker compose up -d db

# Terminal 2: backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python start.py

# Terminal 3: frontend
cd ui
npm install
npm run dev
```

The backend listens on `http://127.0.0.1:5001`; Vite normally serves
`http://127.0.0.1:5173` and proxies `/api` calls to Flask.

Create the ignored file `app/database.json` for the Docker database:

```json
{
  "host": "localhost",
  "port": 5433,
  "user": "postgres",
  "password": "password",
  "db_name": "buckaroo_db"
}
```

Equivalent `BUCKAROO_DB_*` environment variables override this file. See
[the development guide](docs/DEVELOPMENT.md) for tests and subsystem-specific
change checklists.

## Engineering Documentation

- [System architecture](docs/ARCHITECTURE.md)
- [Development and verification](docs/DEVELOPMENT.md)
- [Merge-request stack](docs/MERGE_REQUESTS.md)
- [Clustering research record](docs/clustering/README.md)
- [Experiment entrypoints](experiments/README.md)

## Dev Notes - last update: August 15, 2026

There is a doc called DEVNOTES.md which can be helpful to understand the arch of the app, and how things flow. This isn't comprehensive, but explains a lot. Definitely worth a skim at least when getting into the codebase. If other developers on Buckaroo change any of the core functionality in ``main``, please update this doc so that future students or others doing development on Buckaroo can continue to reference the DEVNOTES.md in the future :). 



## Improvements Available: 
- Integrate refactor-detector-port into main without breaking functionality in main
- Make dirty rows table infinitely scrollable (right now it just shows the top 10 rows, but want it to scroll to show the next 10 top rows and so on)
- The tool currently bins numerical values, however, it does not bin string values. Thus, any strings like dates, unique IDs etc. will all receive their own tick mark on the axis, resulting in a crowded and often unreadable plot. Future work on this project should handle dates in a more sophisticated way, such as binning by month or year. We discussed even binning all clean data into one bin and then leaving any data with errors unbinned so it can easily be spotted. Could also select a subset of the clean data to show and then keep all the dirty data to repair. Could also bin by error type.
- Make dirty row table headers clickable to sort by. So if a user clicks on "Age" for example, the table will show the top 10 rows with an error in the Age column.
- Continue validating semantic grouping usefulness with blinded human ratings.

