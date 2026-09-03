// Wordle Game - Frontend JavaScript Tests
// Using Jest-style syntax (can run with any test runner)

/**
 * Test suite for frontend game logic
 * These tests are independent of DOM - pure logic functions
 */

// Color evaluation logic (should match backend exactly)
function evaluateGuess(target, guess) {
    target = target.toLowerCase();
    guess = guess.toLowerCase();
    
    const result = ['gray', 'gray', 'gray', 'gray', 'gray'];
    const targetChars = target.split('');
    const guessChars = guess.split('');
    
    // Count available letters in target (non-green positions)
    const available = {};
    for (let i = 0; i < 5; i++) {
        if (targetChars[i] !== guessChars[i]) {
            available[targetChars[i]] = (available[targetChars[i]] || 0) + 1;
        }
    }
    
    // First pass: mark greens
    for (let i = 0; i < 5; i++) {
        if (guessChars[i] === targetChars[i]) {
            result[i] = 'green';
            guessChars[i] = ''; // Mark as processed
        }
    }
    
    // Second pass: mark yellows from available pool
    for (let i = 0; i < 5; i++) {
        if (!guessChars[i]) continue; // Already processed as green
        const char = guessChars[i];
        if (available[char] > 0) {
            result[i] = 'yellow';
            available[char]--;
        }
    }
    
    return result;
}

// Game state management
class GameState {
    constructor() {
        this.gameId = null;
        this.targetWord = null;
        this.attempts = [];
        this.maxAttempts = 5;
        this.isGameOver = false;
        this.isWon = false;
        this.password = 'secret123';
    }
    
    reset() {
        this.gameId = null;
        this.targetWord = null;
        this.attempts = [];
        this.isGameOver = false;
        this.isWon = false;
    }
    
    addAttempt(guess, result) {
        this.attempts.push({ guess, result });
        if (guess === this.targetWord) {
            this.isWon = true;
            this.isGameOver = true;
        } else if (this.attempts.length >= this.maxAttempts) {
            this.isGameOver = true;
        }
    }
    
    getRemainingAttempts() {
        return Math.max(0, this.maxAttempts - this.attempts.length);
    }
}

// Keyboard handling
const KEYBOARD_LAYOUT = [
    ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
    ['enter', 'z', 'x', 'c', 'v', 'b', 'n', 'm', 'backspace']
];

function getKeyClass(letter, gameState) {
    // Determine key color based on all attempts
    let hasGreen = false;
    let hasYellow = false;
    let guessed = false;
    
    for (const attempt of gameState.attempts) {
        for (let i = 0; i < attempt.guess.length; i++) {
            if (attempt.guess[i] === letter) {
                guessed = true;
                if (attempt.result[i] === 'green') hasGreen = true;
                else if (attempt.result[i] === 'yellow') hasYellow = true;
            }
        }
    }
    
    if (hasGreen) return 'key-green';
    if (hasYellow) return 'key-yellow';
    if (guessed) return 'key-gray';
    return 'key-default';
}

// ============================================
// TESTS
// ============================================

console.log('Running frontend tests...\n');

let passed = 0;
let failed = 0;

function assertEqual(actual, expected, testName) {
    const actualStr = JSON.stringify(actual);
    const expectedStr = JSON.stringify(expected);
    if (actualStr === expectedStr) {
        console.log(`✓ ${testName}`);
        passed++;
    } else {
        console.log(`✗ ${testName}`);
        console.log(`  Expected: ${expectedStr}`);
        console.log(`  Actual:   ${actualStr}`);
        failed++;
    }
}

function assertThrows(fn, testName) {
    try {
        fn();
        console.log(`✗ ${testName} - Expected throw but didn't`);
        failed++;
    } catch (e) {
        console.log(`✓ ${testName}`);
        passed++;
    }
}

// Test evaluateGuess
console.log('--- evaluateGuess tests ---');

assertEqual(
    evaluateGuess('crane', 'crane'),
    ['green', 'green', 'green', 'green', 'green'],
    'All correct - all green'
);

assertEqual(
    evaluateGuess('crane', 'zesty'),
    ['gray', 'yellow', 'gray', 'gray', 'gray'],
    'crane vs zesty - e is yellow at pos 1'
);

