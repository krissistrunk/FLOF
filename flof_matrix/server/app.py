"""FastAPI application — FLOF Matrix Command Center backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from flof_matrix.server.routes.dashboard import router as dashboard_router
from flof_matrix.server.routes.actions import router as actions_router
from flof_matrix.server.ws import websocket_endpoint

app = FastAPI(
    title="FLOF Matrix Command Center",
    version="1.0.0",
    description="Backend API for the FLOF Matrix trading system dashboard",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5185", "http://127.0.0.1:5185"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)
app.include_router(actions_router)

app.add_api_websocket_route("/ws", websocket_endpoint)


@app.get("/")
def root():
    return {"service": "FLOF Matrix Command Center", "version": "1.0.0"}
