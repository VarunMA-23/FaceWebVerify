<div align="center">

# 🔍 Face → Web → Blockchain Pipeline

**Find a face on the web, fingerprint the post, and prove it on-chain.**

```
Face scan  →  Reverse image search  →  Face match  →  SHA-256 fingerprint  →  Blockchain verification
```

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.6.0+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Solidity](https://img.shields.io/badge/Solidity-^0.8.20-363636?logo=solidity)](https://docs.soliditylang.org/)
[![Tests](https://img.shields.io/badge/tests-passing-2ea44f)]()
[![License](https://img.shields.io/badge/license-MIT-blue)]()

Upload a photo of a face → the pipeline reverse-searches the web, locates
matching public content (verified against the real post *and* thumbnails),
fingerprints the matched post with SHA-256, and can register that hash on the
**Sepolia** Ethereum testnet for tamper-evident attestation.

</div>

---

## ✨ Features

- 🧬 **512-D face embeddings** via InsightFace `buffalo_l` (ArcFace recognition head)
- 🔎 **Reverse image search** across multiple providers (OpenWeb Ninja, Bing,
  SerpAPI, TinEye) with automatic fallback
- ✅ **Tiered face matching** — evidence from *page content* (verified) *and*
  search *thumbnails* (login-walled posts)
- 🔐 **Tamper-evident fingerprinting** — canonical record → SHA-256 hash
- ⛓️ **On-chain registration** — `ContentRegistry.sol` on Sepolia
- 🖥️ **FastAPI REST API + simple HTML frontend**

---

## 🧠 How it works

```
┌────────────┐   ┌─────────────────┐   ┌──────────────────┐   ┌───────────────┐
│ Upload     │ → │ Visual search   │ → │ Tiered face      │ → │ Fingerprint   │
│ face image │   │ (multiple APIs) │   │ matching         │   │ (SHA-256)     │
└────────────┘   └─────────────────┘   └──────────────────┘   └───────┬───────┘
                                                                      ▼
                                                          ┌───────────────────┐
                                                          │ Blockchain        │
                                                          │ register + verify │
                                                          └───────────────────┘
```

### Evidence tiers
| Tier | Source | Meaning |
|------|--------|---------|
| 🟢 `verified` | Real post content image (page crawl) | Strongest evidence |
| 🟡 `thumbnail` | Search thumbnail only | Likely a login-walled post |
| ⚫ `none` | — | No face match |

---

## 📦 Quick start

### Prerequisites
- Python **3.9+**
- (Optional) Node/npx — only needed to compile the Solidity contract

### 1. Clone & set up

```bash
# Clone the repo (or use your existing checkout)
git clone <your-repo-url>
cd face-web-blockchain

# Create a virtual environment
python -m venv .venv

# Activate it
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

On first face-model use, InsightFace automatically downloads `buffalo_l`
into `models/`.

### 3. Configure secrets

```bash
# Copy the example env file
copy .env.example .env          # Windows (cmd)
cp .env.example .env            # macOS / Linux

# Edit .env and add at least one search API key + (optional) blockchain keys
```

`.env` expects (see `.env.example`):

```ini
# Reverse image search — provide at least ONE of these
BING_SEARCH_API_KEY=
OPENWEBNINJA_API_KEY=
SERPAPI_API_KEY=
TINEYE_API_KEY=

# Blockchain — optional
# Local hash-linked Merkle ledger is the DEFAULT anchor backend (no config).
# EVM (Sepolia) is opt-in via BLOCKCHAIN_ANCHOR=evm (requires `pip install -r requirements-evm.txt`):
SEPOLIA_RPC_URL=https://ethereum-sepolia-rpc.publicnode.com
SEPOLIA_WALLET_PRIVATE_KEY=
SEPOLIA_CONTRACT_ADDRESS=
# BLOCKCHAIN_ANCHOR=local | evm | none        (default: local)
# BLOCKCHAIN_DIFFICULTY=0                     (local chain PoW bits, 0 = off)
```

> ⚠️ **Never commit `.env`.** It is git-ignored. Your keys stay local.

---

## ▶️ Running the pipeline (CLI)

The standalone runner executes the full end-to-end flow on a single image:

```bash
python run_pipeline.py <image_path> [options]
```

### Options
| Flag | Default | Description |
|------|---------|-------------|
| `--limit N` | `5` | Max candidates to evaluate |
| `--match-threshold F` | `0.4` | Cosine-similarity match threshold |
| `--evidence-tier` | `all` | `all` or `verified_only` (which match tiers qualify) |
| `--do-blockchain` | off | Force blockchain registration |
| `--no-blockchain` | — | Skip blockchain step |

### Examples

```bash
# Basic run (detect, search, match, fingerprint)
python run_pipeline.py myface.jpg

# Only accept verified (page-content) matches, evaluate 10 candidates
python run_pipeline.py myface.jpg --limit 10 --evidence-tier verified_only

# Include on-chain registration + verification.
# Anchors to the local Merkle ledger by default; pass --anchor evm to use Sepolia.
python run_pipeline.py myface.jpg --do-blockchain

# Raise the match threshold
python run_pipeline.py myface.jpg --match-threshold 0.5
```

---

## 🌐 Running the web app (FastAPI)

```bash
# Start the API server (auto-reload for development)
uvicorn backend.main:app --reload
```

- **API docs (Swagger UI):** <http://127.0.0.1:8000/docs>
- **Frontend:** <http://127.0.0.1:8000/>
- **Health check:** <http://127.0.0.1:8000/api/health>

### API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/search` | Upload a face image (`multipart/form-data`, max 10 MB, JPEG/PNG/WebP). Returns a `job_id` immediately. |
| `GET` | `/api/search/{job_id}` | Poll for the pipeline result (status, matches, blockchain summary). |
| `GET` | `/api/search/{job_id}/verify` | Verify the on-chain fingerprint for the job. |
| `GET` | `/api/health` | Service health check. |

**Example — start a search:**

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -F "file=@myface.jpg" -F "limit=5" -F "threshold=0.4"
```

**Example — poll a job while it runs:**

```bash
curl http://127.0.0.1:8000/api/search/<job_id>
```

**Example — verify on-chain:**

```bash
curl http://127.0.0.1:8000/api/search/<job_id>/verify
```

---

## 🧪 Running tests

```bash
# Run the whole suite
python -m pytest tests/ -v
```

### Run individual modules

```bash
python -m pytest tests/test_face.py -v          # Detection + embeddings
python -m pytest tests/test_search.py -v        # Reverse visual search
python -m pytest tests/test_matching.py -v      # Face similarity / threshold
python -m pytest tests/test_matching_service.py -v  # Tiered matching service
python -m pytest tests/test_hashing.py -v       # Fingerprinting (SHA-256)
python -m pytest tests/test_blockchain.py -v    # Contract interaction
python -m pytest tests/test_database.py -v      # SQLite persistence
python -m pytest tests/test_api.py -v           # HTTP API
```

> **Live tests** (hitting real APIs / chain) are **auto-skipped** unless the
> matching credentials are present:

| Test | Needs to run live |
|------|-------------------|
| `tests/test_search.py` live tests | `OPENWEBNINJA_API_KEY`, `BING_SEARCH_API_KEY`, `SERPAPI_API_KEY`, or `TINEYE_API_KEY` |
| `tests/test_blockchain.py` live test | `SEPOLIA_WALLET_PRIVATE_KEY` + `SEPOLIA_CONTRACT_ADDRESS` |

---

## ⛓️ Deploying the smart contract

The contract lives at `contracts/ContentRegistry.sol`.

```bash
# Compile to ABI + bytecode (needs Node/npx)
npx solc@0.8.21 --abi --bin contracts\ContentRegistry.sol
```

Then:
1. Fund a wallet with **Sepolia ETH** (use a faucet — it's free testnet ETH).
2. Set `SEPOLIA_WALLET_PRIVATE_KEY` and `SEPOLIA_RPC_URL` in `.env`.
3. Deploy `ContentRegistry` with your preferred tool (Remix, a web3 script, etc.).
4. Paste the deployed address into `SEPOLIA_CONTRACT_ADDRESS`.

---

## 🗂️ Project structure

```
face-web-blockchain/
├── backend/
│   ├── main.py                 # FastAPI entry point (mounts API + frontend)
│   ├── api/
│   │   ├── routes.py           # POST /search, GET /search/{id}, GET /search/{id}/verify
│   │   └── schemas.py          # Pydantic response models
│   ├── face/
│   │   ├── detector.py         # Face detection + bounding box
│   │   ├── embedder.py         # 512-d face embedding
│   │   └── matcher.py          # Cosine-similarity matching + evidence tiers
│   ├── search/
│   │   ├── visual_search.py    # Reverse image search (multi-provider fallback)
│   │   ├── image_host.py       # Publish local uploads to a temp public URL
│   │   └── search_models.py    # Search-result data classes
│   ├── crawler/
│   │   ├── collector.py        # Fetch candidate pages, download images
│   │   └── parser.py           # Parse HTML → image/text/metadata
│   ├── matching/
│   │   └── service.py          # Tiered (thumbnail + page) match orchestration
│   ├── fingerprint/
│   │   ├── canonicalizer.py    # Build canonical ContentRecord
│   │   └── hasher.py           # SHA-256 hashing
│   ├── blockchain/
│   │   ├── contract.py         # ABI + contract interaction
│   │   ├── registry.py         # register(hash) → tx_hash
│   │   └── verifier.py         # verify(hash) → bool
│   ├── pipeline/
│   │   └── runner.py           # End-to-end job orchestration
│   └── database/
│       └── models.py           # SQLite (jobs, discovered_posts, blockchain_records)
├── contracts/
│   └── ContentRegistry.sol     # Solidity smart contract
├── frontend/
│   └── index.html              # Simple web UI
├── tests/                      # Pytest suite (unit + mocked + live)
├── models/                     # Downloaded InsightFace models (generated)
├── requirements.txt
├── run_pipeline.py             # Standalone CLI runner
└── .env.example                # Template for secrets
```

---

## 📐 Module map

| Module | Code | Purpose |
|--------|------|---------|
| 1 — Input/API | `backend/api/`, `backend/pipeline/` | Accept upload, create job, run async |
| 2 — Face analysis | `backend/face/` | Detect + embed a face (512-d) |
| 3 — Visual search | `backend/search/` | Find candidate posts on the web |
| 4 — Candidate collection | `backend/crawler/` | Fetch pages + download images |
| 5 — Face matching | `backend/face/`, `backend/matching/` | Compare faces, flag matches |
| 6 — Fingerprinting | `backend/fingerprint/` | Canonical record + SHA-256 |
| 7 — Blockchain registry | `backend/blockchain/registry.py` | Register hash on-chain |
| 8 — Verification | `backend/blockchain/verifier.py` | Verify hash exists on-chain |

---

## 🔑 Key design decisions

1. **Face model** — InsightFace `buffalo_l` (ArcFace recognition head), 512-d
   L2-normalized embeddings, CPU provider by default.
2. **Visual search** — provider list (OpenWeb Ninja, Bing Visual Search API,
   SerpAPI, TinEye), chosen by which keys exist in `.env`. `search_web()`
   falls through to the first provider that returns results. OpenWeb Ninja and
   SerpAPI search by image URL, so local uploads are published to a temporary
   public host first (`backend/search/image_host.py`).
3. **Similarity threshold** — `0.4` cosine similarity (InsightFace convention).
   `tests/test_matching.py` asserts the same image embedded twice scores above it.
4. **Blockchain network** — Sepolia testnet (free, no real ETH).
5. **Contract address** — not deployed yet; paste into `SEPOLIA_CONTRACT_ADDRESS`
   after deployment (see *Deploying the smart contract*).

---

## ⚠️ Security notes

- Secrets live in `.env` (git-ignored) — **never commit API keys or wallet keys**.
- Uploads are limited to **10 MB** and only `JPEG`/`PNG`/`WebP`.
- All outbound URLs are **validated before fetch**; redirects are **not**
  followed blindly (`allow_redirects=False`).

---

## 🛠️ Tech stack

| Area | Technology |
|------|-----------|
| Backend | Python, **FastAPI**, Uvicorn |
| Face recognition | **InsightFace** (buffalo_l / ArcFace), ONNX Runtime, OpenCV |
| Web scraping | Requests + BeautifulSoup |
| Blockchain | Solidity ^0.8.20, **web3.py**, Sepolia testnet |
| Database | SQLite |
| Tests | Pytest |

---

## 📜 License

[MIT](LICENSE)

---

<div align="center">

**Built with ❤️ for discovering and protecting content — one face at a time.**

</div>
