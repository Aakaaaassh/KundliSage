from datetime import datetime, timedelta
from pymongo import MongoClient
from fastapi import FastAPI, HTTPException, Depends, Security, Query, Body, Request, Response
from fastapi.security import APIKeyHeader
import requests
import os
from dotenv import load_dotenv
from enum import Enum
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from enum import Enum
from pydantic import BaseModel
from uuid import uuid4
import markdown  # For converting Markdown to HTML if needed
import re  # For basic text processing




# Load environment variables from .env file
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect to MongoDB
mongo_uri = os.environ.get("MONGO_URI")
client = MongoClient(mongo_uri)
db = client["astrology_app"]
sessions_collection = db["user_sessions"]
user_chat_sessions = db["chat_sessions"]  # New collection for chat session data

# Custom StaticFiles class to disable caching
class StaticFilesWithoutCaching(StaticFiles):
    def is_not_modified(self, *args, **kwargs) -> bool:
        return False


# Mount static files with caching disabled
app.mount("/static", StaticFilesWithoutCaching(directory=Path("static"), html=True), name="static")

# Retrieve the API key from environment variables
API_KEY = os.environ.get("API_KEY", "")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY", "")

# Define the API key header scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Dependency to validate the API key from the header (defaults to env key)
async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == API_KEY or not api_key_header:
        return API_KEY
    else:
        raise HTTPException(status_code=403, detail="Could not validate API Key")

# Store the latest search results for selection (in a real app, use a database or session)
latest_search_results = []


class ChatPredictionRequest(BaseModel):
    name: str
    dob: str  # DD/MM/YYYY
    tob: str  # HH:MM
    lat: str
    lon: str
    tz: float
    lang: str = "en"
    query: str


# Define Enum for planet selection dropdown
class Planet(str, Enum):
    Sun = "Sun"
    Moon = "Moon"
    Mercury = "Mercury"
    Venus = "Venus"
    Mars = "Mars"
    Jupiter = "Jupiter"
    Saturn = "Saturn"
    Rahu = "Rahu"
    Ketu = "Ketu"

class AspectResponseType(str, Enum):
    houses = "houses"
    planets = "planets"

# Define Enum for response type dropdown
class ResponseType(str, Enum):
    planet_object = "planet_object"
    house_array = "house_array"


# Define Enum for divisional chart dropdown
class DivisionalChart(str, Enum):
    D1 = "D1"  # Lagna
    D3 = "D3"  # Dreshkana
    D3_s = "D3-s"  # D3-Somanatha
    D7 = "D7"  # Saptamsa
    D9 = "D9"  # Navamsa
    D10 = "D10"  # Dasamsa
    D10_R = "D10-R"  # Dasamsa-EvenReverse
    D12 = "D12"  # Dwadasamsa
    D16 = "D16"  # Shodashamsa
    D20 = "D20"  # Vimsama
    D24 = "D24"  # ChaturVimshamsha
    D24_R = "D24-R"  # D24-R
    D30 = "D30"  # Trimshamsha
    D40 = "D40"  # KhaVedamsa
    D45 = "D45"  # AkshaVedamsa
    D60 = "D60"  # Shastiamsha
    chalit = "chalit"  # Bhav-chalit
    moon = "moon"  # Moon chart
    sun = "sun"  # Sun chart

# Define Enum for chart style dropdown
class ChartStyle(str, Enum):
    north = "north"
    south = "south"

# Define Enum for split dropdown (boolean as string for FastAPI compatibility)
class SplitOption(str, Enum):
    true = "true"
    false = "false"

# Define Enum for type dropdown
class PredictionType(str, Enum):
    big = "big"
    small = "small"

# Define Enum for zodiac dropdown (1 to 12 mapping to Aries to Pisces)
ZODIAC_MAPPING = {
    "Aries": 1,
    "Taurus": 2,
    "Gemini": 3,
    "Cancer": 4,
    "Leo": 5,
    "Virgo": 6,
    "Libra": 7,
    "Scorpio": 8,
    "Sagittarius": 9,
    "Capricorn": 10,
    "Aquarius": 11,
    "Pisces": 12
}

# List of Zodiac names for dropdown in Swagger UI
ZODIAC_NAMES = list(ZODIAC_MAPPING.keys())


# Define mapping for Nakshatra names to numeric values
NAKSHATRA_MAPPING = {
    "Ashwini": 1,
    "Bharani": 2,
    "Krittika": 3,
    "Rohini": 4,
    "Mrigashira": 5,
    "Ardra": 6,
    "Punarvasu": 7,
    "Pushya": 8,
    "Ashlesha": 9,
    "Magha": 10,
    "Purva Phalguni": 11,
    "Uttara Phalguni": 12,
    "Hasta": 13,
    "Chitra": 14,
    "Swati": 15,
    "Vishakha": 16,
    "Anuradha": 17,
    "Jyeshtha": 18,
    "Mula": 19,
    "Purva Ashadha": 20,
    "Uttara Ashadha": 21,
    "Shravana": 22,
    "Dhanishta": 23,
    "Shatabhisha": 24,
    "Purva Bhadrapada": 25,
    "Uttara Bhadrapada": 26,
    "Revati": 27
}

# List of Nakshatra names for dropdown in Swagger UI
NAKSHATRA_NAMES = list(NAKSHATRA_MAPPING.keys())




# Define Enum for week dropdown
class WeekOption(str, Enum):
    thisweek = "thisweek"
    nextweek = "nextweek"


# Function to fetch geo data from the external API
def fetch_geo_data(api_key: str, city: str):
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/utilities/geo-search",
        params={"api_key": api_key, "city": city}
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch data from external API")

