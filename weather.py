###################
# Created : 2026-09-02 GB
# Purpose : Retrieves hourly weather forecast data for CFB matches.
#           Formats Open-Meteo forecast data for use by Discord commands,
#           including temperature, precipitation, wind, and weather conditions.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Index
#           OpenAI model/version: GPT-5.6 Sol
###################

import certifi
import json
import os
import ssl

from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen


# Geographic coordinates used for CFB match weather forecasts.
WEATHER_LAT = float(os.getenv("WEATHER_LAT"))
WEATHER_LON = float(os.getenv("WEATHER_LON"))


def format_time(dt):
    # Format a datetime for concise Discord-friendly display.
    return dt.strftime("%I:%M %p").lstrip("0")


def get_forecast(match_date, first_tee_time):
    # Build the forecast window from the first tee time through five hours later.
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

    # Request the hourly weather measurements used by the bot.
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

    # Use certifi's CA bundle to provide a reliable certificate chain
    # for the HTTPS request.
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    with urlopen(url, timeout=10, context=ssl_context) as response:
        data = json.load(response)

    hourly = data["hourly"]

    # Extract the Open-Meteo hourly record corresponding to a target time.
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
            "apparent_temperature": round(
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


def weather_emoji(code):
    # Translate Open-Meteo WMO weather codes into a compact Discord icon.
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

    # Unknown or unsupported weather codes receive a generic weather icon.
    return "🌡️"


def wind_direction_text(degrees):
    # Convert numeric wind bearings into eight standard compass directions.
    directions = [
        "N", "NE", "E", "SE",
        "S", "SW", "W", "NW"
    ]

    index = round(degrees / 45) % 8

    return directions[index]