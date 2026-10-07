from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Terminal
from app.schemas import TerminalOut

router = APIRouter(prefix="/terminals", tags=["terminals"])


@router.get("", response_model=list[TerminalOut])
def list_terminals(db: Session = Depends(get_db)) -> list[Terminal]:
    return db.query(Terminal).order_by(Terminal.code).all()


@router.get("/{code}", response_model=TerminalOut)
def get_terminal(code: str, db: Session = Depends(get_db)) -> Terminal:
    terminal = db.query(Terminal).filter(Terminal.code == code.upper()).first()
    if not terminal:
        raise HTTPException(status_code=404, detail=f"Terminal {code} not found")
    return terminal