# Function to fetch planet details from the external API
def fetch_planet_details(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/planet-details",
        params=params
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch planet details from external API")


# Function to ascendant report details from the external API
def ascendant_report(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/ascendant-report",
        params=params
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch planet details from external API")
    
# Function to fetch planet report from the external API
def fetch_planet_report(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/planet-report",
        params=params
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch planet report from external API")

# Function to fetch personal characteristics from the external API
def fetch_personal_characteristics(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/personal-characteristics",
        params=params
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch personal characteristics from external API")
    

# Function to fetch Ashtakvarga data from the external API
def fetch_ashtakvarga(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/ashtakvarga",
        params=params
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch Ashtakvarga data from external API")
    
# Function to fetch Binnashtakvarga data from the external API
def fetch_binnashtakvarga(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/binnashtakvarga",
        params=params
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch Binnashtakvarga data from external API")


# Function to fetch AI 12-month prediction data from the external API
def fetch_ai_12_month_prediction(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/ai-12-month-prediction",
        params=params
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch AI 12-month prediction data from external API")
    

# Function to fetch Planetary Aspects data from the external API
def fetch_planetary_aspects(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/planetary-aspects",
        params=params
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch Planetary Aspects data from external API")
    

# Function to fetch Planets in Houses data from the external API
def fetch_planets_in_houses(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/planets-in-houses",
        params=params
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch Planets in Houses data from external API")


# Function to fetch Divisional Charts data from the external API
def fetch_divisional_charts(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/divisional-charts",
        params=params
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch Divisional Charts data from external API")
    

# Function to fetch Chart Image data from the external API
def fetch_chart_image(api_key: str, params: dict):
    params["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/chart-image",
        params=params
    )
    if response.status_code == 200:
        return response.text
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch Chart Image data from external API")
    

# Function to fetch Ashtakvarga Chart Image data from the external API as raw SVG content
def fetch_ashtakvarga_chart_image(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/ashtakvarga-chart-image",
        params=params_copy
    )
    if response.status_code == 200:
        # Return the raw text content (likely SVG XML) instead of parsing as JSON
        return response.text
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Ashtakvarga Chart Image data from external API: {response.text}")


# Function to fetch Western Planets data from the external API
def fetch_western_planets(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/horoscope/western-planets",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Western Planets data from external API: {response.text}")
    
# Function to fetch Daily Sun prediction data from the external API
def fetch_daily_sun(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/prediction/daily-sun",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Daily Sun prediction data from external API: {response.text}")


# Function to fetch Daily Moon prediction data from the external API
def fetch_daily_moon(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/prediction/daily-moon",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Daily Moon prediction data from external API: {response.text}")

    
# Function to fetch Daily Nakshatra prediction data from the external API
# Function to fetch Daily Nakshatra prediction data from the external API
def fetch_daily_nakshatra(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/prediction/daily-nakshatra",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Daily Nakshatra prediction data from external API: {response.text}")


# Function to fetch Weekly Sun prediction data from the external API
def fetch_weekly_sun(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/prediction/weekly-sun",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Weekly Sun prediction data from external API: {response.text}")

# Function to fetch Weekly Moon prediction data from the external API
def fetch_weekly_moon(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/prediction/weekly-moon",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Weekly Moon prediction data from external API: {response.text}")

# Function to fetch Yearly prediction data from the external API
def fetch_yearly_prediction(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/prediction/yearly",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Yearly prediction data from external API: {response.text}")
    
# Function to fetch Biorhythm prediction data from the external API
def fetch_biorhythm(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/prediction/biorhythm",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Biorhythm prediction data from external API: {response.text}")


# Function to fetch Day Number prediction data from the external API
def fetch_day_number(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/prediction/day-number",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Day Number prediction data from external API: {response.text}")

# Function to fetch Numerology prediction data from the external API
def fetch_numerology(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/prediction/numerology",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Numerology prediction data from external API: {response.text}")

# Function to convert raw response to styled HTML
def format_response_to_html(raw_response: str) -> str:
    # Convert Markdown to HTML if the response contains Markdown formatting
    if "#" in raw_response or "-" in raw_response or "|" in raw_response:
        html_content = markdown.markdown(raw_response, extensions=['tables'])
    else:
        html_content = raw_response.replace("\n", "<br>")

    # Additional manual formatting for better structure if needed
    html_content = re.sub(r"<h1>(.*?)</h1>", r"<h1>\1</h1>", html_content)
    html_content = re.sub(r"<h2>(.*?)</h2>", r"<h2>\1</h2>", html_content)

# Function to fetch Find Moon Sign data from the external API
def fetch_find_moon_sign(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/find-moon-sign",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Find Moon Sign data from external API: {response.text}")
    

# Function to fetch Find Sun Sign data from the external API
def fetch_find_sun_sign(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/find-sun-sign",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Find Sun Sign data from external API: {response.text}")
    

# Function to fetch Find Ascendant data from the external API
def fetch_find_ascendant(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/find-ascendant",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Find Ascendant data from external API: {response.text}")
    

# Function to fetch Current Sade Sati data from the external API
def fetch_current_sade_sati(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/current-sade-sati",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Current Sade Sati data from external API: {response.text}")
    

# Function to fetch Sade Sati Table data from the external API
def fetch_sade_sati_table(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/sade-sati-table",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Sade Sati Table data from external API: {response.text}")



# Function to fetch Extended Kundli Details data from the external API
def fetch_extended_kundli_details(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/extended-kundli-details",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Extended Kundli Details data from external API: {response.text}")
    
# Function to fetch Yoga List data from the external API
def fetch_yoga_list(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/yoga-list",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Yoga List data from external API: {response.text}")

# Function to fetch Friendship Table data from the external API
def fetch_friendship(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/friendship",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Friendship Table data from external API: {response.text}")


# Function to fetch KP Planets data from the external API
def fetch_kp_planets(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/kp-planets",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch KP Planets data from external API: {response.text}")
    

# Function to fetch KP Houses data from the external API
def fetch_kp_houses(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/kp-houses",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch KP Houses data from external API: {response.text}")


# Function to fetch Shad Bala data from the external API
def fetch_shad_bala(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/shad-bala",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Shad Bala data from external API: {response.text}")


# Function to fetch Arudha Padas data from the external API
def fetch_arudha_padas(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/arutha-padas",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Arudha Padas data from external API: {response.text}")


# Function to fetch Jaimini Karakas data from the external API
def fetch_jaimini_karakas(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/jaimini-karakas",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Jaimini Karakas data from external API: {response.text}")
    

# Function to fetch Gem Suggestion data from the external API
def fetch_gem_suggestion(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/gem-suggestion",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Gem Suggestion data from external API: {response.text}")



# Function to fetch Numero Table data from the external API
def fetch_numero_table(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/numero-table",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Numero Table data from external API: {response.text}")

# Function to fetch Rudraksha Suggestion data from the external API
def fetch_rudraksh_suggestion(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/rudraksh-suggestion",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Rudraksha Suggestion data from external API: {response.text}")

# Function to fetch Varshapal Details data from the external API
def fetch_varshapal_details(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/varshapal-details",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Varshapal Details data from external API: {response.text}")

# Function to fetch Varshapal Month Chart data from the external API
def fetch_varshapal_month_chart(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/varshapal-month-chart",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Varshapal Month Chart data from external API: {response.text}")

# Function to fetch Varshapal Year Chart data from the external API
def fetch_varshapal_year_chart(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/extended-horoscope/varshapal-year-chart",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Varshapal Year Chart data from external API: {response.text}")

# Function to fetch Mangal Dosha data from the external API
def fetch_mangal_dosha(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dosha/mangal-dosh",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Mangal Dosha data from external API: {response.text}")

# Function to fetch Kaalsarp Dosha data from the external API
def fetch_kaalsarp_dosha(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dosha/kaalsarp-dosh",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Kaalsarp Dosha data from external API: {response.text}")

# Function to fetch Manglik Dosha data from the external API
def fetch_manglik_dosha(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dosha/manglik-dosh",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Manglik Dosha data from external API: {response.text}")


# Function to fetch Pitra Dosha data from the external API
def fetch_pitra_dosha(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dosha/pitra-dosh",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Pitra Dosha data from external API: {response.text}")

# Function to fetch Papasamya data from the external API
def fetch_papasamya(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dosha/papasamaya",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Papasamya data from external API: {response.text}")

# Function to fetch Mahadasha data from the external API
def fetch_maha_dasha(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/maha-dasha",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Mahadasha data from external API: {response.text}")

# Function to fetch Mahadasha Predictions data from the external API
def fetch_maha_dasha_predictions(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/maha-dasha-predictions",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Mahadasha Predictions data from external API: {response.text}")

# Function to fetch Antar Dasha data from the external API
def fetch_antar_dasha(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/antar-dasha",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Antar Dasha data from external API: {response.text}")

# Function to fetch Char Dasha Current data from the external API
def fetch_char_dasha_current(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/char-dasha-current",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Char Dasha Current data from external API: {response.text}")

# Function to fetch Char Dasha Main data from the external API
def fetch_char_dasha_main(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/char-dasha-main",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Char Dasha Main data from external API: {response.text}")

# Function to fetch Char Dasha Sub data from the external API
def fetch_char_dasha_sub(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/char-dasha-sub",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Char Dasha Sub data from external API: {response.text}")

# Function to fetch Current Mahadasha Full data from the external API
def fetch_current_mahadasha_full(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/current-mahadasha-full",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Current Mahadasha Full data from external API: {response.text}")

# Function to fetch Current Mahadasha data from the external API
def fetch_current_mahadasha(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/current-mahadasha",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Current Mahadasha data from external API: {response.text}")

# Function to fetch Paryantar Dasha data from the external API
def fetch_paryantar_dasha(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/paryantar-dasha",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Paryantar Dasha data from external API: {response.text}")

# Function to fetch Yogini Dasha Main data from the external API
def fetch_yogini_dasha_main(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/yogini-dasha-main",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Yogini Dasha Main data from external API: {response.text}")

# Function to fetch Yogini Dasha Sub data from the external API
def fetch_yogini_dasha_sub(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/dashas/yogini-dasha-sub",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Yogini Dasha Sub data from external API: {response.text}")

# Function to fetch Ashtakoot matching data from the external API
def fetch_ashtakoot(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/matching/ashtakoot",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Ashtakoot matching data from external API: {response.text}")

# Function to fetch Ashtakoot with Astro Details matching data from the external API
def fetch_ashtakoot_with_astro_details(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/matching/ashtakoot-with-astro-details",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Ashtakoot with Astro Details matching data from external API: {response.text}")

# Function to fetch Dashakoot matching data from the external API
def fetch_dashakoot(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/matching/dashakoot",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Dashakoot matching data from external API: {response.text}")
    

# Function to fetch Dashakoot with Astro Details matching data from the external API
def fetch_dashakoot_with_astro_details(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/matching/dashakoot-with-astro-details",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Dashakoot with Astro Details matching data from external API: {response.text}")

# Function to fetch Aggregate Match data from the external API
def fetch_aggregate_match(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/matching/aggregate-match",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Aggregate Match data from external API: {response.text}")

# Function to fetch Rajju Vedha Match data from the external API
def fetch_rajju_vedha_details(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/matching/rajju-vedha-details",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Rajju Vedha Match data from external API: {response.text}")

# Function to fetch Papasamaya Match data from the external API
def fetch_papasamaya_match(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/matching/papasamaya-match",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Papasamaya Match data from external API: {response.text}")

# Function to fetch Nakshatra Match data from the external API
def fetch_nakshatra_match(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/matching/nakshatra-match",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Nakshatra Match data from external API: {response.text}")

# Function to fetch Western Match data from the external API
def fetch_western_match(api_key: str, params: dict):
    params_copy = params.copy()
    params_copy["api_key"] = api_key
    response = requests.get(
        "https://api.vedicastroapi.com/v3-json/matching/western-match",
        params=params_copy
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch Western Match data from external API: {response.text}")


@app.get("/", response_class=HTMLResponse)
async def serve_chat_html():
    with open("static/final.html", "r") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content, status_code=200)



@app.get("/geo-search")
async def geo_search(
    city: str = Query(..., title="City Name", description="Enter the name of the city to search for locations (e.g., Kanpur)"),
    api_key: str = Depends(get_api_key)
):
    global latest_search_results
    data = fetch_geo_data(api_key, city)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request to external API")
    latest_search_results = data.get("response", [])
    # Return both full_name and coordinates for each location
    locations = [
        {"full_name": location["full_name"], "coordinates": location["coordinates"]}
        for location in latest_search_results
    ]
    return {"status": 200, "locations": locations, "result_length": len(locations)}


@app.get("/select-location")
async def select_location(
    full_name: str = Query(..., title="Full Location Name", description="Enter the full name of the location (e.g., Kanpur, Uttar Pradesh, IN)"),
    api_key: str = Depends(get_api_key)
):
    global latest_search_results
    for location in latest_search_results:
        if location["full_name"] == full_name:
            return {"status": 200, "coordinates": location["coordinates"]}
    raise HTTPException(status_code=404, detail="Selected location not found in recent search results")


@app.get("/horoscope/planet-details")
async def get_planet_details(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_planet_details(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/horoscope/ascendant-report")
async def get_ascendant_report(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = ascendant_report(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/horoscope/planet-report")
async def get_planet_report(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/05/1990)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 01:37)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    planet: Planet = Query(..., title="Planet", description="Select the planet for the report"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "planet": planet.value,  # Use the selected planet value from Enum
        "lang": lang
    }
    data = fetch_planet_report(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/horoscope/personal-characteristics")
async def get_personal_characteristics(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/05/1990)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 01:37)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_personal_characteristics(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/horoscope/ashtakvarga")
async def get_ashtakvarga(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/05/1990)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 01:37)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_ashtakvarga(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/horoscope/binnashtakvarga")
async def get_binnashtakvarga(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/05/1990)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 01:37)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    planet: Planet = Query(..., title="Planet", description="Select the planet for the Binnashtakvarga report"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "planet": planet.value,  # Use the selected planet value from Enum
        "lang": lang
    }
    data = fetch_binnashtakvarga(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/horoscope/ai-12-month-prediction")
async def get_ai_12_month_prediction(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/05/1990)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 01:37)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    start_date: str = Query(..., title="Start Date", description="Enter start date for prediction in DD/MM/YYYY format (e.g., 09/05/2029)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "start_date": start_date,
        "lang": lang
    }
    data = fetch_ai_12_month_prediction(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/horoscope/planetary-aspects")
async def get_planetary_aspects(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/05/1990)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 01:37)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    aspect_response_type: AspectResponseType = Query(..., title="Aspect Response Type", description="Select the response type for aspects"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "aspect_response_type": aspect_response_type.value,  # Use the selected response type value from Enum
        "lang": lang
    }
    data = fetch_planetary_aspects(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/horoscope/planets-in-houses")
async def get_planets_in_houses(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/05/1990)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 01:37)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_planets_in_houses(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/horoscope/divisional-charts")
async def get_divisional_charts(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 01/05/2025)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 13:06)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    response_type: ResponseType = Query(..., title="Response Type", description="Select the response type for the chart data"),
    div: DivisionalChart = Query(..., title="Divisional Chart", description="Select the divisional chart type"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "response_type": response_type.value,  # Use the selected response type value from Enum
        "div": div.value,  # Use the selected divisional chart value from Enum
        "lang": lang
    }
    data = fetch_divisional_charts(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/horoscope/chart-image")
async def get_chart_image(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    style: ChartStyle = Query(..., title="Chart Style", description="Select the chart style"),
    div: DivisionalChart = Query(..., title="Divisional Chart", description="Select the divisional chart type"),
    color: str = Query("%23ff3366", title="Color", description="Enter hash color code for the chart (use %23 instead of #, e.g., %23ff3366)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    # Construct params dictionary in the specified order
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang,
        "div": div.value,  # Use the selected divisional chart value from Enum
        "style": style.value,  # Use the selected style value from Enum
        "color": color  # Color code as provided by user (with %23 prefix)
    }
    data = fetch_chart_image(api_key, params)
    # Return the raw SVG content as the response
    return {"status": 200, "response": data}

@app.get("/horoscope/ashtakvarga-chart-image")
async def get_ashtakvarga_chart_image(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    style: ChartStyle = Query(..., title="Chart Style", description="Select the chart style"),
    planet: Planet = Query(..., title="Planet", description="Select the planet for the Ashtakvarga chart"),
    color: str = Query("%23ff3366", title="Color", description="Enter hash color code for the chart (use %23 instead of #, e.g., %23ff3366)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    # Construct params dictionary in the specified order
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "style": style.value,  # Use the selected style value from Enum
        "color": color,  # Color code as provided by user (with %23 prefix)
        "lang": lang,
        "planet": planet.value  # Use the selected planet value from Enum
    }
    data = fetch_ashtakvarga_chart_image(api_key, params)
    # Return the raw SVG content as the response
    return {"status": 200, "response": data}


@app.get("/horoscope/western-planets")
async def get_western_planets(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_western_planets(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/prediction/daily-sun")
async def get_daily_sun(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    split: SplitOption = Query(..., title="Split", description="Select whether to split the prediction"),
    type: PredictionType = Query(..., title="Type", description="Select the type of prediction"),
    zodiac: str = Query(..., title="Zodiac Sign", description="Select the zodiac sign", enum=ZODIAC_NAMES),
    date: str = Query(..., title="Date", description="Enter date in DD/MM/YYYY format (e.g., 09/09/1998)"),
    api_key: str = Depends(get_api_key)
):
        # Map the selected Zodiac name to its numeric value
    zodiac_value = ZODIAC_MAPPING.get(zodiac)
    if zodiac_value is None:
        raise HTTPException(status_code=400, detail="Invalid Zodiac sign selected")
    
    params = {
        "lang": lang,
        "split": split.value == "true",  # Convert string 'true'/'false' to boolean
        "type": type.value,
        "zodiac": zodiac_value,  # Use the numeric value (1 to 12)
        "date": date
    }
    data = fetch_daily_sun(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/prediction/daily-moon")
async def get_daily_moon(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    split: SplitOption = Query(..., title="Split", description="Select whether to split the prediction"),
    type: PredictionType = Query(..., title="Type", description="Select the type of prediction"),
    zodiac: str = Query(..., title="Zodiac Sign", description="Select the zodiac sign", enum=ZODIAC_NAMES),
    date: str = Query(..., title="Date", description="Enter date in DD/MM/YYYY format (e.g., 09/09/1998)"),
    api_key: str = Depends(get_api_key)
):
    # Map the selected Zodiac name to its numeric value
    zodiac_value = ZODIAC_MAPPING.get(zodiac)
    if zodiac_value is None:
        raise HTTPException(status_code=400, detail="Invalid Zodiac sign selected")
    
    params = {
        "lang": lang,
        "split": split.value == "true",  # Convert string 'true'/'false' to boolean
        "type": type.value,
        "zodiac": zodiac_value,  # Use the numeric value (1 to 12) associated with the selected name
        "date": date
    }
    data = fetch_daily_moon(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/prediction/daily-nakshatra")
async def get_daily_nakshatra(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    date: str = Query(..., title="Date", description="Enter date in DD/MM/YYYY format (e.g., 09/09/1998)"),
    nakshatra: str = Query(..., title="Nakshatra", description="Select the Nakshatra", enum=NAKSHATRA_NAMES),
    api_key: str = Depends(get_api_key)
):
    # Map the selected Nakshatra name to its numeric value
    nakshatra_value = NAKSHATRA_MAPPING.get(nakshatra)
    if nakshatra_value is None:
        raise HTTPException(status_code=400, detail="Invalid Nakshatra selected")
    
    params = {
        "lang": lang,
        "date": date,
        "nakshatra": nakshatra_value  # Use the numeric value (1 to 27) associated with the selected name
    }
    data = fetch_daily_nakshatra(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}



@app.get("/prediction/weekly-sun")
async def get_weekly_sun(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    type: PredictionType = Query(..., title="Type", description="Select the type of prediction"),
    split: SplitOption = Query(..., title="Split", description="Select whether to split the prediction"),
    week: WeekOption = Query(..., title="Week", description="Select the week for prediction"),
    zodiac: str = Query(..., title="Zodiac Sign", description="Select the zodiac sign", enum=ZODIAC_NAMES),
    api_key: str = Depends(get_api_key)
):
    # Map the selected Zodiac name to its numeric value
    zodiac_value = ZODIAC_MAPPING.get(zodiac)
    if zodiac_value is None:
        raise HTTPException(status_code=400, detail="Invalid Zodiac sign selected")
    
    params = {
        "lang": lang,
        "type": type.value,
        "split": split.value == "true",  # Convert string 'true'/'false' to boolean
        "week": week.value,
        "zodiac": zodiac_value  # Use the numeric value (1 to 12) associated with the selected name
    }
    data = fetch_weekly_sun(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/prediction/weekly-moon")
async def get_weekly_moon(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    type: PredictionType = Query(..., title="Type", description="Select the type of prediction"),
    split: SplitOption = Query(..., title="Split", description="Select whether to split the prediction"),
    week: WeekOption = Query(..., title="Week", description="Select the week for prediction"),
    zodiac: str = Query(..., title="Zodiac Sign", description="Select the zodiac sign", enum=ZODIAC_NAMES),
    api_key: str = Depends(get_api_key)
):
    # Map the selected Zodiac name to its numeric value
    zodiac_value = ZODIAC_MAPPING.get(zodiac)
    if zodiac_value is None:
        raise HTTPException(status_code=400, detail="Invalid Zodiac sign selected")
    
    params = {
        "lang": lang,
        "type": type.value,
        "split": split.value == "true",  # Convert string 'true'/'false' to boolean
        "week": week.value,
        "zodiac": zodiac_value  # Use the numeric value (1 to 12) associated with the selected name
    }
    data = fetch_weekly_moon(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/prediction/yearly")
async def get_yearly_prediction(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    zodiac: str = Query(..., title="Zodiac Sign", description="Select the zodiac sign", enum=ZODIAC_NAMES),
    year: str = Query(..., title="Year", description="Enter the year for prediction (e.g., 2025)"),
    api_key: str = Depends(get_api_key)
):
    # Map the selected Zodiac name to its numeric value
    zodiac_value = ZODIAC_MAPPING.get(zodiac)
    if zodiac_value is None:
        raise HTTPException(status_code=400, detail="Invalid Zodiac sign selected")
    
    params = {
        "lang": lang,
        "zodiac": zodiac_value,  # Use the numeric value (1 to 12) associated with the selected name
        "year": year
    }
    data = fetch_yearly_prediction(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/prediction/biorhythm")
async def get_biorhythm(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "lang": lang,
        "dob": dob
    }
    data = fetch_biorhythm(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/prediction/day-number")
async def get_day_number(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "lang": lang,
        "dob": dob
    }
    data = fetch_day_number(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/prediction/numerology")
async def get_numerology(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    date: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    name: str = Query(..., title="Name", description="Enter full name (e.g., Akash Soni)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "lang": lang,
        "date": date,
        "name": name
    }
    data = fetch_numerology(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/extended-horoscope/find-moon-sign")
async def get_find_moon_sign(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_find_moon_sign(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/extended-horoscope/find-sun-sign")
async def get_find_sun_sign(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_find_sun_sign(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/extended-horoscope/find-ascendant")
async def get_find_ascendant(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_find_ascendant(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/current-sade-sati")
async def get_current_sade_sati(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_current_sade_sati(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/extended-horoscope/sade-sati-table")
async def get_sade_sati_table(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_sade_sati_table(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/extended-horoscope/extended-kundli-details")
async def get_extended_kundli_details(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_extended_kundli_details(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/yoga-list")
async def get_yoga_list(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_yoga_list(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/friendship")
async def get_friendship(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_friendship(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/extended-horoscope/kp-planets")
async def get_kp_planets(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_kp_planets(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/kp-houses")
async def get_kp_houses(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_kp_houses(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/shad-bala")
async def get_shad_bala(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_shad_bala(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/arudha-padas")
async def get_arudha_padas(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_arudha_padas(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/jaimini-karakas")
async def get_jaimini_karakas(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_jaimini_karakas(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/gem-suggestion")
async def get_gem_suggestion(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_gem_suggestion(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/numero-table")
async def get_numero_table(
    name: str = Query(..., title="Full Name", description="Enter full name (e.g., Akash Soni)"),
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "name": name,
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_numero_table(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/rudraksh-suggestion")
async def get_rudraksh_suggestion(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_rudraksh_suggestion(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/varshapal-details")
async def get_varshapal_details(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_varshapal_details(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/varshapal-month-chart")
async def get_varshapal_month_chart(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_varshapal_month_chart(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/extended-horoscope/varshapal-year-chart")
async def get_varshapal_year_chart(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_varshapal_year_chart(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dosha/mangal-dosh")
async def get_mangal_dosha(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_mangal_dosha(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dosha/kaalsarp-dosh")
async def get_kaalsarp_dosha(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_kaalsarp_dosha(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dosha/manglik-dosh")
async def get_manglik_dosha(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_manglik_dosha(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dosha/pitra-dosh")
async def get_pitra_dosha(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_pitra_dosha(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dosha/papasamaya")
async def get_papasamya(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_papasamya(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dashas/maha-dasha")
async def get_maha_dasha(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_maha_dasha(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dashas/maha-dasha-predictions")
async def get_maha_dasha_predictions(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_maha_dasha_predictions(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dashas/antar-dasha")
async def get_antar_dasha(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_antar_dasha(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dashas/char-dasha-current")
async def get_char_dasha_current(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_char_dasha_current(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dashas/char-dasha-main")
async def get_char_dasha_main(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_char_dasha_main(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.get("/dashas/char-dasha-sub")
async def get_char_dasha_sub(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_char_dasha_sub(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dashas/current-mahadasha-full")
async def get_current_mahadasha_full(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_current_mahadasha_full(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dashas/current-mahadasha")
async def get_current_mahadasha(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_current_mahadasha(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dashas/paryantar-dasha")
async def get_paryantar_dasha(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_paryantar_dasha(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dashas/yogini-dasha-main")
async def get_yogini_dasha_main(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_yogini_dasha_main(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/dashas/yogini-dasha-sub")
async def get_yogini_dasha_sub(
    dob: str = Query(..., title="Date of Birth", description="Enter date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    tob: str = Query(..., title="Time of Birth", description="Enter time of birth in HH:MM format (e.g., 19:08)"),
    lat: str = Query(..., title="Latitude", description="Enter latitude of the location (e.g., 26.46523000)"),
    lon: str = Query(..., title="Longitude", description="Enter longitude of the location (e.g., 80.34975000)"),
    tz: float = Query(..., title="Timezone Offset", description="Enter timezone offset (e.g., 5.5 for IST)"),
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "dob": dob,
        "tob": tob,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "lang": lang
    }
    data = fetch_yogini_dasha_sub(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/matching/ashtakoot")
async def get_ashtakoot_matching(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    boy_dob: str = Query(..., title="Boy's Date of Birth", description="Enter boy's date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    boy_tob: str = Query(..., title="Boy's Time of Birth", description="Enter boy's time of birth in HH:MM format (e.g., 19:08)"),
    boy_tz: float = Query(..., title="Boy's Timezone Offset", description="Enter boy's timezone offset (e.g., 5.5 for IST)"),
    boy_lat: str = Query(..., title="Boy's Latitude", description="Enter boy's birth place latitude (e.g., 26.46523000)"),
    boy_lon: str = Query(..., title="Boy's Longitude", description="Enter boy's birth place longitude (e.g., 80.34975000)"),
    girl_dob: str = Query(..., title="Girl's Date of Birth", description="Enter girl's date of birth in DD/MM/YYYY format (e.g., 25/07/1997)"),
    girl_tob: str = Query(..., title="Girl's Time of Birth", description="Enter girl's time of birth in HH:MM format (e.g., 14:07)"),
    girl_tz: float = Query(..., title="Girl's Timezone Offset", description="Enter girl's timezone offset (e.g., 5.5 for IST)"),
    girl_lat: str = Query(..., title="Girl's Latitude", description="Enter girl's birth place latitude (e.g., 26.46523000)"),
    girl_lon: str = Query(..., title="Girl's Longitude", description="Enter girl's birth place longitude (e.g., 80.34975000)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "lang": lang,
        "boy_dob": boy_dob,
        "boy_tob": boy_tob,
        "boy_tz": boy_tz,
        "boy_lat": boy_lat,
        "boy_lon": boy_lon,
        "girl_dob": girl_dob,
        "girl_tob": girl_tob,
        "girl_tz": girl_tz,
        "girl_lat": girl_lat,
        "girl_lon": girl_lon
    }
    data = fetch_ashtakoot(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/matching/ashtakoot-with-astro-details")
async def get_ashtakoot_with_astro_details(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    boy_dob: str = Query(..., title="Boy's Date of Birth", description="Enter boy's date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    boy_tob: str = Query(..., title="Boy's Time of Birth", description="Enter boy's time of birth in HH:MM format (e.g., 19:08)"),
    boy_tz: float = Query(..., title="Boy's Timezone Offset", description="Enter boy's timezone offset (e.g., 5.5 for IST)"),
    boy_lat: str = Query(..., title="Boy's Latitude", description="Enter boy's birth place latitude (e.g., 26.46523000)"),
    boy_lon: str = Query(..., title="Boy's Longitude", description="Enter boy's birth place longitude (e.g., 80.34975000)"),
    girl_dob: str = Query(..., title="Girl's Date of Birth", description="Enter girl's date of birth in DD/MM/YYYY format (e.g., 25/07/1997)"),
    girl_tob: str = Query(..., title="Girl's Time of Birth", description="Enter girl's time of birth in HH:MM format (e.g., 14:07)"),
    girl_tz: float = Query(..., title="Girl's Timezone Offset", description="Enter girl's timezone offset (e.g., 5.5 for IST)"),
    girl_lat: str = Query(..., title="Girl's Latitude", description="Enter girl's birth place latitude (e.g., 26.46523000)"),
    girl_lon: str = Query(..., title="Girl's Longitude", description="Enter girl's birth place longitude (e.g., 80.34975000)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "lang": lang,
        "boy_dob": boy_dob,
        "boy_tob": boy_tob,
        "boy_tz": boy_tz,
        "boy_lat": boy_lat,
        "boy_lon": boy_lon,
        "girl_dob": girl_dob,
        "girl_tob": girl_tob,
        "girl_tz": girl_tz,
        "girl_lat": girl_lat,
        "girl_lon": girl_lon
    }
    data = fetch_ashtakoot_with_astro_details(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/matching/dashakoot")
async def get_dashakoot_matching(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    boy_dob: str = Query(..., title="Boy's Date of Birth", description="Enter boy's date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    boy_tob: str = Query(..., title="Boy's Time of Birth", description="Enter boy's time of birth in HH:MM format (e.g., 19:08)"),
    boy_tz: float = Query(..., title="Boy's Timezone Offset", description="Enter boy's timezone offset (e.g., 5.5 for IST)"),
    boy_lat: str = Query(..., title="Boy's Latitude", description="Enter boy's birth place latitude (e.g., 26.46523000)"),
    boy_lon: str = Query(..., title="Boy's Longitude", description="Enter boy's birth place longitude (e.g., 80.34975000)"),
    girl_dob: str = Query(..., title="Girl's Date of Birth", description="Enter girl's date of birth in DD/MM/YYYY format (e.g., 25/07/1997)"),
    girl_tob: str = Query(..., title="Girl's Time of Birth", description="Enter girl's time of birth in HH:MM format (e.g., 14:07)"),
    girl_tz: float = Query(..., title="Girl's Timezone Offset", description="Enter girl's timezone offset (e.g., 5.5 for IST)"),
    girl_lat: str = Query(..., title="Girl's Latitude", description="Enter girl's birth place latitude (e.g., 26.46523000)"),
    girl_lon: str = Query(..., title="Girl's Longitude", description="Enter girl's birth place longitude (e.g., 80.34975000)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "lang": lang,
        "boy_dob": boy_dob,
        "boy_tob": boy_tob,
        "boy_tz": boy_tz,
        "boy_lat": boy_lat,
        "boy_lon": boy_lon,
        "girl_dob": girl_dob,
        "girl_tob": girl_tob,
        "girl_tz": girl_tz,
        "girl_lat": girl_lat,
        "girl_lon": girl_lon
    }
    data = fetch_dashakoot(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/matching/dashakoot-with-astro-details")
async def get_dashakoot_with_astro_details(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    boy_dob: str = Query(..., title="Boy's Date of Birth", description="Enter boy's date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    boy_tob: str = Query(..., title="Boy's Time of Birth", description="Enter boy's time of birth in HH:MM format (e.g., 19:08)"),
    boy_tz: float = Query(..., title="Boy's Timezone Offset", description="Enter boy's timezone offset (e.g., 5.5 for IST)"),
    boy_lat: str = Query(..., title="Boy's Latitude", description="Enter boy's birth place latitude (e.g., 26.46523000)"),
    boy_lon: str = Query(..., title="Boy's Longitude", description="Enter boy's birth place longitude (e.g., 80.34975000)"),
    girl_dob: str = Query(..., title="Girl's Date of Birth", description="Enter girl's date of birth in DD/MM/YYYY format (e.g., 25/07/1997)"),
    girl_tob: str = Query(..., title="Girl's Time of Birth", description="Enter girl's time of birth in HH:MM format (e.g., 14:07)"),
    girl_tz: float = Query(..., title="Girl's Timezone Offset", description="Enter girl's timezone offset (e.g., 5.5 for IST)"),
    girl_lat: str = Query(..., title="Girl's Latitude", description="Enter girl's birth place latitude (e.g., 26.46523000)"),
    girl_lon: str = Query(..., title="Girl's Longitude", description="Enter girl's birth place longitude (e.g., 80.34975000)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "lang": lang,
        "boy_dob": boy_dob,
        "boy_tob": boy_tob,
        "boy_tz": boy_tz,
        "boy_lat": boy_lat,
        "boy_lon": boy_lon,
        "girl_dob": girl_dob,
        "girl_tob": girl_tob,
        "girl_tz": girl_tz,
        "girl_lat": girl_lat,
        "girl_lon": girl_lon
    }
    data = fetch_dashakoot_with_astro_details(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/matching/aggregate-match")
async def get_aggregate_match(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    boy_dob: str = Query(..., title="Boy's Date of Birth", description="Enter boy's date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    boy_tob: str = Query(..., title="Boy's Time of Birth", description="Enter boy's time of birth in HH:MM format (e.g., 19:08)"),
    boy_tz: float = Query(..., title="Boy's Timezone Offset", description="Enter boy's timezone offset (e.g., 5.5 for IST)"),
    boy_lat: str = Query(..., title="Boy's Latitude", description="Enter boy's birth place latitude (e.g., 26.46523000)"),
    boy_lon: str = Query(..., title="Boy's Longitude", description="Enter boy's birth place longitude (e.g., 80.34975000)"),
    girl_dob: str = Query(..., title="Girl's Date of Birth", description="Enter girl's date of birth in DD/MM/YYYY format (e.g., 25/07/1997)"),
    girl_tob: str = Query(..., title="Girl's Time of Birth", description="Enter girl's time of birth in HH:MM format (e.g., 14:07)"),
    girl_tz: float = Query(..., title="Girl's Timezone Offset", description="Enter girl's timezone offset (e.g., 5.5 for IST)"),
    girl_lat: str = Query(..., title="Girl's Latitude", description="Enter girl's birth place latitude (e.g., 26.46523000)"),
    girl_lon: str = Query(..., title="Girl's Longitude", description="Enter girl's birth place longitude (e.g., 80.34975000)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "lang": lang,
        "boy_dob": boy_dob,
        "boy_tob": boy_tob,
        "boy_tz": boy_tz,
        "boy_lat": boy_lat,
        "boy_lon": boy_lon,
        "girl_dob": girl_dob,
        "girl_tob": girl_tob,
        "girl_tz": girl_tz,
        "girl_lat": girl_lat,
        "girl_lon": girl_lon
    }
    data = fetch_aggregate_match(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/matching/rajju-vedha-details")
async def get_rajju_vedha_details(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    boy_dob: str = Query(..., title="Boy's Date of Birth", description="Enter boy's date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    boy_tob: str = Query(..., title="Boy's Time of Birth", description="Enter boy's time of birth in HH:MM format (e.g., 19:08)"),
    boy_tz: float = Query(..., title="Boy's Timezone Offset", description="Enter boy's timezone offset (e.g., 5.5 for IST)"),
    boy_lat: str = Query(..., title="Boy's Latitude", description="Enter boy's birth place latitude (e.g., 26.46523000)"),
    boy_lon: str = Query(..., title="Boy's Longitude", description="Enter boy's birth place longitude (e.g., 80.34975000)"),
    girl_dob: str = Query(..., title="Girl's Date of Birth", description="Enter girl's date of birth in DD/MM/YYYY format (e.g., 25/07/1997)"),
    girl_tob: str = Query(..., title="Girl's Time of Birth", description="Enter girl's time of birth in HH:MM format (e.g., 14:07)"),
    girl_tz: float = Query(..., title="Girl's Timezone Offset", description="Enter girl's timezone offset (e.g., 5.5 for IST)"),
    girl_lat: str = Query(..., title="Girl's Latitude", description="Enter girl's birth place latitude (e.g., 26.46523000)"),
    girl_lon: str = Query(..., title="Girl's Longitude", description="Enter girl's birth place longitude (e.g., 80.34975000)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "lang": lang,
        "boy_dob": boy_dob,
        "boy_tob": boy_tob,
        "boy_tz": boy_tz,
        "boy_lat": boy_lat,
        "boy_lon": boy_lon,
        "girl_dob": girl_dob,
        "girl_tob": girl_tob,
        "girl_tz": girl_tz,
        "girl_lat": girl_lat,
        "girl_lon": girl_lon
    }
    data = fetch_rajju_vedha_details(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/matching/papasamaya-match")
async def get_papasamaya_match(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    boy_dob: str = Query(..., title="Boy's Date of Birth", description="Enter boy's date of birth in DD/MM/YYYY format (e.g., 09/09/1998)"),
    boy_tob: str = Query(..., title="Boy's Time of Birth", description="Enter boy's time of birth in HH:MM format (e.g., 19:08)"),
    boy_tz: float = Query(..., title="Boy's Timezone Offset", description="Enter boy's timezone offset (e.g., 5.5 for IST)"),
    boy_lat: str = Query(..., title="Boy's Latitude", description="Enter boy's birth place latitude (e.g., 26.46523000)"),
    boy_lon: str = Query(..., title="Boy's Longitude", description="Enter boy's birth place longitude (e.g., 80.34975000)"),
    girl_dob: str = Query(..., title="Girl's Date of Birth", description="Enter girl's date of birth in DD/MM/YYYY format (e.g., 25/07/1997)"),
    girl_tob: str = Query(..., title="Girl's Time of Birth", description="Enter girl's time of birth in HH:MM format (e.g., 14:07)"),
    girl_tz: float = Query(..., title="Girl's Timezone Offset", description="Enter girl's timezone offset (e.g., 5.5 for IST)"),
    girl_lat: str = Query(..., title="Girl's Latitude", description="Enter girl's birth place latitude (e.g., 26.46523000)"),
    girl_lon: str = Query(..., title="Girl's Longitude", description="Enter girl's birth place longitude (e.g., 80.34975000)"),
    api_key: str = Depends(get_api_key)
):
    params = {
        "lang": lang,
        "boy_dob": boy_dob,
        "boy_tob": boy_tob,
        "boy_tz": boy_tz,
        "boy_lat": boy_lat,
        "boy_lon": boy_lon,
        "girl_dob": girl_dob,
        "girl_tob": girl_tob,
        "girl_tz": girl_tz,
        "girl_lat": girl_lat,
        "girl_lon": girl_lon
    }
    data = fetch_papasamaya_match(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/matching/nakshatra-match")
async def get_nakshatra_match(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    boy_star: str = Query(..., title="Boy's Nakshatra", description="Select the boy's Nakshatra", enum=NAKSHATRA_NAMES),
    girl_star: str = Query(..., title="Girl's Nakshatra", description="Select the girl's Nakshatra", enum=NAKSHATRA_NAMES),
    api_key: str = Depends(get_api_key)
):
    # Map the selected Nakshatra names to their numeric values
    boy_star_value = NAKSHATRA_MAPPING.get(boy_star)
    girl_star_value = NAKSHATRA_MAPPING.get(girl_star)
    
    if boy_star_value is None or girl_star_value is None:
        raise HTTPException(status_code=400, detail="Invalid Nakshatra selection")
    
    params = {
        "lang": lang,
        "boy_star": boy_star_value,
        "girl_star": girl_star_value
    }
    data = fetch_nakshatra_match(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}

@app.get("/matching/western-match")
async def get_western_match(
    lang: str = Query(..., title="Language", description="Enter language code (e.g., 'en' for English)"),
    boy_sign: str = Query(..., title="Boy's Zodiac Sign", description="Select the boy's zodiac sign", enum=ZODIAC_NAMES),
    girl_sign: str = Query(..., title="Girl's Zodiac Sign", description="Select the girl's zodiac sign", enum=ZODIAC_NAMES),
    api_key: str = Depends(get_api_key)
):
    # Map the selected Zodiac names to their numeric values
    boy_sign_value = ZODIAC_MAPPING.get(boy_sign)
    girl_sign_value = ZODIAC_MAPPING.get(girl_sign)
    
    if boy_sign_value is None or girl_sign_value is None:
        raise HTTPException(status_code=400, detail="Invalid Zodiac sign selection")
    
    params = {
        "lang": lang,
        "boy_sign": boy_sign_value,
        "girl_sign": girl_sign_value
    }
    data = fetch_western_match(api_key, params)
    if data.get("status") != 200:
        raise HTTPException(status_code=400, detail="Invalid request parameters to external API")
    return {"status": 200, "response": data.get("response", {})}


@app.post("/chat/prediction")
async def chat_prediction(
    data: ChatPredictionRequest,
    request: Request,
    response: Response,
    api_key: str = Depends(get_api_key)
):
    # Check for session ID in cookies
    session_id = request.cookies.get("chat_session_id")
    if not session_id:
        # Generate a new session ID if none exists
        session_id = str(uuid4())
        response.set_cookie(
            key="chat_session_id",
            value=session_id,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            max_age=86400  # 24 hours expiration
        )
    
    # Check if session data exists in MongoDB
    session_data = user_chat_sessions.find_one({"session_id": session_id})
    
    if not session_data:
        # Fetch astrological data (as in your current logic)
        user_key = f"{data.name}_{data.dob}_{data.tob}_{data.lat}_{data.lon}"
        stored_data = sessions_collection.find_one({"user_key": user_key})
        needs_refresh = True
        data_age = None
        
        if stored_data:
            last_updated = stored_data.get("last_updated")
            if last_updated:
                data_age = datetime.now() - last_updated
                if data_age < timedelta(hours=24):
                    needs_refresh = False
        
        kundli_params = {
            "dob": data.dob,
            "tob": data.tob,
            "lat": data.lat,
            "lon": data.lon,
            "tz": data.tz,
            "lang": data.lang
        }
        
        if needs_refresh:
            try:
                if not stored_data:  # New user, fetch all data
                    astrological_data = {
                    "planet_details": fetch_planet_details(api_key, kundli_params),
                    "personal_chars": fetch_personal_characteristics(api_key, kundli_params),
                    "mangal_dosh": fetch_mangal_dosha(api_key, kundli_params),
                    "kaalsarp_dosh": fetch_kaalsarp_dosha(api_key, kundli_params),
                    "manglik_dosh": fetch_manglik_dosha(api_key, kundli_params),
                    "pitra_dosh": fetch_pitra_dosha(api_key, kundli_params),
                    "current_mahadasha_full": fetch_current_mahadasha_full(api_key, kundli_params),
                    "shad_bala": fetch_shad_bala(api_key, kundli_params),
                    "current_sade_sati": fetch_current_sade_sati(api_key, kundli_params),
                    "ashtakvarga": fetch_ashtakvarga(api_key, kundli_params),
                    "binnashtakvarga": fetch_binnashtakvarga(api_key, kundli_params),
                    "rudraksh_suggestion": fetch_rudraksh_suggestion(api_key, kundli_params),
                    "gem_suggestions": fetch_gem_suggestion(api_key, kundli_params)
                }
                else:
                    astrological_data = stored_data["astrological_data"]
                    if data_age >= timedelta(days=7):
                        astrological_data.update({
                            "planet_details": fetch_planet_details(api_key, kundli_params),
                            "personal_chars": fetch_personal_characteristics(api_key, kundli_params),
                            "current_mahadasha_full": fetch_current_mahadasha_full(api_key, kundli_params),
                            "current_sade_sati": fetch_current_sade_sati(api_key, kundli_params)
                            # Update other fields as needed
                        })
                    elif data_age >= timedelta(hours=24):
                        astrological_data.update({
                            "planet_details": fetch_planet_details(api_key, kundli_params),
                            "personal_chars": fetch_personal_characteristics(api_key, kundli_params)
                        })
                
                # Update database
                sessions_collection.update_one(
                    {"user_key": user_key},
                    {"$set": {
                        "user_key": user_key,
                        "astrological_data": astrological_data,
                        "last_updated": datetime.now()
                    }},
                    upsert=True
                )
            except Exception as e:
                if stored_data:
                    astrological_data = stored_data["astrological_data"]
                else:
                    raise HTTPException(status_code=500, detail=f"Failed to fetch astrological data: {str(e)}")
        else:
            astrological_data = stored_data["astrological_data"]
        
        # Initialize conversation history with system message and initial user data
        initial_prompt = (
            f"User: {data.name}\n"
            f"Kundli Planet Details: {astrological_data.get('planet_details', {}).get('response', {})}\n"
            f"Personal Characteristics: {astrological_data.get('personal_chars', {}).get('response', {})}\n"
            f"Mangal Dosh: {astrological_data.get('mangal_dosh', {}).get('response', {})}\n"
            f"Kaalsarp Dosh: {astrological_data.get('kaalsarp_dosh', {}).get('response', {})}\n"
            f"Manglik Dosh: {astrological_data.get('manglik_dosh', {}).get('response', {})}\n"
            f"Pitra Dosh: {astrological_data.get('pitra_dosh', {}).get('response', {})}\n"
            f"Current Maha Dasha Full: {astrological_data.get('current_mahadasha_full', {}).get('response', {})}\n"
            f"Shada Bala: {astrological_data.get('shad_bala', {}).get('response', {})}\n"
            f"Current Sade Sati: {astrological_data.get('current_sade_sati', {}).get('response', {})}\n"
            f"Ashtakvarga: {astrological_data.get('ashtakvarga', {}).get('response', {})}\n"
            f"binnashtakvarga: {astrological_data.get('binnashtakvarga', {}).get('response', {})}\n"
            f"Rudraksh Suggestion: {astrological_data.get('rudraksh_suggestion', {}).get('response', {})}\n"
            f"Gem Suggestion: {astrological_data.get('gem_suggestions', {}).get('response', {})}\n"
            f"User Query: {data.query}\n"
            f"Give an expert Vedic astrology prediction in simple language. Do not use hashtags (#), asterisks (*), or any other markdown syntax. Avoid including links. "
        )
        conversation_history = [
            {"role": "system", "content": "You are an expert Vedic astrologer. Provide your response in plain text format without any markdown formatting. Do not use hashtags (#), asterisks (*), or any other markdown syntax. Format your response in simple paragraphs with clean line breaks. Use bullet points with • symbol if needed, but avoid markdown formatting."},
            {"role": "user", "content": initial_prompt}
        ]
        
        # Store session data in MongoDB
        user_chat_sessions.insert_one({
            "session_id": session_id,
            "user_key": user_key,
            "astrological_data": astrological_data,
            "conversation_history": conversation_history,
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(hours=24)
        })
    else:
        # Retrieve existing conversation history
        conversation_history = session_data["conversation_history"]
        astrological_data = session_data["astrological_data"]
        # Append only the new user query to the conversation history
        conversation_history.append(
            {"role": "user", "content": f"User Query: {data.query}"}
        )
        # Update the session in MongoDB
        user_chat_sessions.update_one(
            {"session_id": session_id},
            {"$set": {
                "conversation_history": conversation_history,
                "last_updated": datetime.now()
            }}
        )
    
    # Call Perplexity API with the full conversation history
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "sonar-pro",
        "messages": conversation_history
    }
    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            json=payload,
            headers=headers,
            timeout=300
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Perplexity API error: {resp.text}")
        result = resp.json()
        answer = result["choices"][0]["message"]["content"]
        
        # Append AI response to conversation history in MongoDB
        conversation_history.append(
            {"role": "assistant", "content": answer}
        )
        user_chat_sessions.update_one(
            {"session_id": session_id},
            {"$set": {
                "conversation_history": conversation_history,
                "last_updated": datetime.now()
            }}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get prediction: {str(e)}")
    
    return {"prediction": answer}


# Run the app with: uvicorn main:app --reload
