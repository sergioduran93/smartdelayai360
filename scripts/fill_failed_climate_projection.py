import csv
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

BASE_URL = "https://climate-api.open-meteo.com/v1/climate"
START_DATE = "2025-01-01"
END_DATE = "2028-12-31"
MODEL = "CMCC_CM2_VHR4"

FAIL_PATH = Path("data/processed/climate_projection_failed_countries.csv")
OUT_PATH = Path("data/processed/climate_projection_150_countries_2025_2028.csv")

DAILY_VARS = [
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_mean",
]


def fetch_daily_projection(lat: float, lon: float, retries: int = 10):
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
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            if attempt >= retries:
                raise exc
            wait_seconds = min(90, 3 * (2 ** attempt))
            print(f"Retry {attempt + 1}/{retries} in {wait_seconds}s -> {exc}")
            time.sleep(wait_seconds)
            attempt += 1


def load_failures(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main():
    failures = load_failures(FAIL_PATH)
    if not failures:
        print("No failed countries found. Nothing to fill.")
        return

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

    still_failed = []
    added_rows = 0

    with OUT_PATH.open("a", encoding="utf-8", newline="") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=out_fields)

        for i, row in enumerate(failures, start=1):
            country = row["country"]
            orders = row.get("orders", "")
            lat = float(row["latitude"])
            lon = float(row["longitude"])

            try:
                payload = fetch_daily_projection(lat, lon)
                daily = payload.get("daily", {})
                dates = daily.get("time", [])

                for idx, date_value in enumerate(dates):
                    writer.writerow(
                        {
                            "country": country,
                            "orders": orders,
                            "latitude": lat,
                            "longitude": lon,
                            "date": date_value,
                            "temperature_2m_mean": daily.get("temperature_2m_mean", [None])[idx],
                            "temperature_2m_max": daily.get("temperature_2m_max", [None])[idx],
                            "temperature_2m_min": daily.get("temperature_2m_min", [None])[idx],
                            "precipitation_sum": daily.get("precipitation_sum", [None])[idx],
                            "wind_speed_10m_mean": daily.get("wind_speed_10m_mean", [None])[idx],
                            "model": MODEL,
                            "source": "Open-Meteo Climate API",
                        }
                    )
                    added_rows += 1

                print(f"[{i}/{len(failures)}] OK - {country} ({len(dates)} days)")
                time.sleep(2.0)
            except Exception as exc:
                still_failed.append(
                    {
                        "country": country,
                        "orders": orders,
                        "latitude": lat,
                        "longitude": lon,
                        "error": str(exc),
                    }
                )
                print(f"[{i}/{len(failures)}] FAIL - {country} -> {exc}")

    with FAIL_PATH.open("w", encoding="utf-8", newline="") as ff:
        writer = csv.DictWriter(ff, fieldnames=["country", "orders", "latitude", "longitude", "error"])
        writer.writeheader()
        writer.writerows(still_failed)

    print("\nFill completed.")
    print(f"Added rows: {added_rows}")
    print(f"Remaining failures: {len(still_failed)}")


if __name__ == "__main__":
    main()