assertEqual(
    evaluateGuess('crane', 'acorn'),
    ['yellow', 'yellow', 'gray', 'yellow', 'yellow'],
    'crane vs acorn - a,c,r,n yellow'
);

assertEqual(
    evaluateGuess('apple', 'alley'),
    ['green', 'yellow', 'gray', 'yellow', 'gray'],
    'apple vs alley - a green, l yellow, e yellow'
);

assertEqual(
    evaluateGuess('apple', 'apply'),
    ['green', 'green', 'green', 'green', 'gray'],
    'apple vs apply - all green except y'
);

assertEqual(
    evaluateGuess('crane', 'cairn'),
    ['green', 'yellow', 'gray', 'yellow', 'yellow'],
    'crane vs cairn - c green, a,r,n yellow'
);

assertEqual(
    evaluateGuess('abbey', 'bbbbb'),
    ['gray', 'green', 'green', 'gray', 'gray'],
    'abbey vs bbbbb - two greens at pos 1,2'
);

assertEqual(
    evaluateGuess('abbey', 'babby'),
    ['yellow', 'yellow', 'green', 'gray', 'green'],
    'abbey vs babby - complex duplicate handling'
);

// Test GameState
console.log('\n--- GameState tests ---');

const state = new GameState();
state.targetWord = 'crane';
state.maxAttempts = 5;

assertEqual(state.getRemainingAttempts(), 5, 'Initial remaining attempts = 5');
assertEqual(state.isGameOver, false, 'Initial game not over');
assertEqual(state.isWon, false, 'Initial not won');

state.addAttempt('apple', ['gray', 'yellow', 'gray', 'gray', 'yellow']);
assertEqual(state.attempts.length, 1, 'One attempt recorded');
assertEqual(state.getRemainingAttempts(), 4, 'Remaining = 4 after 1 attempt');
assertEqual(state.isGameOver, false, 'Game not over after 1 wrong attempt');

state.addAttempt('crane', ['green', 'green', 'green', 'green', 'green']);
assertEqual(state.isWon, true, 'Won after correct guess');
assertEqual(state.isGameOver, true, 'Game over after win');

const state2 = new GameState();
state2.targetWord = 'crane';
state2.maxAttempts = 5;
for (let i = 0; i < 5; i++) {
    state2.addAttempt('zesty', ['gray', 'yellow', 'gray', 'gray', 'gray']);
}
assertEqual(state2.isGameOver, true, 'Game over after 5 attempts');
assertEqual(state2.isWon, false, 'Not won after 5 wrong attempts');

// Test getKeyClass
console.log('\n--- getKeyClass tests ---');

const keyState = new GameState();
keyState.targetWord = 'crane';
keyState.attempts = [
    { guess: 'apple', result: ['gray', 'yellow', 'gray', 'gray', 'yellow'] }
];

// apple: a(p0,gray), p(p1,yellow), p(p2,gray), l(p3,gray), e(p4,yellow)
assertEqual(
    getKeyClass('a', keyState),
    'key-gray',
    'Key "a" is gray (in apple at pos 0, result gray)'
);

assertEqual(
    getKeyClass('p', keyState),
    'key-yellow',
    'Key "p" is yellow (in apple at pos 1, result yellow - overrides pos 2 gray)'
);

assertEqual(
    getKeyClass('l', keyState),
    'key-gray',
    'Key "l" is gray (in apple at pos 3, result gray)'
);

assertEqual(
    getKeyClass('e', keyState),
    'key-yellow',
    'Key "e" is yellow (in apple at pos 4, result yellow)'
);

assertEqual(
    getKeyClass('z', keyState),
    'key-default',
    'Key "z" never guessed -> default'
);

// Add a green attempt
keyState.attempts.push({ guess: 'crane', result: ['green', 'green', 'green', 'green', 'green'] });
assertEqual(
    getKeyClass('c', keyState),
    'key-green',
    'Key "c" is green (in crane at pos 0, result green)'
);

// Green overrides yellow
assertEqual(
    getKeyClass('a', keyState),
    'key-green',
    'Key "a" green overrides previous yellow'
);

console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);

if (failed > 0) {
    process.exit(1);
}