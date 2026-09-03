# Wordle Game - Core Game Logic
# Pure functions and classes for game mechanics, no framework dependencies

import csv
import random
from enum import Enum
from typing import List, Dict, Any, Optional


class GameResult(Enum):
    """Game outcome states"""
    IN_PROGRESS = "in_progress"
    WIN = "win"
    LOSS = "loss"


def load_words(filepath: str) -> List[str]:
    """Load 5-letter words from CSV file.
    
    Args:
        filepath: Path to CSV file with one word per row
        
    Returns:
        List of lowercase 5-letter words
    """
    words = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if row:  # skip empty rows
                word = row[0].strip().lower()
                if len(word) == 5 and word.isalpha():
                    words.append(word)
    return words


def select_random_word(words: List[str]) -> str:
    """Select a random word from the word list.
    
    Args:
        words: List of valid words
        
    Returns:
        Randomly selected word
    """
    return random.choice(words)


def validate_guess(guess: str, word_list: List[str]) -> bool:
    """Validate that guess is a valid 5-letter word in the word list.
    
    Args:
        guess: Player's guess
        word_list: List of valid words
        
    Returns:
        True if valid, False otherwise
    """
    if not guess or len(guess) != 5:
        return False
    if not guess.isalpha():
        return False
    return guess.lower() in word_list


def evaluate_guess(target: str, guess: str) -> List[str]:
    """Evaluate guess against target word with Wordle color coding.
    
    Rules (official Wordle algorithm):
    - Green: correct letter in correct position
    - Yellow: correct letter in wrong position (counts matter!)
    - Gray: letter not in target (or all instances already matched)
    
    Algorithm:
    1. First pass: identify exact matches (green), track remaining target letters
    2. Second pass: for non-green positions, check if letter exists in remaining target
    
    Args:
        target: Target word
        guess: Player's guess
        
    Returns:
        List of 5 color strings: "green", "yellow", or "gray"
    """
    target = target.lower()
    guess = guess.lower()
    
    result = ["gray"] * 5
    target_chars = list(target)
    guess_chars = list(guess)
    
    # Count letters in target that are NOT in correct position
    # These are available for yellow matches
    available = {}
    for i, c in enumerate(target_chars):
        if c != guess_chars[i]:  # Not a green match
            available[c] = available.get(c, 0) + 1
    
    # First pass: mark greens
    for i in range(5):
        if guess_chars[i] == target_chars[i]:
            result[i] = "green"
            guess_chars[i] = ""  # Mark as processed
    
    # Second pass: mark yellows from available pool
    for i in range(5):
        if not guess_chars[i]:  # Already processed as green
            continue
        char = guess_chars[i]
        if available.get(char, 0) > 0:
            result[i] = "yellow"
            available[char] -= 1
    
    return result


class GameState:
    """Manages a single game session state"""
    
    def __init__(self, target_word: str, word_list: List[str], max_attempts: int = 5):
        """Initialize game state.
        
        Args:
            target_word: The word to guess
            word_list: Valid word list for validation
            max_attempts: Maximum number of guesses allowed
        """
        self.target_word = target_word.lower()
        self.word_list = word_list
        self.max_attempts = max_attempts
        self.attempts: List[Dict[str, Any]] = []  # List of {"guess": str, "result": List[str]}
    
    @property
    def is_game_over(self) -> bool:
        """Check if game has ended (won or max attempts reached)"""
        return self.is_won or len(self.attempts) >= self.max_attempts
    
    @property
    def is_won(self) -> bool:
        """Check if player has won"""
        if not self.attempts:
            return False
        return self.attempts[-1]["guess"] == self.target_word
    
    @property
    def attempt_count(self) -> int:
        """Number of attempts made"""
        return len(self.attempts)
    
    @property
    def remaining_attempts(self) -> int:
        """Attempts remaining"""
        return max(0, self.max_attempts - len(self.attempts))
    
    def add_attempt(self, guess: str) -> Dict[str, Any]:
        """Add a guess attempt and return evaluation result.
        
        Args:
            guess: Player's guess
            
        Returns:
            Dict with guess and color-coded result
            
        Raises:
            ValueError: If guess is invalid or game is over
        """
        if self.is_game_over:
            raise ValueError("Game is already over")
        
        if not validate_guess(guess, self.word_list):
            raise ValueError("Invalid guess: not a valid 5-letter word")
        
        guess = guess.lower()
        result = evaluate_guess(self.target_word, guess)
        
        attempt = {
            "guess": guess,
            "result": result
        }
        self.attempts.append(attempt)
        return attempt
    
    def get_result(self) -> GameResult:
        """Get current game result"""
        if self.is_won:
            return GameResult.WIN
        if self.is_game_over:
            return GameResult.LOSS
        return GameResult.IN_PROGRESS
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize game state for API response"""
        return {
            "target_word": self.target_word if self.is_game_over else None,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "attempt_count": self.attempt_count,
            "remaining_attempts": self.remaining_attempts,
            "is_game_over": self.is_game_over,
            "is_won": self.is_won,
            "result": self.get_result().value
        }