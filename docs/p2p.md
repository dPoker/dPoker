# Poker44 P2P Stack (Subnet + Platform + Directory + Ledger + Indexers)

Este documento resume la infraestructura P2P que tenemos montada para `poker44` y como se conectan:

- **Bittensor subnet** con `validator` y `miners` (synapse).
- **Poker Platform** (backend Node + Postgres + Redis + frontend Next.js).
- **Room Directory** (central) para descubrir mesas activas por validator.
- **Indexer** por validator (read API) que publica *attestation bundle* y computa estado de attestation (mock).
- **Ledger/Auth/Balance** (central) que es el *source-of-truth* de identidad y chips (simulado) y que **verifica attestation** antes de aceptar buy-in/cash-out.

Objetivo MVP: que un usuario humano vea una plataforma de poker normal (balance + lobby + mesa), mientras que cada validator genera manos nuevas (humanos vs bots) para evaluar a miners y hacer `set_weights` en la red.

## Layout local (workspace)

- Subnet: `poker44-subnet/`
  - Neurons: `poker44-subnet/neurons/`
  - Lógica subnet: `poker44-subnet/poker44/`
  - P2P services/lib: `poker44-subnet/poker44/p2p/`
  - Deploy PM2: `poker44-subnet/scripts/deploy/pm2/`
  - Docs: `poker44-subnet/docs/`
- Platform:
  - Backend: `platform/backend/`
  - Frontend: `platform/frontend/`

## Componentes (qué corre y para qué)

### 1) Room Directory (central)

Servicio FastAPI (in-memory) para registrar validators y listar rooms activos:

- Código: `poker44-subnet/poker44/p2p/room_directory/app.py`
- Endpoints:
  - `POST /announce`
  - `GET /rooms`
  - `GET /healthz`
- Seguridad (MVP):
  - `signature` es HMAC con `DIRECTORY_SHARED_SECRET` (placeholder; futuro: firma hotkey/ed25519).
- Datos anunciados mínimos:
  - `validator_id`, `validator_name`
  - `platform_url` (backend del validator donde se juega)
  - `indexer_url` (read API del validator)
  - `room_code` (mesa pública joinable en ese momento)
  - `last_seen`, `capacity_tables`, `version_hash`, etc.

### 2) Indexer (por validator)

Servicio FastAPI que corre junto a cada validator para publicar "attestation mock" y un estado de directory verificable:

- Código: `poker44-subnet/poker44/p2p/indexer/app.py`
- Endpoints:
  - `GET /attestation/bundle` (firmado por hotkey del validator)
  - `GET /attestation/votes` (votos sobre otros validators para el epoch actual)
  - `GET /directory/state` (agrega `/rooms` + votos y calcula `attested`)
  - `GET /attestation/status/{validator_id}` (status puntual para el ledger/front)
- Mock TEE:
  - `tee_enabled` se configura con `INDEXER_TEE_ENABLED=true|false`.
  - En este MVP no hay TEE real, pero la infra para verificar y bloquear ya existe.

Esto permite simular un validator "dangerous":

- Si `tee_enabled=false`, el indexer de cualquier peer lo marca `attested=false` y `danger_reason=tee_disabled`.
- Si el validator **no publica bundle** (`INDEXER_DISABLE_BUNDLE=true`), los peers lo marcan `attested=false` y `danger_reason=missing_or_invalid_bundle` (equivale a "no está usando attestation").

### 3) Ledger/Auth/Balance (central)

Es una instancia del **mismo backend** `platform/backend`, pero corriendo en "modo ledger":

