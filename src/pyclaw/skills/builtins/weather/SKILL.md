---
name: weather
description: Get current weather for a location. Use when the user asks about weather conditions, forecasts, or temperature for any city or region.
---

# Weather Skill

Provide current weather information for any location.

## Usage

When the user asks about weather, use the web_search tool to find current conditions.

### Steps

1. Extract the location from the user's request.
2. Search for current weather using web_search (e.g. "current weather in {location}").
3. Summarize the key information: temperature, conditions, humidity, wind.
4. Include the data source and time of the report.
