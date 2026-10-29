# Ideas

Not planned, not scoped. Just things worth doing.

## 0. Expand the playable words
The users currently only can ply 830 words. (game only chooses 830).
users can guess 14,855 valid words. 
I think 830 is a little less. we need find more common playable words and extend the list.
the problem with using the 14855 list as playable -> there are some words like **aalii** which are 
real words technically, but not common words. so having users to guess such words is not good.

## 1. Word requests

When a guess is refused, let the player request it as a valid word. Requests go
in a queue. An admin page reviews them and accepts them into the word list.

Review rather than auto-accept, because no free source is trustworthy enough to
add words unattended: Wiktionary calls `zzzzz` a word, Datamuse accepts `blorp`,
`dictionaryapi.dev` is dead, and the system dictionary has no plurals.

## 2. More modes

6 letters / 6 guesses, 6 letters / 5 guesses, and so on.

Most of the code already handles it — word length and attempt count are
settings, and the board builds itself from what the API returns. The work is
sourcing good word lists per length, and making length per-game instead of
per-process.
