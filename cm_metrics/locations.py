"""Curated appliance locations with map coordinates (autocomplete suggestions)."""

from __future__ import annotations

from typing import Any


def _loc(
    key: str,
    continent: str,
    country: str,
    region: str,
    lat: float,
    lng: float,
    *aliases: str,
) -> dict[str, Any]:
    parts = [continent, country]
    if region:
        parts.append(region)
    label = " · ".join(parts)
    return {
        "key": key,
        "continent": continent,
        "country": country,
        "region": region,
        "label": label,
        "lat": lat,
        "lng": lng,
        "aliases": list(aliases),
    }


# Approximate centroids / capitals for map pins.
_US_STATES: list[tuple[str, str, float, float]] = [
    ("al", "Alabama", 32.38, -86.30),
    ("ak", "Alaska", 61.22, -149.90),
    ("az", "Arizona", 33.45, -112.07),
    ("ar", "Arkansas", 34.75, -92.29),
    ("ca", "California", 36.78, -119.42),
    ("co", "Colorado", 39.74, -104.99),
    ("ct", "Connecticut", 41.76, -72.69),
    ("de", "Delaware", 39.16, -75.52),
    ("dc", "District of Columbia", 38.91, -77.04),
    ("fl", "Florida", 27.99, -81.76),
    ("ga", "Georgia", 33.75, -84.39),
    ("hi", "Hawaii", 21.31, -157.86),
    ("id", "Idaho", 43.62, -116.20),
    ("il", "Illinois", 40.63, -89.40),
    ("in", "Indiana", 39.79, -86.15),
    ("ia", "Iowa", 41.59, -93.62),
    ("ks", "Kansas", 38.58, -98.00),
    ("ky", "Kentucky", 37.84, -84.27),
    ("la", "Louisiana", 30.45, -91.19),
    ("me", "Maine", 44.31, -69.78),
    ("md", "Maryland", 39.05, -76.64),
    ("ma", "Massachusetts", 42.36, -71.06),
    ("mi", "Michigan", 42.33, -83.05),
    ("mn", "Minnesota", 44.98, -93.27),
    ("ms", "Mississippi", 32.30, -90.18),
    ("mo", "Missouri", 38.63, -90.20),
    ("mt", "Montana", 46.59, -112.04),
    ("ne", "Nebraska", 41.26, -95.94),
    ("nv", "Nevada", 36.17, -115.14),
    ("nh", "New Hampshire", 43.21, -71.54),
    ("nj", "New Jersey", 40.22, -74.76),
    ("nm", "New Mexico", 35.69, -105.94),
    ("ny", "New York", 40.71, -74.01),
    ("nc", "North Carolina", 35.78, -78.64),
    ("nd", "North Dakota", 46.81, -100.78),
    ("oh", "Ohio", 39.96, -82.99),
    ("ok", "Oklahoma", 35.47, -97.52),
    ("or", "Oregon", 44.98, -123.03),
    ("pa", "Pennsylvania", 40.44, -79.99),
    ("ri", "Rhode Island", 41.82, -71.41),
    ("sc", "South Carolina", 34.00, -81.03),
    ("sd", "South Dakota", 44.37, -100.35),
    ("tn", "Tennessee", 36.16, -86.78),
    ("tx", "Texas", 30.27, -97.74),
    ("ut", "Utah", 40.76, -111.89),
    ("vt", "Vermont", 44.26, -72.58),
    ("va", "Virginia", 37.54, -77.46),
    ("wa", "Washington", 47.61, -122.33),
    ("wv", "West Virginia", 38.35, -81.63),
    ("wi", "Wisconsin", 43.07, -89.40),
    ("wy", "Wyoming", 41.14, -104.82),
]

