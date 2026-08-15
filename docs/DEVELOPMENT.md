# Development and Verification

## Local services

Buckaroo uses PostgreSQL, a Flask backend, and a Vite/React frontend. The
repository's Docker configuration is the preferred way to obtain a consistent
database and backend environment; the frontend can also run directly with npm.

```powershell
docker compose up --build
cd ui
npm install
npm run dev
```

The Vite development URL is normally `http://127.0.0.1:5173/`. Database
credentials for a non-Docker backend belong in `app/database.json`, which is
ignored by Git.

## Verification commands

Run focused unit tests before a full suite when changing one subsystem:

```powershell
python -m pytest -q tests/unit/test_dataset_profile_shape.py
python -m pytest -q tests/unit/test_multi_view_grouping.py
python -m pytest -q tests/unit
cd ui
npm run build
npm run lint
```

SQL integration tests require PostgreSQL and their test database configuration:

```powershell
python -m pytest -q tests/sql
```

## Adding or changing a profile role

1. Add the classification rule and candidate evidence in the profiler.
2. Map the role family and display label in
   `app/server_utils/data_attribute_summary_integration.py`.
3. Decide whether grouping should exclude, transform, or tokenize the role in
   `app/server_utils/multi_view_grouping.py`.
4. Add a focused classifier test and a UI/API formatting test.
5. Rerun sampling and ablation experiments only after unit behavior is frozen.

Do not create a data warning merely because a field is geographic, temporal, or
high-cardinality. Use review reasons for valid-but-sensitive semantics.

## Adding a grouping representation

1. Gate eligibility with profiler roles, not dataset-specific column names.
2. Preserve source-column identity in feature names.
3. Normalize the block before combining it with other evidence families.
4. Make randomness deterministic and report the seed.
5. Return both supporting and contradictory evidence.
6. Add a test using unfamiliar column names to guard against benchmark
   overfitting.

## Experiment hygiene

Canonical scripts live directly in `experiments/`; outputs should be written to
`outputs/` or an `*_outputs` directory. Commit source, protocols, frozen schema,
and small fixtures. Do not commit downloaded public datasets, human-label
workbooks, model caches, generated presentations, screenshots, or result dumps.

Every reported experiment should record dataset ID/hash, sample size, random
seed, iteration, profiler/grouping version, runtime boundary, and metric
definition. See `experiments/README.md` and
`docs/clustering/REPRODUCIBILITY_PROTOCOL.md`.
