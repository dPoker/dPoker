# Poker44 P2P Stack (Subnet + Platform)

Este documento resume la infraestructura y el flow P2P que tenemos montado para `poker44`:

- Una **subnet de Bittensor** con `validator` y `miner` (synapse).
- Una **plataforma de poker** (backend Node + Postgres + Redis + frontend Next.js) que corre **por validator**.
- Un **Room Directory** (servicio ligero) para descubrir rooms activos (uno por validator).

La idea es que los **validators generan manos nuevas** (humanos vs bots), las usan para evaluar a los **miners** (modelos anti-bot) y hacen `set_weights` en cadena.
Los humanos **no ven** nada de Bittensor/validators: solo ven una plataforma de poker normal con balance y mesa.

## Repos / Layout local (workspace)

- Subnet: `poker44-subnet/`
  - Neurons: `poker44-subnet/neurons/`
  - Lógica subnet: `poker44-subnet/poker44/`
  - Deploy PM2: `poker44-subnet/scripts/deploy/pm2/`
  - Docs: `poker44-subnet/docs/`
- Platform:
  - Backend: `platform/backend/`
  - Frontend: `platform/frontend/`

## Componentes (qué corre y para qué)

### 1) Room Directory (común)

Servicio FastAPI (in-memory) para listar rooms activos:

- Código: `poker44-subnet/poker44/p2p/room_directory/app.py`
- Endpoints:
  - `POST /announce` (anuncio firmado por el validator)
  - `GET /rooms` (listado de rooms activos)
  - `GET /healthz`
- Seguridad (MVP):
  - Firma **HMAC** con `DIRECTORY_SHARED_SECRET` (placeholder; futuro: firma hotkey/ed25519).
- TTL:
  - `DIRECTORY_TTL_SECONDS` (default 60s). Si el validator deja de anunciar, desaparece del directorio.
- CORS:
  - Habilitado para que el **frontend** pueda hacer `fetch` al directory sin “Failed to fetch”.

### 2) Platform Backend (por validator)

Backend Node/Express + TypeORM, con dependencias en Docker:

- Postgres + Redis via `platform/backend/docker-compose.yml`
- API pública (para humanos) bajo `/api/v1/*`:
  - Auth: `/api/v1/auth/*` (cookie HTTP-only `auth_token`)
  - Rooms: `/api/v1/rooms/*`
  - Game: sockets + endpoints del motor
- Endpoints internos (solo validator, protegidos por secreto):
  - `POST /internal/rooms/ensure` crea/reusa el **room anunciado** por ese validator y sienta bots.
  - `POST /internal/rooms/:code/start` intenta arrancar el juego (solo cuando hay al menos 1 humano conectado).
  - `GET /internal/eval/next?limit=N&requireMixed=true` devuelve batches **consume-once** de manos ya jugadas (fresh, nunca evaluadas antes).
  - `POST /internal/eval/simulate` genera manos de prueba (dev) si no hay humanos jugando.
  - Header requerido: `x-eval-secret: <INTERNAL_EVAL_SECRET>`

Bots en mesas P2P:

- El “host” del room anunciado es un **BOT** interno.
- Se crean bots extra (default 3 total contando host) y se unen al room.
- Los bots no tienen “marca” visible: usernames tipo `player_<hash>_<idx>`.
- El juego **no arranca** hasta que hay al menos 1 HUMANO conectado (evita que bots arranquen y bloqueen la entrada).
- Cuando arranca: `botAutoplay: true` (bots actúan server-side) y `autoRebuy: true` (cash-game feel).

Datos de evaluación:

- El backend registra eventos por mano en DB (`game_events`, `hand_results`, etc).
- `internal/eval/next` construye un objeto “hand” **sanitizado** (sin hole cards), con:
  - secuencia de eventos, fase, amounts, pot/current_bet, stacks, `decision_ms`, etc.
  - IDs anonimizados por tokens (hand/table/seat tokens).
