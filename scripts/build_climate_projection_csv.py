import csv
import json
import time
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

BASE_URL = "https://climate-api.open-meteo.com/v1/climate"
START_DATE = "2025-01-01"
END_DATE = "2028-12-31"
MODEL = "CMCC_CM2_VHR4"
TARGET_COUNTRIES = 150

DATA_CO_PATH = Path("data/raw/DataCoSupplyChainDataset.csv")
OUT_DIR = Path("data/processed")
OUT_PATH = OUT_DIR / "climate_projection_150_countries_2025_2028.csv"
FAIL_PATH = OUT_DIR / "climate_projection_failed_countries.csv"

DAILY_VARS = [
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_mean",
]


def _to_float(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_top_countries_from_dataco(path: Path, limit: int):
    stats = defaultdict(lambda: {"count": 0, "lat_sum": 0.0, "lon_sum": 0.0, "geo_count": 0})

    with path.open("r", encoding="latin-1", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            country = (row.get("Order Country") or "").strip()
            if not country:
                continue

            stats[country]["count"] += 1

            lat = _to_float(row.get("Latitude"))
            lon = _to_float(row.get("Longitude"))
            if lat is not None and lon is not None:
                stats[country]["lat_sum"] += lat
                stats[country]["lon_sum"] += lon
                stats[country]["geo_count"] += 1

    ranked = sorted(stats.items(), key=lambda kv: kv[1]["count"], reverse=True)

    selected = []
    for country, s in ranked:
        if s["geo_count"] == 0:
            continue
        selected.append(
            {
                "country": country,
                "orders": s["count"],
                "latitude": round(s["lat_sum"] / s["geo_count"], 6),
                "longitude": round(s["lon_sum"] / s["geo_count"], 6),
            }
        )
        if len(selected) >= limit:
            break

    return selected


def fetch_daily_projection(lat: float, lon: float, retries: int = 6):
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "models": MODEL,
        "daily": ",".join(DAILY_VARS),
        "timezone": "UTC",
    }
    url = f"{BASE_URL}?{urlencode(params)}"

    attempt = 0
    while True:
        try:
            with urlopen(url, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload
        except HTTPError as exc:
            if exc.code == 429 and attempt < retries:
                wait_seconds = min(60, 2 ** attempt)
                print(f"Rate limit (429). Retrying in {wait_seconds}s...")
                time.sleep(wait_seconds)
                attempt += 1
                continue
            raise
        except URLError:
            if attempt < retries:
                wait_seconds = min(30, 2 ** attempt)
                print(f"Network error. Retrying in {wait_seconds}s...")
                time.sleep(wait_seconds)
                attempt += 1
                continue
            raise


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    countries = load_top_countries_from_dataco(DATA_CO_PATH, TARGET_COUNTRIES)
    if not countries:
        raise RuntimeError("No countries with valid latitude/longitude were found in DataCo.")

    out_fields = [
        "country",
        "orders",
        "latitude",
        "longitude",
        "date",
        "temperature_2m_mean",
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_sum",
        "wind_speed_10m_mean",
        "model",
        "source",
    ]

    failures = []
    rows_written = 0

    with OUT_PATH.open("w", encoding="utf-8", newline="") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=out_fields)
        writer.writeheader()

        for i, country in enumerate(countries, start=1):
            try:
                payload = fetch_daily_projection(country["latitude"], country["longitude"])
                daily = payload.get("daily", {})
                dates = daily.get("time", [])

                for idx, date_value in enumerate(dates):
                    row = {
                        "country": country["country"],
                        "orders": country["orders"],
                        "latitude": country["latitude"],
                        "longitude": country["longitude"],
                        "date": date_value,
                        "temperature_2m_mean": daily.get("temperature_2m_mean", [None])[idx],
                        "temperature_2m_max": daily.get("temperature_2m_max", [None])[idx],
                        "temperature_2m_min": daily.get("temperature_2m_min", [None])[idx],
                        "precipitation_sum": daily.get("precipitation_sum", [None])[idx],
                        "wind_speed_10m_mean": daily.get("wind_speed_10m_mean", [None])[idx],
                        "model": MODEL,
                        "source": "Open-Meteo Climate API",
                    }
                    writer.writerow(row)
                    rows_written += 1

                print(f"[{i}/{len(countries)}] OK - {country['country']} ({len(dates)} days)")
            except Exception as exc:
                failures.append(
                    {
                        "country": country["country"],
                        "orders": country["orders"],
                        "latitude": country["latitude"],
                        "longitude": country["longitude"],
                        "error": str(exc),
                    }
                )
                print(f"[{i}/{len(countries)}] FAIL - {country['country']} -> {exc}")

            time.sleep(0.8)

    with FAIL_PATH.open("w", encoding="utf-8", newline="") as ff:
        ff_writer = csv.DictWriter(
            ff,
            fieldnames=["country", "orders", "latitude", "longitude", "error"],
        )
        ff_writer.writeheader()
        ff_writer.writerows(failures)

    print("\nDone.")
    print(f"Countries attempted: {len(countries)}")
    print(f"Rows written: {rows_written}")
    print(f"Failures: {len(failures)}")
    print(f"Output: {OUT_PATH}")
    print(f"Failure log: {FAIL_PATH}")


if __name__ == "__main__":
    main()
