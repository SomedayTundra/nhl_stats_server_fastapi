import uvicorn
from fastapi import FastAPI
from app.routes.nhl_standings import router as nhl_standings_router

# from app.middleware.timer import timing_middleware
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# app.middleware("http")(timing_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(nhl_standings_router)


# we're running uvicorn right out of main.py to simplify debugging in IDEA
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)