_CA_PROVINCES: list[tuple[str, str, float, float]] = [
    ("ab", "Alberta", 53.55, -113.49),
    ("bc", "British Columbia", 49.28, -123.12),
    ("mb", "Manitoba", 49.90, -97.14),
    ("nb", "New Brunswick", 45.96, -66.64),
    ("nl", "Newfoundland and Labrador", 47.56, -52.71),
    ("ns", "Nova Scotia", 44.65, -63.58),
    ("nt", "Northwest Territories", 62.45, -114.37),
    ("nu", "Nunavut", 63.75, -68.52),
    ("on", "Ontario", 43.65, -79.38),
    ("pe", "Prince Edward Island", 46.24, -63.13),
    ("qc", "Quebec", 46.81, -71.21),
    ("sk", "Saskatchewan", 50.45, -104.61),
    ("yt", "Yukon", 60.72, -135.05),
]

# UK nations + popular metro areas (London called out explicitly).
_UK_AREAS: list[tuple[str, str, float, float]] = [
    ("london", "London", 51.51, -0.13),
    ("england-se", "England · South East", 51.27, -0.76),
    ("england-sw", "England · South West", 51.45, -2.59),
    ("england-midlands", "England · Midlands", 52.49, -1.89),
    ("england-nw", "England · North West", 53.48, -2.24),
    ("england-ne", "England · North East", 54.98, -1.61),
    ("england-yorks", "England · Yorkshire", 53.80, -1.55),
    ("manchester", "Manchester", 53.48, -2.24),
    ("birmingham", "Birmingham", 52.49, -1.89),
    ("cambridge", "Cambridge", 52.21, 0.12),
    ("bristol", "Bristol", 51.45, -2.59),
    ("leeds", "Leeds", 53.80, -1.55),
    ("scotland", "Scotland", 55.95, -3.19),
    ("edinburgh", "Edinburgh", 55.95, -3.19),
    ("glasgow", "Glasgow", 55.86, -4.25),
    ("wales", "Wales", 51.48, -3.18),
    ("cardiff", "Cardiff", 51.48, -3.18),
    ("ni", "Northern Ireland", 54.60, -5.93),
    ("belfast", "Belfast", 54.60, -5.93),
]

# Popular Indian states / metro areas.
_IN_AREAS: list[tuple[str, str, float, float]] = [
    ("dl", "Delhi NCR", 28.61, 77.21),
    ("mh", "Maharashtra", 19.08, 72.88),
    ("mumbai", "Mumbai", 19.08, 72.88),
    ("pune", "Pune", 18.52, 73.86),
    ("ka", "Karnataka", 12.97, 77.59),
    ("bengaluru", "Bengaluru", 12.97, 77.59),
    ("tn", "Tamil Nadu", 13.08, 80.27),
    ("chennai", "Chennai", 13.08, 80.27),
    ("ts", "Telangana", 17.39, 78.49),
    ("hyderabad", "Hyderabad", 17.39, 78.49),
    ("gj", "Gujarat", 23.02, 72.57),
    ("ahmedabad", "Ahmedabad", 23.02, 72.57),
    ("wb", "West Bengal", 22.57, 88.36),
    ("kolkata", "Kolkata", 22.57, 88.36),
    ("hr", "Haryana", 28.46, 77.03),
    ("up", "Uttar Pradesh", 26.85, 80.95),
    ("rj", "Rajasthan", 26.91, 75.79),
    ("pb", "Punjab", 30.73, 76.78),
    ("kl", "Kerala", 9.93, 76.27),
    ("ap", "Andhra Pradesh", 17.69, 83.22),
]

# Singapore planning regions / popular districts (city-state).
_SG_AREAS: list[tuple[str, str, float, float]] = [
    ("central", "Central", 1.29, 103.85),
    ("cbd", "CBD / Downtown", 1.28, 103.85),
    ("east", "East", 1.35, 103.94),
    ("changi", "Changi", 1.36, 103.99),
    ("north", "North", 1.43, 103.79),
    ("woodlands", "Woodlands", 1.44, 103.79),
    ("northeast", "North-East", 1.39, 103.89),
    ("west", "West", 1.34, 103.70),
    ("jurong", "Jurong", 1.33, 103.74),
]

