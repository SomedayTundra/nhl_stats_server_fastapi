import uvicorn
from fastapi import FastAPI
from app.routes.nhl_standings import router as nhl_standings_router
from app.routes.nhl_team_info import router as nhl_team_info_router
from app.routes.nhl_records_for_span import router as nhl_records_for_span_router
from app.routes.user_data import router as user_data_router

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# This is the list of origins that are allowed to make cross-origin requests.
# You can also use a wildcard '*' to allow all origins.
origins = [
    "http://localhost",
    "http://localhost:5173",  # The origin for your React app on your local machine/development environment
    "http://localhost:5174",  # The origin for your React app on your local machine/development environment
    # "https://your-production-frontend.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Cookie", "Origin"],
    max_age=3600,  # Cache preflight response for 1 hour (3600 seconds)
)


app.include_router(nhl_standings_router)            # /api/nhl_standings
app.include_router(nhl_team_info_router)            # /api/nhl_team_info
app.include_router(nhl_records_for_span_router)     # /api/nhl_records_for_span
app.include_router(user_data_router)                # /api/user_data


# we're running uvicorn right out of main.py to simplify debugging in IDEA
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
