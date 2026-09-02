# CLAUDE.md — Face-Web-Blockchain Pipeline

## Project Overview

A pipeline that takes a face scan as input, identifies matching content on the web/social media, and verifies that discovered data on a blockchain.

```
Face scan input → Web/social media search → Blockchain upload/verification
```

## Tech Stack

- **Backend**: FastAPI (Python)
- **Face Recognition**: InsightFace/ArcFace
- **Blockchain**: Ethereum testnet (Sepolia) via web3.py + Solidity contract
- **Database**: SQLite (simple, sufficient for MVP)
- **Frontend**: Simple HTML/JS (build last)

## Project Structure

```
face-web-blockchain/
├── backend/
│   ├── main.py                 # FastAPI app entry
│   ├── api/
│   │   ├── routes.py           # POST /search, GET /search/{id}, GET /search/{id}/verify
│   │   └── schemas.py          # Pydantic models
│   ├── face/
│   │   ├── detector.py         # Face detection + bounding box
│   │   ├── embedder.py         # Generate face embedding vector
│   │   └── matcher.py          # Compare two embeddings (cosine similarity)
│   ├── search/
│   │   ├── visual_search.py    # Reverse image search → candidate URLs
│   │   └── search_models.py    # Data classes for search results
│   ├── crawler/
│   │   ├── collector.py        # Fetch candidate pages, extract content
│   │   └── parser.py           # Parse HTML, extract image/text/metadata
│   ├── fingerprint/
│   │   ├── canonicalizer.py    # Build canonical JSON record
│   │   └── hasher.py           # SHA-256 hashing
│   ├── blockchain/
│   │   ├── contract.py         # ABI + contract interaction
│   │   ├── registry.py         # register(hash) → tx_hash
│   │   └── verifier.py         # verify(hash) → True/False
│   └── database/
│       └── models.py           # SQLite models (Job, DiscoveredPost, BlockchainRecord)
├── contracts/
│   └── ContentRegistry.sol     # Solidity smart contract
├── frontend/
│   └── index.html
├── tests/
│   ├── test_face.py
│   ├── test_search.py
│   ├── test_matching.py
│   ├── test_hashing.py
│   └── test_blockchain.py
├── requirements.txt
└── README.md
```

## Module Specifications

### Module 1 — Input/API

**Function**: Accept image upload, create job, pass to pipeline.

```python
upload_image(image) → job_id
```

- Validate: JPEG/PNG, max 10MB
- Generate UUID job ID
- Save to temp directory
- Return `job_id` immediately, run pipeline async

---

### Module 2 — Face Analysis

**Function**: Detect face, generate embedding vector.

```python
extract_face(image) → FaceData
# FaceData = { embedding: list[float], confidence: float, bbox: dict }
```

- Use InsightFace buffalo_l model (or arcface_r100)
- Return 512-d embedding vector
- Handle: no face found, multiple faces (use largest/highest confidence)
- **Test**: Run on 5+ different images, verify embeddings are consistent

---

### Module 3 — Visual Search

**Function**: Use input image to search web for matching posts.

```python
search_web(image) → list[SearchResult]
# SearchResult = { url: str, image_url: str, title: str }
```

**This is the highest-risk module.** Options to evaluate:
- Google Lens API (if accessible)
- Yandex reverse image search (scrape results)
- TinEye API
- Bing Visual Search API
- SerpAPI with image search parameter

**Success criterion**: Can the system genuinely discover at least one accessible public post from the input?

**Test early** — before building anything else.

---

### Module 4 — Candidate Collection

**Function**: Fetch content from discovered URLs.

```python
collect_candidate(search_result) → CandidateContent
# CandidateContent = { source_url, image_url, caption, title, platform }
```

- Use `requests` + `BeautifulSoup`
- Handle: login-required pages, deleted content, robots.txt blocks
- Download candidate images to temp storage
- Extract: URL, image, caption/text, page title, platform name

---

### Module 5 — Face Matching

**Function**: Compare original embedding with candidate face.

```python
match_face(original_embedding, candidate_image) → MatchResult
# MatchResult = { match: bool, score: float, candidate: CandidateContent }
```