# Mainland China — popular municipalities / provinces / metro areas.
_CN_AREAS: list[tuple[str, str, float, float]] = [
    ("beijing", "Beijing", 39.90, 116.41),
    ("shanghai", "Shanghai", 31.23, 121.47),
    ("shenzhen", "Shenzhen", 22.54, 114.06),
    ("guangzhou", "Guangzhou", 23.13, 113.26),
    ("hangzhou", "Hangzhou", 30.27, 120.16),
    ("chengdu", "Chengdu", 30.57, 104.07),
    ("chongqing", "Chongqing", 29.56, 106.55),
    ("wuhan", "Wuhan", 30.59, 114.31),
    ("nanjing", "Nanjing", 32.06, 118.80),
    ("suzhou", "Suzhou", 31.30, 120.62),
    ("tianjin", "Tianjin", 39.08, 117.20),
    ("xian", "Xi'an", 34.34, 108.94),
    ("qingdao", "Qingdao", 36.07, 120.38),
    ("dalian", "Dalian", 38.91, 121.61),
    ("xiamen", "Xiamen", 24.48, 118.09),
    ("guangdong", "Guangdong", 23.13, 113.26),
    ("zhejiang", "Zhejiang", 30.27, 120.16),
    ("jiangsu", "Jiangsu", 32.06, 118.80),
    ("sichuan", "Sichuan", 30.57, 104.07),
    ("hubei", "Hubei", 30.59, 114.31),
]

# Hong Kong — popular districts / areas.
_HK_AREAS: list[tuple[str, str, float, float]] = [
    ("central", "Central", 22.28, 114.16),
    ("admiralty", "Admiralty", 22.28, 114.17),
    ("wan-chai", "Wan Chai", 22.28, 114.17),
    ("tst", "Tsim Sha Tsui", 22.30, 114.17),
    ("kowloon", "Kowloon", 22.32, 114.17),
    ("mong-kok", "Mong Kok", 22.32, 114.17),
    ("hong-kong-island", "Hong Kong Island", 22.27, 114.19),
    ("new-territories", "New Territories", 22.45, 114.16),
    ("sha-tin", "Sha Tin", 22.38, 114.19),
    ("tuen-mun", "Tuen Mun", 22.39, 113.97),
    ("kwun-tong", "Kwun Tong", 22.31, 114.23),
    ("quarry-bay", "Quarry Bay", 22.29, 114.21),
    ("cyberport", "Cyberport", 22.26, 114.13),
    ("science-park", "Science Park", 22.43, 114.21),
]


def _append_named_areas(
    out: list[dict[str, Any]],
    *,
    prefix: str,
    continent: str,
    country: str,
    areas: list[tuple[str, str, float, float]],
    extra_aliases: tuple[str, ...] = (),
) -> None:
    seen: set[str] = set()
    for code, name, lat, lng in areas:
        if code in seen:
            continue
        seen.add(code)
        out.append(
            _loc(
                f"{prefix}-{code}",
                continent,
                country,
                name,
                lat,
                lng,
                name,
                country,
                f"{country} {name}",
                *extra_aliases,
            )
        )


