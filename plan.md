# Implementation Plan: Face-Web-Blockchain Pipeline

## Phase 0 — Project Scaffolding

| Task | Details |
|------|---------|
| Re-init git inside `HH GOA/` | Current repo is at home directory level |
| Create `.gitignore` | Exclude `.env`, `__pycache__`, `*.db`, `uploads/` |
| Create `requirements.txt` | Pin all deps including `insightface`, `onnxruntime`, `web3` |
| Install missing packages | `pip install insightface onnxruntime web3` |
| Create `__init__.py` files | For every Python package directory |
| Create `.env` placeholder | For API keys, wallet private key, RPC URL |

## Phase 1 — Face Detection + Embedding (Module 2)

| File | What it does |
|------|-------------|
| `backend/face/detector.py` | Detect faces in image, return bounding box + confidence |
| `backend/face/embedder.py` | Generate 512-d InsightFace embedding vector |
| `tests/test_face.py` | Run on 5+ images, verify consistency |

## Phase 2 — Visual Search (Module 3) ⚠️ HIGH RISK

| File | What it does |
|------|-------------|
| `backend/search/visual_search.py` | Reverse image search → candidate URLs |
| `backend/search/search_models.py` | Data classes for search results |
| `tests/test_search.py` | Validate at least 1 accessible public post found |

**Key decision needed**: Which search API? Options:
- **Bing Visual Search API** — easiest, free tier available
- **SerpAPI** — has reverse image search support
- **Yandex scraping** — free but fragile/ToS-violating
- **TinEye API** — good but limited free tier

## Phase 3 — Candidate Collection + Face Matching (Module 4 + 5)

| File | What it does |
|------|-------------|
| `backend/crawler/collector.py` | Fetch pages, download candidate images |
| `backend/crawler/parser.py` | Parse HTML, extract image/text/metadata |
| `backend/face/matcher.py` | Cosine similarity between embeddings |
| `tests/test_matching.py` | Verify threshold of 0.4+ works |

## Phase 4 — Content Fingerprinting (Module 6)

| File | What it does |
|------|-------------|
| `backend/fingerprint/canonicalizer.py` | Build canonical JSON record |
| `backend/fingerprint/hasher.py` | SHA-256 hashing |
| `tests/test_hashing.py` | Same data → same hash, modified → different hash |

## Phase 5 — Blockchain (Module 7 + 8)

| File | What it does |
|------|-------------|
| `contracts/ContentRegistry.sol` | Solidity contract (register + verify) |
| `backend/blockchain/contract.py` | ABI + web3 connection |
| `backend/blockchain/registry.py` | `register(hash) → tx_hash` |
| `backend/blockchain/verifier.py` | `verify(hash) → True/False` |
| `tests/test_blockchain.py` | Deploy to Sepolia, test register/verify |

**Requires**: Sepolia testnet ETH (faucet), wallet private key in `.env`

## Phase 6 — API Layer (Module 1)

| File | What it does |
|------|-------------|
| `backend/api/schemas.py` | Pydantic request/response models |
| `backend/api/routes.py` | `POST /search`, `GET /search/{id}`, `GET /search/{id}/verify` |
| `backend/main.py` | FastAPI app, middleware, startup |
| `backend/database/models.py` | SQLite models (Job, DiscoveredPost, BlockchainRecord) |

## Phase 7 — Frontend

| File | What it does |
|------|-------------|
| `frontend/index.html` | Upload form, status display, results view |

---

## Open Questions

1. **Visual search API**: Do you have API keys for any of these (Bing, SerpAPI, Google Cloud Vision, TinEye)? Or should I go with a free/scraping approach?
2. **Blockchain wallet**: Do you have a Sepolia testnet wallet with ETH, or should I include setup instructions?
3. **Scope**: Should I build all 8 phases in one go, or focus on a specific subset first?
