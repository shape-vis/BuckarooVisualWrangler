"""Static, offline country-name-to-coordinate reference for geography distance.

Rosen's own suggestion, and the concrete/bounded fix named in
docs/clustering/RANKING_AND_SIMILARITY_POSITION.md Sec 2.3: Buckaroo already
computes real spherical distance when a table has explicit latitude/longitude
columns (see build_geography_matrix in multi_view_grouping.py). The gap is
location *names* -- "France", "Country=India" -- with no paired coordinate
column, which fall back to exact-match tokens: "India" is exactly as "far"
from "Pakistan" as it is from "Australia".

This module resolves a country-name string to its capital city's coordinates
using two small, static, offline reference libraries -- no network calls at
request time, no per-dataset hand-tuning:
- pycountry: robust name/alias resolution (official names, common names,
  typo-tolerant fuzzy search), sourced from ISO 3166, not hand-curated here.
- geonamescache: offline country + city data (including each country's
  capital and that capital's coordinates).

City-level matching (city_centroid below) resolves those name collisions in
two stages, cheapest and most reliable first:
1. Context: if a companion country/region value for the same row is
   available, narrow candidates to that country before picking one.
2. Population: only when context is absent, or doesn't match any candidate
   for that city name, fall back to the most populous candidate -- a
   deliberately last-resort tie-break, since population correlates with
   "more likely to be the intended city" but is not itself evidence about
   the row.
"""

from __future__ import annotations

import unicodedata
from typing import Any

# Role gate: only country-level location roles are eligible. City/region-name
# roles are out of scope for this first pass (see module docstring).
GEOGRAPHY_NAME_ELIGIBLE_ROLES = {"location_name", "country_code"}

# City-name matching shares the same "location_name" role as country-name
# matching (the profiler doesn't distinguish "city" from "country" by name
# alone -- see geography_kind() in profile_dataset_shape.py). A column only
# reaches city-level matching after failing the (stricter, tried-first)
# country-level gate above -- see build_geography_matrix in
# multi_view_grouping.py, which tries country_centroid before city_centroid.
CITY_NAME_ELIGIBLE_ROLES = {"location_name"}

_country_centroid_cache: dict[str, tuple[float, float] | None] = {}
_reference_data: dict[str, Any] = {}


def _fold(text: str) -> str:
    """Strip accents/diacritics and lowercase, for robust name matching."""
    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(char for char in normalized if not unicodedata.combining(char)).strip().lower()


def _load_reference_data() -> dict[str, Any]:
    """Lazily build the capital-city coordinate table, once per process.

    Not imported at module load time: keeps the (lightweight, but still
    non-trivial) geonamescache/pycountry dependency out of any run that
    never uses geography-name matching, and out of the test suite entirely
    (tests inject a fake resolver instead of loading the real reference data).
    """
    if _reference_data:
        return _reference_data

    import geonamescache

    cache = geonamescache.GeonamesCache()
    countries = cache.get_countries()
    cities = cache.get_cities()

    # geonamescache's own country names cover common/traditional forms that
    # can diverge from pycountry's ISO-official names after a country renames
    # itself in the ISO 3166 list (e.g. ISO now lists "Turkey" as "Turkiye",
    # but "Turkey" -- what virtually every real dataset actually contains --
    # is still geonamescache's canonical name and pycountry's fuzzy search
    # does not reliably bridge that specific gap). Checked as a second exact-
    # match layer before falling back to fuzzy matching.
    name_to_alpha2 = {_fold(country["name"]): code for code, country in countries.items()}

    capital_lookup: dict[tuple[str, str], tuple[float, float]] = {}
    for city in cities.values():
        country_code = city["countrycode"]
        coordinate = (float(city["latitude"]), float(city["longitude"]))
        capital_lookup.setdefault((country_code, _fold(city["name"])), coordinate)
        for alternate_name in city.get("alternatenames", []):
            capital_lookup.setdefault((country_code, _fold(alternate_name)), coordinate)

    alpha2_to_centroid: dict[str, tuple[float, float]] = {}
    for code, country in countries.items():
        capital = _fold(country.get("capital") or "")
        coordinate = capital_lookup.get((code, capital))
        if coordinate is not None:
            alpha2_to_centroid[code] = coordinate

    _reference_data["alpha2_to_centroid"] = alpha2_to_centroid
    _reference_data["name_to_alpha2"] = name_to_alpha2
    return _reference_data