def _build_locations() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for code, name, lat, lng in _US_STATES:
        out.append(
            _loc(
                f"us-{code}",
                "North America",
                "United States",
                name,
                lat,
                lng,
                name,
                code.upper(),
                f"US {name}",
                f"USA {name}",
            )
        )

    for code, name, lat, lng in _CA_PROVINCES:
        out.append(
            _loc(
                f"ca-{code}",
                "North America",
                "Canada",
                name,
                lat,
                lng,
                name,
                code.upper(),
                f"Canada {name}",
            )
        )

    _append_named_areas(
        out, prefix="uk", continent="Europe", country="United Kingdom", areas=_UK_AREAS
    )
    _append_named_areas(
        out, prefix="in", continent="Asia", country="India", areas=_IN_AREAS
    )
    _append_named_areas(
        out, prefix="sg", continent="Asia", country="Singapore", areas=_SG_AREAS
    )
    _append_named_areas(
        out,
        prefix="cn",
        continent="Asia",
        country="China (Mainland)",
        areas=_CN_AREAS,
        extra_aliases=("China", "Mainland China", "PRC", "CN"),
    )
    _append_named_areas(
        out,
        prefix="hk",
        continent="Asia",
        country="Hong Kong",
        areas=_HK_AREAS,
        extra_aliases=("Hongkong", "HK", "HKSAR"),
    )

    # Other countries — North / South / East / West / Central
    regional = [
        ("mx", "North America", "Mexico", 19.43, -99.13),
        ("ie", "Europe", "Ireland", 53.35, -6.26),
        ("de", "Europe", "Germany", 50.11, 8.68),
        ("nl", "Europe", "Netherlands", 52.37, 4.90),
        ("fr", "Europe", "France", 48.86, 2.35),
        ("se", "Europe", "Sweden", 59.33, 18.07),
        ("es", "Europe", "Spain", 40.42, -3.70),
        ("it", "Europe", "Italy", 41.90, 12.50),
        ("ch", "Europe", "Switzerland", 46.95, 7.45),
        ("pl", "Europe", "Poland", 52.23, 21.01),
        ("jp", "Asia", "Japan", 35.68, 139.69),
        ("kr", "Asia", "South Korea", 37.57, 126.98),
        ("tw", "Asia", "Taiwan", 23.70, 120.96),
        ("id", "Asia", "Indonesia", -0.79, 113.92),
        ("au", "Oceania", "Australia", -25.27, 133.78),
        ("nz", "Oceania", "New Zealand", -40.90, 174.89),
        ("br", "South America", "Brazil", -14.24, -51.93),
        ("ar", "South America", "Argentina", -38.42, -63.62),
        ("cl", "South America", "Chile", -35.68, -71.54),
        ("ae", "Middle East", "United Arab Emirates", 23.42, 53.85),
        ("sa", "Middle East", "Saudi Arabia", 23.89, 45.08),
        ("il", "Middle East", "Israel", 31.05, 34.85),
        ("za", "Africa", "South Africa", -30.56, 22.94),
        ("eg", "Africa", "Egypt", 26.82, 30.80),
        ("ng", "Africa", "Nigeria", 9.08, 8.68),
        ("ke", "Africa", "Kenya", -0.02, 37.91),
    ]
    # Approximate regional offsets from country center
    offsets = {
        "North": (3.0, 0.0),
        "South": (-3.0, 0.0),
        "East": (0.0, 3.0),
        "West": (0.0, -3.0),
        "Central": (0.0, 0.0),
    }
    for code, continent, country, lat, lng in regional:
        for region, (dlat, dlng) in offsets.items():
            out.append(
                _loc(
                    f"{code}-{region.lower()}",
                    continent,
                    country,
                    region,
                    lat + dlat,
                    lng + dlng,
                    country,
                    f"{country} {region}",
                    region,
                )
            )

    out.append(
        _loc("lab", "Other", "Lab / On-prem", "", 38.90, -77.04, "Lab", "On-prem", "Onprem")
    )
    return out


LOCATIONS: list[dict[str, Any]] = _build_locations()

_BY_KEY: dict[str, dict[str, Any]] = {loc["key"]: loc for loc in LOCATIONS}

