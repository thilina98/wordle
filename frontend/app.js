/**
 * Wordle Game - Frontend Application
 * Vanilla JS, mobile-responsive, keyboard accessible
 * Communicates with FastAPI backend via REST API
 */

// ============================================
// CONFIGURATION
// ============================================
const API_BASE = ''; // Same origin
const PASSWORD = 'secret123';
const MAX_ATTEMPTS = 5;
const WORD_LENGTH = 5;

// Keyboard layout
const KEYBOARD_LAYOUT = [
    ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
    ['enter', 'z', 'x', 'c', 'v', 'b', 'n', 'm', 'backspace']
];

// ============================================
// STATE
// ============================================
const state = {
    gameId: null,
    targetWord: null,
    currentRow: 0,
    currentCol: 0,
    attempts: [],
    isGameOver: false,
    isWon: false,
    password: PASSWORD
};

// ============================================
// DOM ELEMENTS
// ============================================
const elements = {
    passwordScreen: document.getElementById('password-screen'),
    gameScreen: document.getElementById('game-screen'),
    passwordInput: document.getElementById('password-input'),
    passwordSubmit: document.getElementById('password-submit'),
    passwordError: document.getElementById('password-error'),
    gameGrid: document.getElementById('game-grid'),
    currentAttempt: document.getElementById('current-attempt'),
    message: document.getElementById('message'),
    keyboard: document.getElementById('keyboard'),
    modal: document.getElementById('game-over-modal'),
    modalMessage: document.getElementById('modal-message'),
    modalWord: document.getElementById('modal-word'),
    playAgainBtn: document.getElementById('play-again')
};

// ============================================
// UTILITY FUNCTIONS
// ============================================

/**
 * Show/hide screens
 */
function showScreen(screenName) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(`${screenName}-screen`).classList.add('active');
}

/**
 * Show error message
 */
function showError(msg) {
    elements.message.textContent = msg;
    elements.message.style.color = '#dc3545';
    setTimeout(() => {
        if (elements.message.textContent === msg) {
            elements.message.textContent = '';
            elements.message.style.color = '';
        }
    }, 3000);
}

/**
 * Show info message
 */
function showMessage(msg) {
    elements.message.textContent = msg;
    elements.message.style.color = '#666';
}

/**
 * Clear message
 */
function clearMessage() {
    elements.message.textContent = '';
}

/**
 * Disable/enable keyboard
 */
function setKeyboardDisabled(disabled) {
    document.querySelectorAll('.key').forEach(key => {
        key.disabled = disabled;
    });
}

/**
 * Update attempt counter display
 */
function updateAttemptCounter() {
    elements.currentAttempt.textContent = state.currentRow + 1;
}

/**
 * Generate grid cells
 */
function createGrid() {
    elements.gameGrid.innerHTML = '';
    for (let row = 0; row < MAX_ATTEMPTS; row++) {
        for (let col = 0; col < WORD_LENGTH; col++) {
            const cell = document.createElement('div');
            cell.className = 'cell';
            cell.dataset.row = row;
            cell.dataset.col = col;
            cell.setAttribute('role', 'gridcell');
            cell.setAttribute('aria-label', `Row ${row + 1}, Column ${col + 1}, empty`);
            elements.gameGrid.appendChild(cell);
        }
    }
}

/**
 * Create virtual keyboard
 */
function createKeyboard() {
    elements.keyboard.innerHTML = '';
    KEYBOARD_LAYOUT.forEach((row, rowIndex) => {
        const rowDiv = document.createElement('div');
        rowDiv.className = 'keyboard-row';
        row.forEach(key => {
            const btn = document.createElement('button');
            btn.className = 'key key-default';
            btn.dataset.key = key;
            btn.setAttribute('role', 'button');
            btn.setAttribute('aria-label', key === 'enter' ? 'Enter' : key === 'backspace' ? 'Backspace' : key.toUpperCase());
            
            if (key === 'enter' || key === 'backspace') {
                btn.classList.add('wide');
                btn.textContent = key === 'enter' ? '↵' : '⌫';
            } else {
                btn.textContent = key.toUpperCase();
            }
            
            rowDiv.appendChild(btn);
        });
        elements.keyboard.appendChild(rowDiv);
    });
}

/**
 * Get cell element at position
 */
function getCell(row, col) {
    return elements.gameGrid.querySelector(`.cell[data-row="${row}"][data-col="${col}"]`);
}