- Extract face from candidate image (same as Module 2)
- Compare embeddings using cosine similarity
- **Threshold**: 0.4+ for InsightFace (document your chosen threshold)
- Return all candidates with scores, flag matches above threshold

---

### Module 6 — Content Fingerprinting

**Function**: Create tamper-evident hash of matched content.

```python
fingerprint(content) → str  # SHA-256 hex string
```

- Build canonical JSON:
  ```json
  {
    "schema_version": "1",
    "post_url": "...",
    "image_sha256": "...",
    "caption": "...",
    "timestamp": "..."
  }
  ```
- Hash with SHA-256
- **Test**: Same data → same hash, modified data → different hash

---

### Module 7 — Blockchain Registry

**Function**: Write content hash to blockchain.

```python
register_on_blockchain(content_hash) → str  # transaction hash
```

- Solidity contract `ContentRegistry.sol`:
  ```solidity
  mapping(bytes32 => bool) public registered;
  function register(bytes32 contentHash) external;
  function verify(bytes32 contentHash) external view returns (bool);
  ```
- Use Sepolia testnet (free, no real ETH needed)
- Fund wallet via Sepolia faucet
- Use web3.py to interact
- Store: `tx_hash`, `block_number`, `job_id`

---

### Module 8 — Verification

**Function**: Verify content hash exists on blockchain.

```python
verify_on_blockchain(content_hash) → bool
```

- Call `registered[content_hash]` on contract
- Return `True` if exists, `False` otherwise
- **Tampering demo**: Modify content → re-hash → verify fails

---

## Database Schema

```sql
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,
    input_image_path TEXT,
    created_at TIMESTAMP,
    status TEXT
);

CREATE TABLE discovered_posts (
    id INTEGER PRIMARY KEY,
    job_id TEXT,
    post_url TEXT,
    image_url TEXT,
    platform TEXT,
    caption TEXT,
    face_similarity FLOAT,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE TABLE blockchain_records (
    id INTEGER PRIMARY KEY,
    job_id TEXT,
    content_hash TEXT,
    transaction_hash TEXT,
    block_number INTEGER,
    registered_at TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);
```

---

## API Endpoints

```python
POST /api/search
    Body: multipart/form-data with image file
    Response: { "job_id": "...", "status": "processing" }

GET /api/search/{job_id}
    Response: {
        "job_id": "...",
        "status": "complete",
        "face_detected": true,
        "match_found": true,
        "matched_post": { "url": "...", "platform": "...", "similarity": 0.89 },
        "blockchain": { "content_hash": "...", "tx_hash": "...", "verified": true }
    }

GET /api/search/{job_id}/verify
    Response: { "verified": true, "on_chain": true, "hash_matches": true }
```

---

## Build Order (Critical)

1. **Phase 1**: Face detection + embedding (Module 2)
2. **Phase 2**: Visual search proof-of-concept (Module 3) ← **DO THIS EARLY**
3. **Phase 3**: Face matching (Module 5) — connect search + face
4. **Phase 4**: Content fingerprinting (Module 6)
5. **Phase 5**: Blockchain contract + registry (Module 7)
6. **Phase 6**: Verification (Module 8)
7. **Phase 7**: API (Module 1) — connect all modules
8. **Phase 8**: Frontend — only after backend works

---

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run individual module tests
python -m pytest tests/test_face.py -v
python -m pytest tests/test_search.py -v
python -m pytest tests/test_matching.py -v
python -m pytest tests/test_hashing.py -v
python -m pytest tests/test_blockchain.py -v
```

---

## Key Decisions to Document

1. **Face model chosen**: InsightFace buffalo_l (or alternative)
2. **Visual search method**: [TBD — evaluate options in Phase 2]
3. **Similarity threshold**: 0.4 (document validation approach)
4. **Blockchain network**: Sepolia testnet
5. **Contract address**: [paste after deployment]

---

## Requirements

```
fastapi
uvicorn
opencv-python-headless
insightface
onnxruntime
numpy
requests
beautifulsoup4
web3
python-multipart
pytest
```

---

## Security Notes

- Never commit API keys or wallet private keys
- Use `.env` file for secrets (add to `.gitignore`)
- Limit file upload size
- Validate all URLs before fetching
- Don't follow redirects blindly when crawling