def resolve_country_alpha2(value: str) -> str | None:
    """Best-effort ISO alpha-2 code for a country-name string, or None.

    Uses pycountry's exact-match lookups first (name, official_name,
    common_name, alpha_2/alpha_3 code), then its typo-tolerant fuzzy search
    as a fallback -- covers common real-world variants ("Russia" vs the
    official "Russian Federation", "South Korea" vs "Korea, Republic of")
    without any dataset-specific hand-coded alias list.
    """
    import pycountry

    text = str(value).strip()
    if not text:
        return None

    exact = (
        pycountry.countries.get(name=text)
        or pycountry.countries.get(official_name=text)
        or pycountry.countries.get(common_name=text)
        or (pycountry.countries.get(alpha_2=text.upper()) if len(text) == 2 else None)
        or (pycountry.countries.get(alpha_3=text.upper()) if len(text) == 3 else None)
    )
    if exact is not None:
        return exact.alpha_2

    by_common_name = _load_reference_data()["name_to_alpha2"].get(_fold(text))
    if by_common_name is not None:
        return by_common_name

    try:
        fuzzy = pycountry.countries.search_fuzzy(text)
    except LookupError:
        return None
    return fuzzy[0].alpha_2 if fuzzy else None


def country_centroid(value: Any) -> tuple[float, float] | None:
    """A representative (latitude, longitude) for a country-name string.

    The capital city's coordinates, not a geometric area centroid -- a
    standard, well-defined choice (every country has exactly one capital)
    that avoids the ambiguity of computing a true area centroid for
    irregularly-shaped or archipelagic countries. Cached per distinct
    string value, since this is called once per unique value in a column
    (see semantic_embeddings.embed_unique_values for the same pattern).
    """
    text = str(value).strip()
    if not text:
        return None
    if text in _country_centroid_cache:
        return _country_centroid_cache[text]

    alpha2 = resolve_country_alpha2(text)
    centroid = _load_reference_data()["alpha2_to_centroid"].get(alpha2) if alpha2 else None
    _country_centroid_cache[text] = centroid
    return centroid


_city_candidates_cache: dict[str, list[dict[str, Any]]] = {}


def _load_city_candidate_index() -> dict[str, list[dict[str, Any]]]:
    """Lazily build folded-city-name -> list of candidate cities.

    Each candidate carries its country alpha-2 code, coordinate, and
    population -- everything city_centroid needs for context-first,
    population-as-last-resort disambiguation. Built from the same
    geonamescache city table _load_reference_data() already loads, so a
    process that uses both country and city matching only pays the load
    cost once.
    """
    if _reference_data.get("name_to_cities") is not None:
        return _reference_data["name_to_cities"]

    import geonamescache

    cache = geonamescache.GeonamesCache()
    cities = cache.get_cities()

    name_to_cities: dict[str, list[dict[str, Any]]] = {}
    for city in cities.values():
        candidate = {
            "country_code": city["countrycode"],
            "coordinate": (float(city["latitude"]), float(city["longitude"])),
            "population": int(city.get("population") or 0),
        }
        names = {city["name"], *city.get("alternatenames", [])}
        for name in names:
            name_to_cities.setdefault(_fold(name), []).append(candidate)

    _reference_data["name_to_cities"] = name_to_cities
    return name_to_cities


