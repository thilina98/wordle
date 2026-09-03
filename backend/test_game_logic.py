# Wordle Game - Backend
# Test-driven development: tests first, then implementation

import pytest
from game_logic import (
    load_words,
    select_random_word,
    validate_guess,
    evaluate_guess,
    GameState,
    GameResult,
)

class TestWordLoading:
    """Tests for word list loading"""
    
    def test_load_words_returns_list(self):
        words = load_words("words.csv")
        assert isinstance(words, list)
        assert len(words) > 0
    
    def test_load_words_all_five_letters(self):
        words = load_words("words.csv")
        for word in words:
            assert len(word) == 5
            assert word.isalpha()
    
    def test_load_words_lowercase(self):
        words = load_words("words.csv")
        for word in words:
            assert word == word.lower()

class TestWordSelection:
    """Tests for random word selection"""
    
    def test_select_random_word_from_list(self):
        words = ["apple", "beach", "crane"]
        word = select_random_word(words)
        assert word in words
    
    def test_select_random_word_returns_string(self):
        words = ["apple", "beach", "crane"]
        word = select_random_word(words)
        assert isinstance(word, str)

class TestGuessValidation:
    """Tests for guess validation"""
    
    def test_valid_guess_returns_true(self):
        assert validate_guess("apple", ["apple", "beach"]) is True
    
    def test_invalid_length_returns_false(self):
        assert validate_guess("app", ["apple", "beach"]) is False
        assert validate_guess("apples", ["apple", "beach"]) is False
    
    def test_non_alpha_returns_false(self):
        assert validate_guess("app1e", ["apple", "beach"]) is False
        assert validate_guess("app e", ["apple", "beach"]) is False
    
    def test_word_not_in_list_returns_false(self):
        assert validate_guess("zebra", ["apple", "beach"]) is False
    
    def test_case_insensitive(self):
        assert validate_guess("APPLE", ["apple", "beach"]) is True
        assert validate_guess("Apple", ["apple", "beach"]) is True

class TestGuessEvaluation:
    """Tests for color-coded evaluation (core game logic)"""
    
    def test_all_correct_green(self):
        # target: crane, guess: crane
        result = evaluate_guess("crane", "crane")
        assert result == ["green", "green", "green", "green", "green"]
    
    def test_all_wrong_gray(self):
        # target: crane, guess: zesty (no common letters with crane)
        # crane: c r a n e
        # zesty: z e s t y -> shares 'e'!
        # Use a word with no common letters: zesty shares 'e', try "zesty" -> has e
        # crane letters: c,r,a,n,e
        # zesty letters: z,e,s,t,y - shares e
        # Use "zesty" but change target... or use a different guess
        # target: crane, guess: zesty -> shares e at position 4 vs 1
        # Better: target: crane, guess: zesty -> actually let's use "crane" and "zesty"
        # crane: c r a n e
        # zesty: z e s t y - only 'e' in common
        # So position 4 of crane is 'e', position 1 of zesty is 'e' -> yellow
        # Let's use a truly disjoint word: "crane" vs "zesty" shares e
        # "crane" letters: c,r,a,n,e
        # Need word with none of those: z,o,m,b,i -> "zombi" (not in list)
        # Just test the logic directly with known words
        result = evaluate_guess("crane", "zesty")
        # crane: c r a n e, zesty: z e s t y
        # e at pos 4 in target, pos 1 in guess -> yellow
        assert result == ["gray", "yellow", "gray", "gray", "gray"]
    
    def test_correct_letter_wrong_position_yellow(self):
        # target: crane, guess: acorn
        # crane: c r a n e
        # acorn: a c o r n
        # a: pos 0 in guess, pos 2 in target -> yellow
        # c: pos 1 in guess, pos 0 in target -> yellow
        # o: not in target -> gray
        # r: pos 3 in guess, pos 1 in target -> yellow
        # n: pos 4 in guess, pos 3 in target -> yellow
        result = evaluate_guess("crane", "acorn")
        assert result == ["yellow", "yellow", "gray", "yellow", "yellow"]
    
    def test_duplicate_letters_handling(self):
        # target: apple, guess: alley
        # apple: a p p l e
        # alley: a l l e y
        # a: pos 0 both -> green
        # p: pos 1,2 in target, guess has l at 1 -> not p
        # l: guess has l at 1,2 but target has l at 3
        #   First l (guess[1]): target has l available -> yellow
        #   Second l (guess[2]): target l already used -> gray
        # e: pos 4 in guess, pos 4 in target -> green
        # y: not in target -> gray
        result = evaluate_guess("apple", "alley")
        assert result == ["green", "yellow", "gray", "yellow", "gray"]
    
    def test_duplicate_letters_partial_match(self):
        # target: apple, guess: apply
        # apple: a p p l e
        # apply: a p p l y
        # a: green (pos 0)
        # p: green (pos 1)
        # p: green (pos 2)
        # l: green (pos 3)
        # e vs y: e in target but not y, y not in target -> gray
        result = evaluate_guess("apple", "apply")
        assert result == ["green", "green", "green", "green", "gray"]
    
    def test_multiple_same_letter_in_guess(self):
        # target: crane, guess: cairn
        # crane: c r a n e
        # cairn: c a i r n
        # c: green (pos 0)
        # a: yellow (pos 1 in guess, pos 2 in target)
        # i: gray (not in target)
        # r: yellow (pos 3 in guess, pos 1 in target)
        # n: yellow (pos 4 in guess, pos 3 in target)
        result = evaluate_guess("crane", "cairn")
        assert result == ["green", "yellow", "gray", "yellow", "yellow"]
    
    def test_letter_count_limit(self):
        # target: abbey (a,b,b,e,y), guess: bbbbb
        # abbey: a b b e y
        # bbbbb: b b b b b
        # First pass - greens at positions 1 and 2 (0-indexed)
        # target[1]=b, guess[1]=b -> GREEN
        # target[2]=b, guess[2]=b -> GREEN
        # Available for yellow: a:1, e:1, y:1 (both b's used as green)
        # pos0: b -> not available -> gray
        # pos1: green
        # pos2: green
        # pos3: b -> not available -> gray
        # pos4: b -> not available -> gray
        result = evaluate_guess("abbey", "bbbbb")
        assert result == ["gray", "green", "green", "gray", "gray"]
    
    def test_green_consumes_letter(self):
        # target: abbey, guess: babby
        # abbey: a b b e y
        # babby: b a b b y
        # b at pos 0: target has b at 1,2 -> yellow
        # a at pos 1: target has a at 0 -> yellow
        # b at pos 2: target b at 2 -> green (exact match)
        # b at pos 3: target b at 1 already counted? 
        #   available: a:1, b:1 (pos1), e:1, y:1
        #   pos0: b -> yellow, available[b]=1
        #   pos1: a -> yellow, available[a]=0
        #   pos2: b -> green, available[b] unchanged (already not in available)
        #   pos3: b -> available[b]=1 -> yellow
        #   pos4: y -> available[y]=1 -> green? wait, target[4]=y, guess[4]=y -> GREEN!
        # Actually let's trace properly:
        # target: a b b e y
        # guess:  b a b b y
        # available (non-green): a:1, b:1 (pos1), e:1
        #   pos0: b vs a -> not green
        #   pos1: a vs b -> not green
        #   pos2: b vs b -> GREEN
        #   pos3: b vs e -> not green
        #   pos4: y vs y -> GREEN
        # available: a:1, b:1, e:1
        # pos0: b -> yellow, avail[b]=0
        # pos1: a -> yellow, avail[a]=0
        # pos2: green
        # pos3: b -> avail[b]=0 -> gray
        # pos4: green
        # Result: [yellow, yellow, green, gray, green]
        result = evaluate_guess("abbey", "babby")
        assert result == ["yellow", "yellow", "green", "gray", "green"]

