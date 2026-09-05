# Improvements

Planned work, not built yet. Each item says what it is, what it touches, and
the decisions that need making before anyone starts.

---

## 1. Let players request a word, and review the requests

### What

When a guess is refused with "Enter a valid word", offer a button: *request this
word*. Requested words go into a queue. An admin page lists them, and you accept
or reject each one. Accepted words join the guess list immediately.

### Why

The shipped dictionary has 14,855 words. It will never be complete. Right now a
refused word is simply lost — nobody finds out that six different players tried
`sprog` last week.

**Why review, and not automatic.** Adding a word automatically needs something
that can tell a real word from noise. Two sources were tested and both failed:

| Source | Verdict |
|---|---|
| `dictionaryapi.dev` | Dead. Every request times out. |
| Wiktionary API | Says `zzzzz` is a word. Too permissive. |
| Datamuse API | Accepts `blorp` and `aeiou`. Frequency does not help: `zymic` (real) scores 0.000000, same as `blorp` (not real). |
| `/usr/share/dict/words` | 1934 Webster's. No plurals — `cards`, `boxes`, `trees` all missing — and it adds 2,386 entries like `gucki`, `uvver`, `resex`. Would make the list worse. |

No free source is trustworthy enough to write to the word list unattended. A
person looking at a list of requested words is slower, but it is the only
option that does not degrade the game.

### Shape

- **Queue.** A CSV alongside the word lists: `word, count, first_seen, last_seen`.
  Counted, not appended, so a word requested twenty times sorts to the top.
- **Approved words.** A second CSV, merged over the shipped dictionary at
  startup. Keeping it separate means the packaged list stays pristine and an
  approval can be undone by deleting one line.
- **Where it plugs in.** `GameState.guess` already raises `InvalidGuessError`
  for an unknown word. That needs a distinct subclass so the API layer can tell
  "not a word" from "wrong length" and record only the first.
- **Writable storage.** Both files need a directory that survives a container
  rebuild — a mounted volume, and a `WORDLE_DATA_DIR` setting to point at it.
  Today the app writes nothing to disk at all; this is the change that ends
  that, and it is the main new failure mode to handle (read-only filesystem,
  full disk).

### Open questions

- **Who is the admin?** There are no accounts, only one shared password. The
  dashboard needs either a second password or a token you paste in. Simplest
  honest answer: a separate `WORDLE_ADMIN_PASSWORD`, and the admin page is a
  different origin from the game.
- **Does the requesting player get their guess back?** Their turn was already
  refused, which costs no attempt, so nothing is lost. But if the word is
  approved an hour later, they are long gone. Accept that.
- **Abuse.** Anyone with the password can flood the queue. Cap requests per
  game, or per IP per hour.

### Effort

Roughly: a day for the queue and the merge-on-startup, a day for the admin page
and its own auth. The storage question is the part that will take longer than
it looks.

---

## 2. Scoring

### What

A score per finished game, from two things: how many guesses it took, and how
long each guess took.

### The rules as given

- The **time penalty on the first guess is zero.** Correct — the player is
  staring at an empty board with nothing to reason from, so thinking time there
  measures nothing.
- A win **on the first attempt scores zero**, on both components.

That second rule needs saying out loud, because it looks harsh until you see
it: a first-guess win is luck, not skill. There is no information on the board
to have used. Scoring it zero means the leaderboard measures deduction rather
than fortune. It also removes any point in brute-forcing common answers.

### A concrete formula

Nothing below is decided; it is a starting point to argue with.

```
guess_points = 0                          if solved on attempt 1
             = (max_attempts - used) * 100 + 100   otherwise

time_points  = sum over guesses 2..n of max(0, 60 - seconds_taken) * 2

score        = 0                          if solved on attempt 1
             = guess_points + time_points otherwise
```

So on a 5-guess game: solving in 2 gives 400 base, in 5 gives 100, first try
gives 0. Every guess after the first earns up to 120 speed points, and nothing
below zero — a slow guess costs you the bonus, never the base.

### What it touches

- **The server must time the guesses.** The client cannot be trusted with this;
  a modified `app.js` could report one second every time. `GameState` records
  attempts but no timestamps, so `Attempt` needs one, and the store must keep
  the game's start time.
- **Clock choice matters.** `time.monotonic` for durations — the wall clock can
  jump backwards and produce negative gaps.
- **Network latency counts against the player.** A guess from a phone on a slow
  connection looks slower than the same guess on wifi. Either accept it, or
  time from "board rendered" instead, which means trusting the client again.
  Accepting it is simpler and more honest.

### Open questions

- Is there a leaderboard? If so, scores must persist, and there is currently no
  database at all. That is a much bigger change than the scoring itself.
- What happens to an abandoned game — no score, or zero?
- Do the numbers above feel right? They need playtesting, not reasoning.

---

## 3. More game modes

### What

Beyond 5 letters and 5 guesses: 6 letters with 6 guesses, 6 letters with 5
guesses, and whatever else is worth playing.

### What already supports it

More than you would expect. `WORD_LENGTH` and `MAX_ATTEMPTS` are settings, not
constants in the code. `evaluate_guess` works on any length. `GameView` already
tells the frontend `word_length` and `max_attempts`, and the board and keyboard
are built from those numbers rather than hardcoded. A 6-letter game very nearly
works today.

### What does not

- **The word lists are 5-letter only.** This is the real cost. Each new length
  needs its own answer list and its own dictionary, of the same quality: a
  curated set of common words, and a large set of valid guesses. Sourcing the
  6-letter dictionary is most of the work in this item.
- **Length is set per process, not per game.** `WORDLE_WORD_LENGTH` configures
  the whole app. Modes need it per game: `POST /api/games` takes a mode, and the
  game remembers it.
- **The repository loads one pair of lists.** It would need a set of lists per
  length, chosen when the game is created.
- **The board gets narrow on a phone.** Tiles are `min(62px, 14vw)`. Six columns
  still fit; seven start to get cramped, and the on-screen keyboard is already
  the tightest part of the layout.

### Shape

Name the modes rather than passing loose numbers, so a mode can carry other
rules later:

```json
POST /api/games  {"mode": "classic"}     5 letters, 5 guesses
                 {"mode": "wide"}        6 letters, 6 guesses
                 {"mode": "wide-hard"}   6 letters, 5 guesses
```

A mode is a small record: word length, attempts, and which word lists to use.
Unknown mode is a 400. The frontend needs a picker, and needs to remember the
last mode chosen.

### Open questions

- Does a saved game from one mode survive switching to another? Simplest: each
  mode keeps its own stored game id.
- Do modes share a score table, or one each? Comparing a 6-letter score to a
  5-letter one is meaningless, so probably one each — which folds back into
  item 2.

---

## Order

**2 before 1 and 3.** Scoring is self-contained and touches no storage. Item 1
introduces writing to disk, which changes deployment. Item 3 is gated on
sourcing word lists, which is slow and mostly not coding.
