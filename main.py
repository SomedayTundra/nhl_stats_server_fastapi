import os

# load a local .env (if present) before anything imports app.constants.mongo_db_constants,
# which reads MONGO_URI at import time. No-op in production where real env vars are set.
from dotenv import load_dotenv

load_dotenv()

import uvicorn
from fastapi import FastAPI

from app.routes.nhl_playoffs import router as nhl_playoffs_router
from app.routes.nhl_standings import router as nhl_standings_router
from app.routes.nhl_team_info import router as nhl_team_info_router
from app.routes.season_info import router as season_info_router
from app.routes.user_data import router as user_data_router

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Allowed browser origins for cross-origin requests. Production sets CORS_ALLOW_ORIGINS to a
# comma-separated list (e.g. "https://somedaytundra.com,https://www.somedaytundra.com"); with it
# unset we fall back to the local dev origins. allow_credentials=True rules out a "*" wildcard.
_default_origins = "http://localhost,http://localhost:5173"
origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", _default_origins).split(",") if o.strip()]

# Starlette types add_middleware() with a ParamSpec that PyCharm's checker can't resolve, so it
# wrongly flags CORSMiddleware below. The call is correct.
# noinspection PyTypeChecker
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Cookie", "Origin"],
    max_age=3600,  # Cache preflight response for 1 hour (3600 seconds)
)


@app.get("/health", tags=["health"])
def health():
    """Liveness/readiness probe: confirms the process is up and MongoDB is reachable."""
    from app.constants import mongo_db_constants as mongo

    mongo.client.admin.command("ping")
    return {"status": "ok"}


app.include_router(nhl_playoffs_router)             # /api/playoffs
app.include_router(nhl_standings_router)            # /api/nhl_standings
app.include_router(nhl_team_info_router)            # /api/nhl_team_info
app.include_router(season_info_router)              # /api/season_info
app.include_router(user_data_router)                # /api/user_data


# we're running uvicorn right out of main.py to simplify debugging in IDEA
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        ws="none",  # no WebSocket routes; skip loading uvicorn's ws backend (and its deprecation noise)
    )