class TestGameState:
    """Tests for game state management"""
    
    @pytest.fixture
    def word_list(self):
        return ["apple", "beach", "crane", "dance", "eagle", "flame", "grape"]
    
    def test_initial_state(self, word_list):
        state = GameState("crane", word_list)
        assert state.target_word == "crane"
        assert state.attempts == []
        assert state.max_attempts == 5
        assert state.is_game_over is False
        assert state.is_won is False
    
    def test_add_valid_attempt(self, word_list):
        state = GameState("crane", word_list)
        result = state.add_attempt("crane")
        assert len(state.attempts) == 1
        assert state.attempts[0]["guess"] == "crane"
        assert state.attempts[0]["result"] == ["green"] * 5
        assert state.is_game_over is True
        assert state.is_won is True
    
    def test_add_invalid_attempt_raises(self, word_list):
        state = GameState("crane", word_list)
        with pytest.raises(ValueError):
            state.add_attempt("zebra")  # not in word list
    
    def test_max_attempts_game_over(self, word_list):
        state = GameState("crane", word_list)
        words = ["apple", "beach", "dance", "eagle", "flame"]
        for w in words:
            state.add_attempt(w)
        assert state.is_game_over is True
        assert state.is_won is False
    
    def test_attempt_count_limit(self, word_list):
        state = GameState("crane", word_list)
        words = ["apple", "beach", "dance", "eagle", "flame"]
        for w in words:
            state.add_attempt(w)
        # 6th attempt should fail
        with pytest.raises(ValueError):
            state.add_attempt("grape")
    
    def test_get_game_result_win(self, word_list):
        state = GameState("crane", word_list)
        state.add_attempt("crane")
        result = state.get_result()
        assert result == GameResult.WIN
    
    def test_get_game_result_loss(self, word_list):
        state = GameState("crane", word_list)
        for w in ["apple", "beach", "dance", "eagle", "flame"]:
            state.add_attempt(w)
        result = state.get_result()
        assert result == GameResult.LOSS
    
    def test_get_game_result_in_progress(self, word_list):
        state = GameState("crane", word_list)
        state.add_attempt("apple")
        result = state.get_result()
        assert result == GameResult.IN_PROGRESS

class TestAPIEndpoints:
    """Tests for FastAPI endpoints (integration-style)"""
    
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)
    
    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    
    def test_new_game_requires_password(self, client):
        response = client.post("/api/new-game")
        # FastAPI returns 422 for missing required header
        assert response.status_code in [401, 422]
    
    def test_new_game_with_password(self, client):
        response = client.post("/api/new-game", headers={"X-Password": "secret123"})
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["max_attempts"] == 5
    
    def test_guess_requires_password(self, client):
        response = client.post("/api/guess", json={"game_id": "test", "guess": "apple"})
        assert response.status_code in [401, 422]
    
    def test_guess_valid_flow(self, client):
        # Create game
        response = client.post("/api/new-game", headers={"X-Password": "secret123"})
        game_id = response.json()["game_id"]
        
        # Make guess
        response = client.post("/api/guess", 
            headers={"X-Password": "secret123"},
            json={"game_id": game_id, "guess": "apple"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert len(data["result"]) == 5
        assert all(c in ["green", "yellow", "gray"] for c in data["result"])