- Es el único sitio donde vive el bankroll simulado (`balanceChips`) y la identidad.
- Endpoints:
  - Auth: `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, etc.
  - Ledger: `GET /api/v1/ledger/me`, `POST /api/v1/ledger/buyin`, `POST /api/v1/ledger/cashout`
- Verificación de attestation (MVP):
  - El ledger lista indexers desde el Room Directory (`LEDGER_DIRECTORY_URL`).
  - Para un `validatorId` dado, consulta `GET {indexer}/attestation/status/{validatorId}`.
  - Rechaza si:
    - Cualquier indexer reporta `attested=false` o `tee_enabled=false`.
    - No hay suficientes indexers disponibles (`LEDGER_MIN_INDEXERS`, default 2).
- Auth (P2P):
  - `AUTH_RETURN_TOKEN_IN_BODY=true` para devolver `{ user, token }`.
  - `AUTH_SET_COOKIE=false` para no usar cookies cross-domain.
  - El frontend guarda el token en `localStorage` y usa `Authorization: Bearer <token>`.

### 4) Platform Backend (por validator)

Cada validator corre su **propio backend** (Node/Express) con su **propio Postgres + Redis**:

- API pública (para jugar) bajo `/api/v1/*`:
  - Rooms: `/api/v1/rooms/*`
  - Juego: socket.io + endpoints del motor
  - Admin dashboard: `/api/v1/admin/*` (solo admins)
- Internal endpoints (solo validator local, protegidos por secreto):
  - `POST /internal/rooms/ensure` (crea/reusa la mesa pública)
  - `POST /internal/rooms/:code/start` (arranca la mesa si hay 1 HUMANO conectado)
  - `GET /internal/eval/next?limit=N&requireMixed=true` (hands fresh consume-once)
  - `POST /internal/eval/simulate` (dev autosimulate si no hay manos)
  - `POST /internal/metrics/ingest-cycle` (ingesta de resultados de evaluación para dashboard)
  - Header requerido: `x-eval-secret: <INTERNAL_EVAL_SECRET>`

**Bots en mesas públicas**

- El room público anunciado se hostea por un BOT interno.
- Se sientan bots extra (`P2P_ROOM_BOT_COUNT`, default 3 incluyendo host bot).
- El juego no arranca hasta que hay al menos 1 HUMANO conectado.
- Al arrancar: `botAutoplay=true` y `autoRebuy=true`.

**Ledger bridge (buy-in/cash-out)**

Cuando `LEDGER_API_URL` está configurado en el backend del validator:

- `POST /api/v1/rooms/:code/join` hace `ledger.buyin` (deduce `startingChips`) antes de unirse.
- `POST /api/v1/rooms/:code/leave` hace `ledger.cashout` (devuelve `startingChips`) antes de salir.
- Si el validator no está attested, el ledger devuelve 403 y el join falla.

### 5) Platform Frontend (central)

Frontend Next.js que vive fuera de validators y se conecta dinámicamente al backend elegido:

- Home: `/poker-gameplay` (login/signup)
- Lobby: `/poker-gameplay/lobby` (lista mesas públicas del directory + tablas privadas)
- P2P debug: `/poker-gameplay/p2p` (config manual de directory/validator)

P2P selection:

- Auto-selección best-effort vía `Room Directory` (`NEXT_PUBLIC_DIRECTORY_URL`).
- Cross-check best-effort con 2 indexers (si están disponibles) para marcar rooms `Verified/Unverified`.
- Guarda en `localStorage` solo URLs/room_code (no secretos):
  - `poker44_platform_url`, `poker44_api_base_url`, `poker44_ws_url`, `poker44_directory_url`.
- Auth token:
  - Se guarda en `localStorage` (MVP) y se manda como `Authorization: Bearer` a validators y al ledger.

### 6) Miner (Bittensor)

Neuron miner que responde a la synapse:

- Código: `poker44-subnet/neurons/miner.py`
- Synapse: `poker44-subnet/poker44/validator/synapse.py` (`DetectionSynapse`)
- Input: `chunks` (lista de N chunks; cada chunk es lista de dicts “hand”)
- Output: `risk_scores` (lista de floats, 1 score por chunk)

En dev/testnet usamos un miner mock (scores aleatorios) para poder probar E2E.

### 7) Validator (Bittensor) + evaluación

Neuron validator que:

- Mantiene una mesa pública joinable y la anuncia al directory.
- Consume manos nuevas desde su platform backend (`/internal/eval/next`) y acumula hasta N.
- Consulta a miners con `DetectionSynapse`.
- Calcula rewards y hace `set_weights` en cadena.
- Publica métricas al backend local (`/internal/metrics/ingest-cycle`) para dashboard.

Entrypoints:

- `poker44-subnet/neurons/validator.py`
- `poker44-subnet/poker44/validator/forward.py`

Buffering:

- `POKER44_TASK_BATCH_SIZE` (default 10): acumula hasta N y evalúa exactamente esas N; luego espera otras N.

Selección de miners:

- Por defecto filtra peers no-serving para evitar ruido (validators con `axon_off`, uids stale, etc.).
- Overrides:
  - `POKER44_QUERY_UIDS="1,3,4"`
  - `POKER44_QUERY_HOTKEYS="<ss58>,<ss58>"`

## Deploy local E2E (2 validators + ledger + directory + frontend + 3 miners)

Script recomendado:

```bash
cd poker44-subnet
NETWORK=test NETUID=401 \
VALIDATOR_WALLET=poker44-test VALIDATOR1_HOTKEY=validator VALIDATOR2_HOTKEY=validator2 \
MINER_WALLET=owner MINER_HOTKEYS=miner1,miner2,miner3 \
START_PORT=random \
bash scripts/deploy/pm2/up-e2e-2validators.sh
```

Qué levanta:

- Central: directory + frontend + ledger
- Miners: 3 procesos (axon ports consecutivos)
- Validator 1: `INDEXER_TEE_ENABLED=true` (attested)
- Validator 2: `INDEXER_TEE_ENABLED=false` (dangerous, ledger lo deniega)

Opcional (para pruebas de seguridad):

- Mock "no attestation" en validator2:
  - `INDEXER_DISABLE_BUNDLE_VALI2=true`
- Mock "no TEE" en validator1:
  - `INDEXER_TEE_ENABLED_VALI1=false`

Verificación rápida:

- Directory rooms: `GET <directory>/rooms`
- Indexer state: `GET <indexer>/directory/state` (deberías ver `danger_reason=tee_disabled` en validator2)
- Ledger denial:
  - `POST <ledger>/api/v1/ledger/buyin` con `validatorId` del validator2 -> 403
- Frontend: abre `http://127.0.0.1:<frontend_port>/poker-gameplay`
  - Login: `test@poker44.com` / `password`

## Tests

- Subnet:
  - `cd poker44-subnet && ./validator_env/bin/python -m pytest -q`
- Backend:
  - `cd platform/backend && npm test`
- Frontend:
  - `cd platform/frontend && npm test && npm run lint && npm run typecheck`

## Notas / TODOs (intencionales por MVP)

- Attestation es mock (no TEE real, no IPFS, no anclaje on-chain de commitments).
- Token en `localStorage` es un tradeoff para evitar cookies cross-domain en MVP.
- Join mid-game no está soportado: las mesas públicas rotan a un nuevo `room_code` cuando arrancan.
- Scoring es baseline; anti-collusion y scoring robusto vendrá después.
