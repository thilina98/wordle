/**
 * The game page. Puts the pieces together and starts them; owns nothing itself.
 */

import { createAccount } from './account.js';
import { api } from './api.js';
import { auth } from './auth.js';
import { createGame } from './game.js';

api.useToken(() => auth.accessToken());

const account = createAccount({ page: 'game' });
const game = createGame({ account });

await account.start();
await game.play();