/**
 * Update keyboard key colors based on attempts
 */
function updateKeyboardColors() {
    // Calculate best color for each letter
    const keyColors = {}; // letter -> best color
    
    state.attempts.forEach(attempt => {
        attempt.guess.split('').forEach((letter, idx) => {
            const result = attempt.result[idx];
            const current = keyColors[letter];
            // Priority: green > yellow > gray
            if (result === 'green') keyColors[letter] = 'green';
            else if (result === 'yellow' && current !== 'green') keyColors[letter] = 'yellow';
            else if (result === 'gray' && !current) keyColors[letter] = 'gray';
        });
    });
    
    // Apply to keyboard
    document.querySelectorAll('.key[data-key]').forEach(key => {
        const letter = key.dataset.key;
        if (letter === 'enter' || letter === 'backspace') return;
        
        const color = keyColors[letter];
        key.className = 'key';
        if (color) {
            key.classList.add(`key-${color}`);
        } else {
            key.classList.add('key-default');
        }
    });
}

// ============================================
// API FUNCTIONS
// ============================================

/**
 * Make authenticated API request
 */
async function apiRequest(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        'X-Password': state.password,
        ...options.headers
    };
    
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers
    });
    
    const data = await response.json();
    
    if (!response.ok) {
        throw new Error(data.detail || 'Request failed');
    }
    
    return data;
}

/**
 * Create new game
 */
async function startNewGame() {
    const data = await apiRequest('/api/new-game', { method: 'POST' });
    state.gameId = data.game_id;
    state.maxAttempts = data.max_attempts;
    state.currentRow = 0;
    state.currentCol = 0;
    state.attempts = [];
    state.isGameOver = false;
    state.isWon = false;
    state.targetWord = null; // Unknown until game over
    
    // Reset UI
    createGrid();
    updateAttemptCounter();
    clearMessage();
    setKeyboardDisabled(false);
    updateKeyboardColors();
    elements.modal.classList.add('hidden');
    
    // Focus first cell
    getCell(0, 0)?.focus();
}

/**
 * Submit guess
 */
async function submitGuess(guess) {
    const data = await apiRequest('/api/guess', {
        method: 'POST',
        body: JSON.stringify({ game_id: state.gameId, guess })
    });
    
    return data;
}

// ============================================
// GAME LOGIC
// ============================================

/**
 * Process a completed guess - animate and update state
 */
async function processGuess(guess) {
    try {
        clearMessage();
        setKeyboardDisabled(true);
        
        // Submit to backend
        const data = await submitGuess(guess);
        
        // Animate cells
        await animateGuess(state.currentRow, data.result, guess);
        
        // Update state
        state.attempts.push({
            guess: data.guess,
            result: data.result
        });
        state.currentRow++;
        state.currentCol = 0;
        
        // Update keyboard
        updateKeyboardColors();
        
        // Check game over
        if (data.is_game_over) {
            state.isGameOver = true;
            state.isWon = data.is_won;
            state.targetWord = data.target_word;
            handleGameOver(data);
        } else {
            updateAttemptCounter();
            showMessage(data.message);
            setKeyboardDisabled(false);
        }
        
    } catch (error) {
        showError(error.message);
        setKeyboardDisabled(false);
    }
}

/**
 * Animate guess cells with flip effect
 */
function animateGuess(row, results, guess) {
    return new Promise(resolve => {
        const cells = [];
        for (let col = 0; col < WORD_LENGTH; col++) {
            cells.push(getCell(row, col));
        }
        
        // Set text content before animation
        guess.split('').forEach((char, index) => {
            cells[index].textContent = char.toUpperCase();
        });
        
        let completed = 0;
        const delay = 200; // ms between flips
        
        cells.forEach((cell, index) => {
            setTimeout(() => {
                cell.classList.add('flip', results[index]);
                
                cell.addEventListener('animationend', () => {
                    cell.classList.remove('flip');
                    completed++;
                    if (completed === WORD_LENGTH) {
                        // Add pop animation to all
                        cells.forEach(c => c.classList.add('pop'));
                        setTimeout(() => {
                            cells.forEach(c => c.classList.remove('pop'));
                            resolve();
                        }, 200);
                    }
                }, { once: true });
            }, index * delay);
        });
    });
}

/**
 * Handle game over
 */