def city_centroid(value: Any, country_hint: Any = None) -> tuple[float, float] | None:
    """A representative (latitude, longitude) for a city-name string.

    Many city names collide across countries ("Springfield", "San Jose"),
    so a bare name lookup is ambiguous. Disambiguates in two stages:
    1. Context: if country_hint (a companion country/region value from the
       same row) resolves to a known country and narrows the candidates,
       use that.
    2. Population: only when country_hint is absent, unresolvable, or
       doesn't match any candidate for this city name, fall back to the
       most populous candidate -- a deliberate last resort, since
       population is a proxy for "more likely intended", not row evidence.

    Cached per (value, country_hint) pair, mirroring country_centroid's
    per-value cache.
    """
    text = str(value).strip()
    if not text:
        return None

    cache_key = f"{text}␟{country_hint if country_hint is not None else ''}"
    if cache_key in _city_candidates_cache:
        cached = _city_candidates_cache[cache_key]
        return cached[0]["coordinate"] if cached else None

    candidates = _load_city_candidate_index().get(_fold(text), [])
    if not candidates:
        _city_candidates_cache[cache_key] = []
        return None

    resolved = candidates
    if len(candidates) > 1 and country_hint is not None and str(country_hint).strip():
        alpha2 = resolve_country_alpha2(str(country_hint))
        if alpha2:
            narrowed = [c for c in candidates if c["country_code"] == alpha2]
            if narrowed:
                resolved = narrowed

    best = max(resolved, key=lambda c: c["population"])
    _city_candidates_cache[cache_key] = [best]
    return best["coordinate"]


def geography_name_eligible_columns(
    columns: list[str],
    frame,
    profile_map: dict[str, dict],
    *,
    resolver=country_centroid,
) -> list[str]:
    """Which location-name columns should use real geographic distance
    instead of exact-match equality.

    Two gates:
    1. Role gate: only country-level location roles (see
       GEOGRAPHY_NAME_ELIGIBLE_ROLES) -- city/region names are out of scope
       for this first pass.
    2. Every distinct present value must resolve to a country centroid.
       Same deliberately strict, no-partial-credit bar as
       ordinal_eligible_columns: one unresolvable value (a genuinely
       unrecognized name, a data-entry error) disqualifies the whole column
       rather than silently dropping it from the representation.

    resolver is injectable so tests never need the real reference data
    (offline, fast, no geonamescache/pycountry import in the test suite).
    """
    eligible = []
    for column in columns:
        if profile_map.get(column, {}).get("role") not in GEOGRAPHY_NAME_ELIGIBLE_ROLES:
            continue
        series = frame[column]
        from app.server_utils import semantic_grouping as sg

        distinct_values = series[~series.map(sg.is_missing_value)].map(sg.format_group_value).unique()
        if len(distinct_values) < 2:
            continue
        resolved = [resolver(value) for value in distinct_values]
        if any(value is None for value in resolved):
            continue
        if len(set(resolved)) < 2:
            continue
        eligible.append(column)
    return eligible


def city_name_eligible_columns(
    columns: list[str],
    frame,
    profile_map: dict[str, dict],
    *,
    context_column: str | None = None,
    resolver=city_centroid,
) -> list[str]:
    """Which city-name columns should use real geographic distance.

    Row-level, not column-level, unlike geography_name_eligible_columns:
    city_centroid's context_hint means the same city string can resolve
    differently depending on the country/region value paired with it in
    that row, so eligibility must be checked per row rather than per
    distinct value.

    Two gates, same strictness precedent as the country-level pass:
    1. Role gate: only CITY_NAME_ELIGIBLE_ROLES. Callers should already
       have removed columns that cleared the (tried-first) country-level
       gate -- see build_geography_matrix.
    2. Every present value, resolved with whatever context_column value
       accompanies it in that row, must resolve to a coordinate. One
       genuinely unresolvable city name disqualifies the whole column
       rather than silently dropping it.

    context_column is the companion country/region column (if any) found
    elsewhere in the frame -- see build_geography_matrix for how it's
    chosen. resolver is injectable so tests never need the real reference
    data.
    """
    from app.server_utils import semantic_grouping as sg

    context_values = frame[context_column] if context_column is not None else None

    eligible = []
    for column in columns:
        if profile_map.get(column, {}).get("role") not in CITY_NAME_ELIGIBLE_ROLES:
            continue
        series = frame[column]
        present_mask = ~series.map(sg.is_missing_value)
        if present_mask.sum() < 2:
            continue

        resolved_coordinates = []
        for index in series[present_mask].index:
            value = sg.format_group_value(series[index])
            hint = None
            if context_values is not None and not sg.is_missing_value(context_values[index]):
                hint = sg.format_group_value(context_values[index])
            resolved_coordinates.append(resolver(value, hint))

        if any(coordinate is None for coordinate in resolved_coordinates):
            continue
        if len(set(resolved_coordinates)) < 2:
            continue
        eligible.append(column)
    return eligible