- Consume-once:
  - Tabla `eval_consumed_hands` asegura que una mano se evalúa una sola vez.

Auth / “token en storage”:

- El frontend **no guarda token en localStorage** (es inseguro).
- La sesión se mantiene con cookie **HTTP-only** `auth_token` (persistente).
- En dev hemos extendido la duración de sesión a 30 días (`JWT_EXPIRES_IN=30d`, `COOKIE_MAX_AGE=2592000000`).

### 3) Platform Frontend (por validator)

Frontend Next.js (poker UI) en modo P2P:

- Entry: `/poker-gameplay`
- Flow “poker normal”:
  1. Abres `/poker-gameplay`
  2. El cliente **auto-selecciona** un backend/room desde el Room Directory (sin mostrarlo al usuario)
  3. Login/Signup normal
  4. “Play Now” te manda al room (mesa)
- La selección P2P se guarda en `localStorage` (NO tokens):
  - `poker44_platform_url`, `poker44_api_base_url`, `poker44_ws_url`, `poker44_directory_url`, `poker44_pending_room_code`
- El usuario no necesita abrir `/poker-gameplay/p2p` (queda como página debug, sin link).

### 4) Miner (Bittensor)

Neuron miner que expone un axon y responde a la synapse:

- Código: `poker44-subnet/neurons/miner.py`
- Synapse: `poker44-subnet/poker44/validator/synapse.py` (`DetectionSynapse`)
- Input: `chunks` (lista de N chunks; cada chunk es lista de dicts “hand”)
- Output: `risk_scores` (lista de floats, 1 score por chunk)
- En dev/testnet el miner actual es un **modelo mock** que devuelve scores aleatorios (suficiente para E2E).

### 5) Validator (Bittensor) + P2P bridge

Neuron validator que:

- Asegura un room discoverable y lo anuncia al directory.
- Genera “tareas” de evaluación desde el Platform Backend (`/internal/eval/next`).
- Acumula hasta N tasks (chunks) y consulta a los miners.
- Calcula rewards y hace `set_weights` (con commit-reveal timelocked en testnet netuid 401).

Piezas clave:

- Entrypoint: `poker44-subnet/neurons/validator.py`
- Ciclo de forward: `poker44-subnet/poker44/validator/forward.py`
  - Buffer: acumula hasta `POKER44_TASK_BATCH_SIZE` (default 10) y luego evalúa exactamente esas N.
  - Autosimulate (dev): si no hay batches y `POKER44_AUTOSIMULATE=true`, llama `/internal/eval/simulate`.
- P2P announcement loop:
  - Asegura room via `/internal/rooms/ensure`
  - Intenta arrancar room via `/internal/rooms/:code/start`
  - Anuncia via directory `/announce` con firma HMAC

Weights en testnet (netuid 401):

- `commit_reveal_weights_enabled=True` (CRv4 timelocked), por lo que:
  - `set_weights` crea **un commit** y el reveal ocurre mas tarde (no se ve inmediato en `metagraph.weights`).
  - Para verificar: `sub.get_timelocked_weight_commits(netuid)`.
- El validator respeta `weights_rate_limit` del chain para no spamear `set_weights`.

## Deploy local (PM2) y URLs

Script que levanta TODO en local (con puertos dinamicos):

- Up: `poker44-subnet/scripts/deploy/pm2/up.sh`
- Down: `poker44-subnet/scripts/deploy/pm2/down.sh`

`up.sh` hace:

- Selecciona puertos libres (frontend/backend/directory + base para axons de miners).
- Levanta Docker deps del backend (`npm run docker:up` + migrations).
- Arranca en PM2:
  - directory
  - platform backend
  - platform frontend
  - miner(s)
  - validator
- Escribe runtime en `poker44-subnet/.p2p_deploy.env` (gitignored).

Para ver el estado:

- `pm2 ls | rg poker44-p2p`
- `pm2 logs poker44-p2p-validator-test-default --lines 200`
- `pm2 logs poker44-p2p-miner-test-miner1 --lines 200`