function handleGameOver(data) {
    if (data.is_won) {
        elements.modalMessage.textContent = `Congratulations! You won in ${data.attempt} attempt(s)!`;
        elements.modalWord.textContent = '';
        elements.modalWord.classList.add('hidden');
    } else {
        elements.modalMessage.textContent = 'Game Over!';
        elements.modalWord.textContent = data.target_word.toUpperCase();
        elements.modalWord.classList.remove('hidden');
    }
    
    elements.modal.classList.remove('hidden');
    setKeyboardDisabled(true);
}

/**
 * Handle keyboard input
 */
function handleKeyInput(key) {
    if (state.isGameOver) return;
    
    if (key === 'enter') {
        if (state.currentCol === WORD_LENGTH) {
            const guess = getCurrentGuess();
            if (guess.length === WORD_LENGTH) {
                processGuess(guess);
            } else {
                showError('Not enough letters');
                shakeRow(state.currentRow);
            }
        }
    } else if (key === 'backspace') {
        if (state.currentCol > 0) {
            state.currentCol--;
            const cell = getCell(state.currentRow, state.currentCol);
            cell.textContent = '';
            cell.classList.remove('filled');
            cell.setAttribute('aria-label', `Row ${state.currentRow + 1}, Column ${state.currentCol + 1}, empty`);
        }
    } else if (/^[a-z]$/i.test(key)) {
        if (state.currentCol < WORD_LENGTH) {
            const cell = getCell(state.currentRow, state.currentCol);
            cell.textContent = key.toUpperCase();
            cell.classList.add('filled');
            cell.setAttribute('aria-label', `Row ${state.currentRow + 1}, Column ${state.currentCol + 1}, ${key.toUpperCase()}`);
            state.currentCol++;
        }
    }
}

/**
 * Get current row's guess
 */
function getCurrentGuess() {
    let guess = '';
    for (let col = 0; col < WORD_LENGTH; col++) {
        const cell = getCell(state.currentRow, col);
        guess += cell.textContent.toLowerCase();
    }
    return guess;
}

/**
 * Shake row animation for invalid input
 */
function shakeRow(row) {
    for (let col = 0; col < WORD_LENGTH; col++) {
        const cell = getCell(row, col);
        cell.style.animation = 'shake 0.3s ease';
        setTimeout(() => {
            cell.style.animation = '';
        }, 300);
    }
}

/**
 * Handle physical keyboard
 */
function handlePhysicalKeyboard(e) {
    if (state.isGameOver) return;
    
    const key = e.key.toLowerCase();
    
    if (key === 'enter') {
        e.preventDefault();
        handleKeyInput('enter');
    } else if (key === 'backspace') {
        e.preventDefault();
        handleKeyInput('backspace');
    } else if (/^[a-z]$/.test(key)) {
        e.preventDefault();
        handleKeyInput(key);
    }
}

// ============================================
// EVENT LISTENERS
// ============================================

// Password screen
elements.passwordSubmit.addEventListener('click', () => {
    const input = elements.passwordInput.value;
    if (input === PASSWORD) {
        elements.passwordError.classList.add('hidden');
        elements.passwordInput.value = '';
        showScreen('game');
        startNewGame();
    } else {
        elements.passwordError.classList.remove('hidden');
        elements.passwordInput.value = '';
        elements.passwordInput.focus();
    }
});

elements.passwordInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        elements.passwordSubmit.click();
    }
});

// Virtual keyboard
elements.keyboard.addEventListener('click', (e) => {
    const keyBtn = e.target.closest('.key');
    if (keyBtn && !keyBtn.disabled) {
        handleKeyInput(keyBtn.dataset.key);
    }
});

// Play again
elements.playAgainBtn.addEventListener('click', () => {
    startNewGame();
});

// Physical keyboard
document.addEventListener('keydown', handlePhysicalKeyboard);

// Prevent default behavior for game keys
document.addEventListener('keydown', (e) => {
    if (['Enter', 'Backspace'].includes(e.key) || /^[a-z]$/i.test(e.key)) {
        if (!state.isGameOver && elements.gameScreen.classList.contains('active')) {
            e.preventDefault();
        }
    }
});

// Focus management
elements.passwordInput.addEventListener('focus', () => {
    elements.passwordError.classList.add('hidden');
});

// ============================================
// INITIALIZATION
// ============================================
function init() {
    createGrid();
    createKeyboard();
    showScreen('password');
    elements.passwordInput.focus();
}

// Start app
init();