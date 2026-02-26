"""Dashboard REST endpoints — read-only snapshots of strategy state."""

from fastapi import APIRouter

from flof_matrix.server.state import FlofState

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard():
    return FlofState().snapshot_dashboard()


@router.get("/positions")
def get_positions():
    return FlofState().snapshot_positions()


@router.get("/trades")
def get_trades():
    return FlofState().snapshot_trades()


@router.get("/scoring")
def get_scoring():
    return FlofState().snapshot_scoring()


@router.get("/risk")
def get_risk():
    return FlofState().snapshot_risk()


@router.get("/config")
def get_config():
    return FlofState().snapshot_config()


@router.get("/config/toggles")
def get_toggles():
    return FlofState().snapshot_toggles()


@router.get("/equity-curve")
def get_equity_curve():
    return FlofState().snapshot_equity_curve()


@router.get("/pois")
def get_pois():
    return FlofState().snapshot_pois()
