import os
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv import load_dotenv


load_dotenv()

WEATHER_LAT = float(os.getenv("WEATHER_LAT"))
WEATHER_LON = float(os.getenv("WEATHER_LON"))


def wind_direction_text(degrees):
    directions = [
        "N", "NE", "E", "SE",
        "S", "SW", "W", "NW"
    ]

    index = round(degrees / 45) % 8

    return directions[index]


def weather_emoji(code):
    if code == 0:
        return "☀️"
    elif code in (1, 2):
        return "🌤️"
    elif code == 3:
        return "☁️"
    elif code in (45, 48):
        return "🌫️"
    elif code in (51, 53, 55, 56, 57):
        return "🌦️"
    elif code in (
        61, 63, 65,
        66, 67,
        80, 81, 82
    ):
        return "🌧️"
    elif code in (
        71, 73, 75,
        77, 85, 86
    ):
        return "🌨️"
    elif code in (95, 96, 99):
        return "⛈️"

    return "🌡️"


def format_time(dt):
    return dt.strftime("%I:%M %p").lstrip("0")


def get_forecast(match_date, first_tee_time):
    start_datetime = (
        datetime.combine(
            match_date,
            datetime.min.time()
        )
        + first_tee_time
    )

    end_datetime = (
        start_datetime
        + timedelta(hours=5)
    )

    params = {
        "latitude": WEATHER_LAT,
        "longitude": WEATHER_LON,
        "hourly": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation_probability",
            "weather_code",
            "cloud_cover",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m"
        ]),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "America/Chicago",
        "start_date": match_date.isoformat(),
        "end_date": match_date.isoformat()
    }

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urlencode(params)
    )

    with urlopen(url, timeout=10) as response:
        data = json.load(response)

    hourly = data["hourly"]

    def find_hour(target):
        target_hour = target.replace(
            minute=0,
            second=0,
            microsecond=0
        )

        target_string = target_hour.strftime(
            "%Y-%m-%dT%H:%M"
        )

        index = hourly["time"].index(
            target_string
        )

        return {
            "time": target,
            "temperature": round(
                hourly["temperature_2m"][index]
            ),
            "humidity": round(
                hourly["relative_humidity_2m"][index]
            ),
            "heat_index": round(
                hourly["apparent_temperature"][index]
            ),
            "rain_chance": round(
                hourly["precipitation_probability"][index]
            ),
            "cloud_cover": round(
                hourly["cloud_cover"][index]
            ),
            "wind_speed": round(
                hourly["wind_speed_10m"][index]
            ),
            "wind_direction": wind_direction_text(
                hourly["wind_direction_10m"][index]
            ),
            "wind_gusts": round(
                hourly["wind_gusts_10m"][index]
            ),
            "weather_code": hourly[
                "weather_code"
            ][index]
        }

    return {
        "start": find_hour(start_datetime),
        "end": find_hour(end_datetime)
    }