# Older coarse US/Canada region keys → representative state/province.
_ALIASES: dict[str, str] = {
    "us-north": "us-mn",
    "us-south": "us-tx",
    "us-east": "us-va",
    "us-west": "us-or",
    "us-central": "us-il",
    "ca-north": "ca-nt",
    "ca-south": "ca-bc",
    "ca-east": "ca-on",
    "ca-west": "ca-bc",
    "ca-central": "ca-mb",
    "uk": "uk-london",
    "uk-north": "uk-scotland",
    "uk-south": "uk-england-se",
    "uk-east": "uk-england-se",
    "uk-west": "uk-england-sw",
    "uk-central": "uk-london",
    "ie": "ie-east",
    "de": "de-central",
    "nl": "nl-west",
    "fr": "fr-central",
    "se": "se-east",
    "sg": "sg-central",
    "sg-north": "sg-north",
    "sg-south": "sg-central",
    "sg-east": "sg-east",
    "sg-west": "sg-west",
    "sg-central": "sg-central",
    "cn": "cn-beijing",
    "cn-north": "cn-beijing",
    "cn-south": "cn-shenzhen",
    "cn-east": "cn-shanghai",
    "cn-west": "cn-chengdu",
    "cn-central": "cn-wuhan",
    "hk": "hk-central",
    "hk-north": "hk-new-territories",
    "hk-south": "hk-hong-kong-island",
    "hk-east": "hk-quarry-bay",
    "hk-west": "hk-central",
    "hk-central": "hk-central",
    "kr": "kr-central",
    "mx": "mx-central",
    "ae": "ae-north",
    "me-central": "ae-central",
    "in-north": "in-dl",
    "in-south": "in-bengaluru",
    "in-east": "in-kolkata",
    "in-west": "in-mumbai",
    "in-central": "in-hyderabad",
    "jp-east": "jp-east",
    "jp-west": "jp-west",
    "au-east": "au-east",
    "au-west": "au-west",
    "br-east": "br-east",
}


def get_location(key: str | None) -> dict[str, Any] | None:
    if not key:
        return None
    raw = str(key).strip()
    resolved = _ALIASES.get(raw, raw)
    return _BY_KEY.get(resolved)


def normalize_location_key(value: str | None, *, allow_empty: bool = True) -> str | None:
    """Return a catalog key, None if empty, or raise ValueError if unknown."""
    raw = (value or "").strip()
    if not raw:
        if allow_empty:
            return None
        raise ValueError("location is required")
    if raw in _BY_KEY:
        return raw
    if raw in _ALIASES:
        return _ALIASES[raw]
    raise ValueError(
        f"Unknown location '{raw}'. Choose a suggestion from the list."
    )


def enrich_appliance_location(item: dict[str, Any]) -> dict[str, Any]:
    """Attach location_label / lat / lng; flag legacy free-text as unmapped."""
    raw = (item.get("location") or "").strip() or None
    loc = get_location(raw)
    if loc:
        item["location"] = loc["key"]
        item["location_label"] = loc["label"]
        item["location_lat"] = loc["lat"]
        item["location_lng"] = loc["lng"]
        item["location_mapped"] = True
        item["location_previous"] = None
    elif raw:
        item["location"] = raw
        item["location_label"] = raw
        item["location_lat"] = None
        item["location_lng"] = None
        item["location_mapped"] = False
        item["location_previous"] = raw
    else:
        item["location"] = None
        item["location_label"] = None
        item["location_lat"] = None
        item["location_lng"] = None
        item["location_mapped"] = False
        item["location_previous"] = None
    return item


def locations_api_payload() -> dict[str, Any]:
    """Flat suggestion list for autocomplete (+ continent tree for compatibility)."""
    suggestions = []
    for loc in LOCATIONS:
        suggestions.append(
            {
                "key": loc["key"],
                "label": loc["label"],
                "continent": loc["continent"],
                "country": loc["country"],
                "region": loc["region"] or "",
                "lat": loc["lat"],
                "lng": loc["lng"],
                "aliases": loc.get("aliases") or [],
            }
        )

    # Keep continents grouping for any older clients.
    tree: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for loc in LOCATIONS:
        tree.setdefault(loc["continent"], {}).setdefault(loc["country"], []).append(
            {
                "key": loc["key"],
                "region": loc["region"] or "",
                "label": loc["label"],
                "lat": loc["lat"],
                "lng": loc["lng"],
            }
        )
    continents = [
        {
            "continent": continent,
            "countries": [
                {"country": country, "regions": regions}
                for country, regions in countries.items()
            ],
        }
        for continent, countries in tree.items()
    ]

    return {
        "locations": list(LOCATIONS),
        "suggestions": suggestions,
        "continents": continents,
    }
