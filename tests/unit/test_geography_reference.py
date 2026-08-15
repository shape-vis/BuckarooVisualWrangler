import pandas as pd

from app.server_utils.geography_reference import (
    city_name_eligible_columns,
    geography_name_eligible_columns,
)


def profile(role):
    return {"role": role}


def fake_resolver_factory(known):
    """A deterministic, offline stand-in for country_centroid.

    known maps value -> (lat, lon); anything else resolves to None, matching
    the real function's behavior for an unrecognized/unresolvable name.
    """
    def resolver(value):
        return known.get(str(value).strip())
    return resolver


def test_geography_name_eligible_columns_requires_role_and_full_resolution():
    frame = pd.DataFrame({
        "country": ["France", "Germany", "Japan", "France"] * 5,
        "city": ["Paris", "Springfield", "Springfield", "Paris"] * 5,
        "product": ["Widget A", "Widget B", "Widget C", "Widget A"] * 5,
    })
    profile_map = {
        "country": profile("location_name"),
        "city": profile("location_name"),
        "product": profile("categorical"),
    }
    resolver = fake_resolver_factory({
        "France": (48.85, 2.35),
        "Germany": (52.52, 13.41),
        "Japan": (35.68, 139.65),
        # "Paris"/"Springfield" deliberately unresolved -- city-level matching
        # is out of scope for this pass (see geography_reference.py docstring).
    })

    eligible = geography_name_eligible_columns(
        ["country", "city", "product"], frame, profile_map, resolver=resolver,
    )

    # Role gate: "product" is plain categorical, never eligible regardless of
    # whether its values happen to resolve.
    assert "product" not in eligible
    # Every distinct value resolves -> eligible.
    assert "country" in eligible
    # One resolver miss ("Paris"/"Springfield" not in the fake known set)
    # disqualifies the whole column -- same conservative, no-partial-credit
    # bar as ordinal_eligible_columns.
    assert "city" not in eligible


def test_geography_name_eligible_columns_rejects_single_value_and_no_variation():
    frame = pd.DataFrame({"country": ["France"] * 10})
    profile_map = {"country": profile("location_name")}
    resolver = fake_resolver_factory({"France": (48.85, 2.35)})

    # Only one distinct value -- no variation to cluster on, same floor as
    # every other eligibility gate in this codebase.
    assert geography_name_eligible_columns(["country"], frame, profile_map, resolver=resolver) == []


def fake_city_resolver_factory(known):
    """A deterministic, offline stand-in for city_centroid.

    known maps (value, country_hint) -> (lat, lon); anything else resolves
    to None, matching the real function's behavior for a city name with no
    matching candidate.
    """
    def resolver(value, country_hint=None):
        return known.get((str(value).strip(), country_hint))
    return resolver


def test_city_centroid_prefers_country_hint_over_population(monkeypatch):
    from app.server_utils import geography_reference as geo_ref

    # Two real "Springfield"s: a small one in a country that resolves cleanly
    # via pycountry (no geonamescache needed), and a much more populous one
    # in another country -- if population-based tie-breaking were used
    # instead of the hint, the more populous one would win.
    monkeypatch.setitem(
        geo_ref._reference_data, "name_to_cities",
        {
            "springfield": [
                {"country_code": "DE", "coordinate": (50.0, 8.0), "population": 500},
                {"country_code": "US", "coordinate": (39.8, -89.6), "population": 500_000},
            ],
        },
    )
    geo_ref._city_candidates_cache.clear()

    hinted = geo_ref.city_centroid("Springfield", country_hint="Germany")
    assert hinted == (50.0, 8.0)


def test_city_centroid_falls_back_to_population_without_a_matching_hint(monkeypatch):
    from app.server_utils import geography_reference as geo_ref

    monkeypatch.setitem(
        geo_ref._reference_data, "name_to_cities",
        {
            "springfield": [
                {"country_code": "DE", "coordinate": (50.0, 8.0), "population": 500},
                {"country_code": "US", "coordinate": (39.8, -89.6), "population": 500_000},
            ],
        },
    )
    geo_ref._city_candidates_cache.clear()

    # No hint at all -- population-as-last-resort picks the bigger city.
    assert geo_ref.city_centroid("Springfield") == (39.8, -89.6)

    geo_ref._city_candidates_cache.clear()
    # A hint that doesn't match any candidate (e.g. a data-entry inconsistency)
    # falls through to the same population tie-break rather than failing.
    assert geo_ref.city_centroid("Springfield", country_hint="Japan") == (39.8, -89.6)


def test_city_name_eligible_columns_requires_role_and_full_row_resolution():
    frame = pd.DataFrame({
        "city": ["Paris", "Berlin", "Paris", "Berlin"] * 3,
        "country": ["France", "Germany", "France", "Germany"] * 3,
        "product": ["Widget A", "Widget B", "Widget A", "Widget B"] * 3,
    })
    profile_map = {
        "city": profile("location_name"),
        "country": profile("location_name"),
        "product": profile("categorical"),
    }
    resolver = fake_city_resolver_factory({
        ("Paris", "France"): (48.85, 2.35),
        ("Berlin", "Germany"): (52.52, 13.41),
    })

    eligible = city_name_eligible_columns(
        ["city", "product"], frame, profile_map,
        context_column="country", resolver=resolver,
    )

    assert "city" in eligible
    assert "product" not in eligible


def test_city_name_eligible_columns_rejects_one_unresolvable_value():
    frame = pd.DataFrame({
        "city": ["Paris", "Atlantis", "Paris", "Atlantis"] * 3,
        "country": ["France", "Nowhere", "France", "Nowhere"] * 3,
    })
    profile_map = {"city": profile("location_name"), "country": profile("location_name")}
    resolver = fake_city_resolver_factory({
        ("Paris", "France"): (48.85, 2.35),
        # "Atlantis"/"Nowhere" deliberately absent -- one unresolvable value
        # disqualifies the whole column, same bar as every other eligibility
        # gate in this codebase.
    })

    assert city_name_eligible_columns(
        ["city"], frame, profile_map, context_column="country", resolver=resolver,
    ) == []
