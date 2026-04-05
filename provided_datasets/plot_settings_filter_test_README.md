`plot_settings_filter_test.csv` is a small 100-row dataset meant for validating Plot Settings behavior.

What it is designed to show:

- `group`
  This is the rarity-test column.
  The frequencies are exact:
  `common` = 69%
  `preset15` = 15%
  `preset10` = 10%
  `preset05` = 5%
  `preset01` = 1%

  That makes it easy to sanity-check the rarity slider:
  - `1%` should surface only `preset01`
  - `5%` should include `preset05` and `preset01`
  - `10%` should include `preset10`, `preset05`, and `preset01`
  - `15%` should include `preset15`, `preset10`, `preset05`, and `preset01`

- `score_main`
  Primary numeric column for anomaly-method testing.
  It has:
  - a tight baseline cluster around `48-52`
  - a mild high cluster around `54-58`
  - a stronger high cluster around `63-66`
  - a rarer higher cluster around `82-84`
  - one extreme point at `150`

- `score_probe`
  Secondary numeric column with a similar stepped pattern.
  It is useful if one anomaly method looks too similar on `score_main`.

- `note`
  Simple text labels that make it easier to inspect rows in the Top Errors table.

Suggested quick checks:

1. Load the dataset and keep anomaly methods at `Z-Score`, rarity at `5%`.
2. Change rarity to `1%`, `10%`, and `15%` and watch whether the summaries and top rows react to the exact category frequencies above.
3. Toggle `Z-Score`, `MAD`, and `IQR` while looking at `score_main` and `score_probe`.