## Deploy modular (desacoplado)

Topologia objetivo:

- **Central** (infra comun): `room_directory` + `platform frontend`
- **Por validator** (infra del operador): `platform backend` + `validator` (+ su Postgres/Redis)
- **Por miner** (infra del operador): `miner`

Scripts PM2 (MVP):

- Central:
  - `bash poker44-subnet/scripts/deploy/pm2/up-directory.sh` (solo directory)
  - `bash poker44-subnet/scripts/deploy/pm2/up-central.sh` (directory + frontend)
- Validator operator:
  - `bash poker44-subnet/scripts/deploy/pm2/up-validator-stack.sh` (backend + validator)

Variables importantes en modo desacoplado:

- El directory es un servicio HTTP publico:
  - `DIRECTORY_SHARED_SECRET` debe coincidir con el validator.
- El validator debe anunciar un `platform_url` reachable por usuarios (no `127.0.0.1`):
  - setea `POKER44_PLATFORM_PUBLIC_URL=https://<tu-dominio-o-ip>:<port>`
- El backend debe permitir CORS + cookies desde el frontend:
  - `CORS_ORIGINS=https://<frontend-domain>`
  - En prod: `COOKIE_DOMAIN=.poker44.com` + HTTPS (SameSite=None, Secure)

## Smoke / tests

- Smoke (stack P2P + internal endpoints + directory):
  - `poker44-subnet/scripts/testnet/smoke_validator_stack.sh`
- Tests subnet:
  - `cd poker44-subnet && ./validator_env/bin/python -m pytest -q`
- Tests backend:
  - `cd platform/backend && npm test`
- Typecheck frontend:
  - `cd platform/frontend && npm run typecheck`

## Variables de entorno importantes (resumen)

Directory:

- `DIRECTORY_SHARED_SECRET`
- `DIRECTORY_TTL_SECONDS`
- `DIRECTORY_CORS_ORIGINS`

Platform backend:

- `PORT`
- `CORS_ORIGINS`
- `INTERNAL_EVAL_SECRET`
- `JWT_EXPIRES_IN` (dev: 30d)
- `COOKIE_MAX_AGE` (dev: 2592000000)

Validator (P2P provider):

- `POKER44_PROVIDER=platform`
- `POKER44_PLATFORM_BACKEND_URL=http://127.0.0.1:<backend_port>`
- `POKER44_INTERNAL_EVAL_SECRET=<secret>`
- `POKER44_DIRECTORY_URL=http://127.0.0.1:<directory_port>`
- `POKER44_DIRECTORY_SHARED_SECRET=<secret>`
- `POKER44_AUTOSIMULATE=true|false`
- `POKER44_TASK_BATCH_SIZE=10`
- `POKER44_QUERY_HOTKEYS=<comma-separated ss58>` (para limitar miners consultados)

Frontend:

- `NEXT_PUBLIC_API_URL=<platform_url>/api/v1`
- `NEXT_PUBLIC_WS_URL=<platform_url>`
- `NEXT_PUBLIC_DIRECTORY_URL=<directory_url>`

## Qué estamos haciendo (en una frase)

Estamos construyendo una plataforma de poker P2P donde **cada validator corre su propia sala** y usa manos nuevas (humanos vs bots) para evaluar modelos anti-bot (miners) en Bittensor, estableciendo weights en cadena, mientras los humanos juegan en una UI normal sin saber nada de validators/miners.

## Limitaciones / TODOs (intencionales por MVP)

- Directory usa HMAC compartido (reemplazar por firma hotkey/ed25519).
- Selection P2P en frontend: ahora es “auto-pick primero”; mas adelante: balancear por region/capacity/latency.
- Commit-reveal timelocked: las weights no aparecen instantaneamente; hay que esperar reveal.
- Scoring miner: actualmente es baseline/mock (mejorar scoring y anti-collusion).
- Reward “burn UID0”: fixed para que el burn vaya al UID 0 global (no al indice 0 del subset consultado).
