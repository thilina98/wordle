# Wordle Game - FastAPI Backend
# REST API with password protection

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid

from game_logic import (
    load_words,
    select_random_word,
    validate_guess,
    evaluate_guess,
    GameState,
    GameResult,
)

# Configuration
GAME_PASSWORD = "secret123"  # In production, use environment variable
WORD_FILE = "words.csv"
MAX_ATTEMPTS = 5

# In-memory game storage (replace with DB in production)
games: Dict[str, GameState] = {}
word_list = load_words(WORD_FILE)

app = FastAPI(title="Wordle API", version="1.0.0")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Password dependency
def verify_password(x_password: str = Header(...)) -> None:
    """Verify password from header"""
    if x_password != GAME_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")


# Request/Response models
class NewGameResponse(BaseModel):
    game_id: str
    max_attempts: int
    message: str = "Game created. Make your first guess!"


class GuessRequest(BaseModel):
    game_id: str
    guess: str


class GuessResponse(BaseModel):
    guess: str
    result: List[str]  # ["green", "yellow", "gray", ...]
    attempt: int
    remaining: int
    is_game_over: bool
    is_won: bool
    target_word: Optional[str] = None
    message: str = ""


class GameStateResponse(BaseModel):
    game_id: str
    attempts: List[Dict[str, Any]]
    max_attempts: int
    attempt_count: int
    remaining_attempts: int
    is_game_over: bool
    is_won: bool
    result: str
    target_word: Optional[str] = None


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}


@app.post("/api/new-game", response_model=NewGameResponse)
async def new_game(password_verified: None = Depends(verify_password)):
    """Create a new game session"""
    target = select_random_word(word_list)
    game_id = str(uuid.uuid4())[:8]  # Short ID for readability
    
    game = GameState(target, word_list, MAX_ATTEMPTS)
    games[game_id] = game
    
    return NewGameResponse(
        game_id=game_id,
        max_attempts=MAX_ATTEMPTS
    )


@app.post("/api/guess", response_model=GuessResponse)
async def make_guess(
    request: GuessRequest,
    password_verified: None = Depends(verify_password)
):
    """Make a guess in an existing game"""
    game = games.get(request.game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    try:
            attempt = game.add_attempt(request.guess)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Build response
    response = GuessResponse(
        guess=attempt["guess"],
        result=attempt["result"],
        attempt=game.attempt_count,
        remaining=game.remaining_attempts,
        is_game_over=game.is_game_over,
        is_won=game.is_won,
        target_word=game.target_word if game.is_game_over else None,
    )
    
    # Add message based on game state
    if game.is_won:
        response.message = f"Congratulations! You won in {game.attempt_count} attempt(s)!"
    elif game.is_game_over:
        response.message = f"Game over! The word was {game.target_word}."
    else:
        response.message = f"Attempt {game.attempt_count}/{MAX_ATTEMPTS}. {game.remaining_attempts} remaining."
    
    return response


@app.get("/api/game/{game_id}", response_model=GameStateResponse)
async def get_game_state(
    game_id: str,
    password_verified: None = Depends(verify_password)
):
    """Get current game state"""
    game = games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    state = game.to_dict()
    state["game_id"] = game_id
    return GameStateResponse(**state)


# For testing: endpoint to list all games (dev only)
@app.get("/api/games")
async def list_games(password_verified: None = Depends(verify_password)):
    """List all active games (dev endpoint)"""
    return {
        gid: game.to_dict() 
        for gid, game in games.items()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)