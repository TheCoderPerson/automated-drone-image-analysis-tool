# ADIAT Client-Server Architecture Feasibility Analysis

## Executive Summary

Converting ADIAT to a client-server architecture is **technically feasible but represents a significant undertaking**. The current desktop-only Qt application would require substantial rearchitecting to support web-based remote review. This document analyzes the viability, performance implications, and implementation challenges of such a system.

**Key Findings:**
- ✅ **Feasible** for 2-5 concurrent users with proper infrastructure
- ⚠️ **Challenging** for 5-10 concurrent users over WAN without cloud relay
- 📊 **Progressive loading** is essential for acceptable user experience
- 🔧 **Significant development effort** required (estimated 3-6 months for experienced team)
- 💰 **Infrastructure costs** may be necessary for reliable WAN access

---

## 1. Current Architecture Overview

### Technology Stack
| Component | Current Technology |
|-----------|-------------------|
| UI Framework | PySide6 (Qt 6) - Desktop only |
| Data Storage | XML files (ADIAT_Data.xml) |
| Image Cache | Local filesystem |
| Processing | Multi-process (local CPU) |
| Networking | None (consumer of RTMP streams only) |

### Data Flow Summary
```
Images (filesystem) → Processing (local) → XML Results → Qt Viewer → Local Display
```

### Key Metrics from Codebase Analysis
| Metric | Value |
|--------|-------|
| Full image load | 12-50 MB per image (4000x3000 to 8000x5000) |
| Thumbnail size | ~10 KB (180×180 JPEG @ 80% quality) |
| Mask file size | ~100 KB (grayscale PNG) |
| AOI metadata | ~500 bytes per AOI |
| Typical dataset | 1,000-10,000 images |
| AOIs per image | 10-150+ (target: 10-20) |

---

## 2. Proposed Client-Server Architecture

### High-Level Design
```
┌─────────────────────────────────────────────────────────────────┐
│                        MAIN COMPUTER                            │
│                    (Desktop Workstation)                        │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   ADIAT     │  │   REST API  │  │    Image Server         │  │
│  │ Processing  │──│   Server    │──│  (Static Files +        │  │
│  │   Engine    │  │  (FastAPI)  │  │   Progressive JPEG)     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│         │               │                    │                   │
│         └───────────────┴────────────────────┘                   │
│                         │                                        │
│              ┌──────────┴──────────┐                            │
│              │   WebSocket Server  │                            │
│              │  (Real-time Sync)   │                            │
│              └──────────┬──────────┘                            │
└─────────────────────────┼───────────────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              │    INTERNET / WAN     │
              └───────────┬───────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
   │ Browser │      │ Browser │      │ Browser │
   │Client 1 │      │Client 2 │      │Client 3 │
   └─────────┘      └─────────┘      └─────────┘
```

### Required New Components

| Component | Purpose | Technology Options |
|-----------|---------|-------------------|
| REST API Server | Serve data, handle annotations | FastAPI, Flask |
| WebSocket Server | Real-time updates, sync | Socket.IO, native WebSockets |
| Image Server | Serve images with caching | nginx, CDN, or built-in |
| Web UI | Browser-based viewer | React, Vue, or Svelte |
| Database | Multi-user annotations | SQLite or PostgreSQL |
| Authentication | User management | JWT tokens, sessions |

---

## 3. Data Transfer Analysis

### Image Size Breakdown

For an **8000×5000 pixel JPEG** (typical high-resolution drone image):

| Quality Level | Approximate Size | Use Case |
|---------------|------------------|----------|
| Thumbnail (180×112) | 5-10 KB | Gallery grid |
| Preview (1600×1000) | 150-300 KB | Initial view |
| Medium (3200×2000) | 600 KB - 1.2 MB | Detailed review |
| Full (8000×5000) | 6-12 MB | Pixel-level inspection |

### Transfer Time Estimates

Based on typical internet connection speeds:

| Connection Type | Upload Speed | 8MB Image Transfer | 300KB Preview |
|-----------------|--------------|--------------------| --------------|
| Basic Broadband | 10 Mbps | 6.4 seconds | 240 ms |
| Standard Broadband | 25 Mbps | 2.6 seconds | 96 ms |
| Fast Broadband | 50 Mbps | 1.3 seconds | 48 ms |
| Fiber | 100 Mbps | 0.64 seconds | 24 ms |
| Gigabit Fiber | 1 Gbps | 64 ms | 2.4 ms |

### Progressive Loading Strategy

**Recommended 3-tier approach:**

```
User clicks AOI → Thumbnail (instant, cached)
                → Preview loads (200-500ms)  ← User sees image quickly
                → Full resolution loads (2-10s) ← Details available for zoom
```

**Implementation: Progressive JPEG or Image Pyramid**

```
Tier 1: Thumbnail    │ 180×112   │  ~8 KB   │ Pre-cached, instant
Tier 2: Preview      │ 1600×1000 │  ~250 KB │ 100-500ms load
Tier 3: Full Detail  │ 8000×5000 │  ~8 MB   │ 1-10s (background)
```

### Bandwidth Requirements

**Per-User Bandwidth Consumption:**

| Activity | Data Per Action | Frequency | Bandwidth Impact |
|----------|-----------------|-----------|------------------|
| Load gallery (150 images, 2250 AOIs) | ~22.5 MB thumbnails | Once per batch | Burst, cacheable |
| Switch to new image | 250 KB preview + 8 MB full | Every 10-30 sec | 8.25 MB/switch |
| AOI metadata load | ~1 MB | With image | Minimal |
| Flag/comment AOI | ~1 KB | Frequent | Negligible |

**Server Upload Requirement (WAN scenario):**

| Concurrent Users | Peak Burst (all switching images) | Sustained | Required Upload |
|------------------|-----------------------------------|-----------|-----------------|
| 2 users | 16 MB | 0.5 MB/s | 25 Mbps |
| 5 users | 40 MB | 1.3 MB/s | 50 Mbps |
| 10 users | 80 MB | 2.6 MB/s | 100 Mbps |

⚠️ **Critical Issue**: Most residential/small office connections have **asymmetric bandwidth** with upload speeds 10-20% of download. A 100 Mbps download connection may only have 10-20 Mbps upload.

---

## 4. Latency Analysis

### Click-to-Display Timeline

**Scenario: User clicks AOI in gallery to view full image**

```
Timeline (25 Mbps upload from server):

0ms     ─ User clicks AOI in gallery
         │
50ms    ─ WebSocket request reaches server
         │
100ms   ─ Server identifies image, AOI data sent
         │
150ms   ─ Client receives AOI metadata
         │
200ms   ─ Preview request initiated
         │
350ms   ─ Preview image received (250KB @ 25Mbps = ~80ms + overhead)
         │
400ms   ─ Preview displayed, zoom to AOI ← USER SEES RESULT
         │
400ms   ─ Full resolution request initiated (background)
         │
3000ms  ─ Full resolution received (8MB @ 25Mbps = ~2.5s)
         │
3100ms  ─ Full resolution swapped in ← HIGH DETAIL AVAILABLE
```

**Perceived Latency: ~400ms** (acceptable for interactive use)
**Full Detail Available: ~3 seconds** (acceptable with progressive loading)

### Latency Comparison by Network

| Network Type | RTT Latency | Preview Display | Full Resolution |
|--------------|-------------|-----------------|-----------------|
| Local LAN | 1-5 ms | 50-100 ms | 200-500 ms |
| Same City WAN | 10-30 ms | 200-400 ms | 2-4 seconds |
| Cross-Country WAN | 50-100 ms | 400-700 ms | 4-8 seconds |
| International | 100-300 ms | 700-1200 ms | 8-15 seconds |

---

## 5. Concurrent User Analysis

### Server Resource Requirements

**Per-Client Resource Usage:**

| Resource | Per Client | 5 Clients | 10 Clients |
|----------|------------|-----------|------------|
| WebSocket connection | 1 socket | 5 sockets | 10 sockets |
| Memory (active session) | 50-100 MB | 250-500 MB | 0.5-1 GB |
| Peak image serving | 8 MB | 40 MB | 80 MB |
| Database connections | 1 | 5 | 10 |

**Desktop Workstation Limits:**

| Component | Typical Spec | Practical Limit |
|-----------|--------------|-----------------|
| CPU | 8-16 cores | 10-20 concurrent image encodes |
| RAM | 32-64 GB | 20-40 active image sessions |
| Disk I/O | 500 MB/s SSD | 50-100 concurrent reads |
| Network Upload | 10-50 Mbps | 2-10 concurrent image streams |

### Realistic Concurrent User Limits

| Scenario | Max Users | Limiting Factor |
|----------|-----------|-----------------|
| LAN (Gigabit) | 20-50 | CPU/Memory |
| WAN (50 Mbps upload) | 5-8 | Upload bandwidth |
| WAN (100 Mbps upload) | 10-15 | Upload bandwidth |
| WAN (10 Mbps upload) | 2-3 | Upload bandwidth |

**⚠️ The upload bandwidth of the server machine is typically the primary bottleneck for WAN deployments.**

---

## 6. Multi-User Annotation System

### Proposed Data Model

```sql
-- Example schema for multi-user annotations
CREATE TABLE aoi_reviews (
    id INTEGER PRIMARY KEY,
    image_index INTEGER,
    aoi_index INTEGER,
    user_id TEXT,
    flagged BOOLEAN,
    comment TEXT,
    timestamp DATETIME,
    session_id TEXT
);

-- Aggregation query example
SELECT image_index, aoi_index,
       COUNT(*) FILTER (WHERE flagged = true) as flag_count,
       GROUP_CONCAT(DISTINCT comment) as all_comments
FROM aoi_reviews
GROUP BY image_index, aoi_index;
```

### Work Distribution System

**Batch Assignment (150 images per reviewer):**

```
Dataset: 1500 images (10,000+ AOIs)
                │
        ┌───────┼───────┐
        ▼       ▼       ▼
    Batch 1   Batch 2   Batch 3  ... Batch 10
    (1-150)  (151-300) (301-450)
        │       │         │
    Reviewer A  Reviewer B  Reviewer C
```

**Features Needed:**
- Batch assignment/checkout system
- Progress tracking per reviewer
- Conflict detection (if same batch assigned to multiple reviewers)
- Merge/aggregate final results

---

## 7. Potential Issues and Challenges

### 7.1 Network Challenges

| Challenge | Impact | Mitigation |
|-----------|--------|------------|
| **NAT/Firewall** | Server not directly accessible | Port forwarding, or relay service (ngrok, Cloudflare Tunnel) |
| **Dynamic IP** | Server address changes | Dynamic DNS (DuckDNS, No-IP) or relay |
| **Upload bandwidth** | Slow image delivery | Cloud relay/CDN, aggressive caching |
| **Connection drops** | Lost work, reconnection needed | Auto-reconnect, local state preservation |
| **SSL/HTTPS** | Required for security | Let's Encrypt, or relay with built-in SSL |

### 7.2 Technical Challenges

| Challenge | Description | Complexity |
|-----------|-------------|------------|
| **Image format conversion** | Generate progressive JPEGs, tiles | Medium |
| **Session management** | Track user state, handle disconnects | Medium |
| **Concurrent file access** | Multiple users reading same images | Low-Medium |
| **Data synchronization** | Merge annotations from multiple users | Medium-High |
| **Offline capability** | Handle temporary disconnections | High |
| **Authentication/Security** | Protect data, manage access | Medium |

### 7.3 User Experience Challenges

| Challenge | Description | Solution |
|-----------|-------------|----------|
| **Initial load time** | Gallery with 2000+ thumbnails | Virtualized list, lazy loading |
| **Image zoom lag** | Full-res not immediately available | Progressive loading, visual feedback |
| **Annotation conflicts** | Two users modify same AOI | Last-write-wins or merge UI |
| **Network indicator** | User unaware of connection issues | Connection status indicator |

### 7.4 Deployment Challenges

| Challenge | For Desktop Workstation Server |
|-----------|-------------------------------|
| Always-on requirement | Workstation must stay running during review sessions |
| Port accessibility | Router/firewall configuration needed |
| Security exposure | Machine exposed to internet traffic |
| Resource contention | Server duties compete with other workstation tasks |

---

## 8. Implementation Approach Options

### Option A: Embedded Web Server (Recommended for Your Use Case)

**Add web server directly to ADIAT desktop application**

```
┌─────────────────────────────────────────┐
│           ADIAT Desktop App             │
├─────────────────────────────────────────┤
│  Existing Qt UI (local use)             │
│  + Embedded FastAPI server              │
│  + Static file server for images        │
│  + WebSocket for real-time updates      │
└─────────────────────────────────────────┘
         ▲
         │ HTTP/WebSocket
         ▼
┌─────────────────────────────────────────┐
│         Web Browser Clients             │
│    (Lightweight review-only UI)         │
└─────────────────────────────────────────┘
```

**Pros:**
- Single application to deploy
- Existing processing engine reused
- Local user still has full Qt interface
- Lower development effort

**Cons:**
- Workstation must stay running
- Limited scalability
- Upload bandwidth constrained

**Estimated Effort:** 2-4 months

---

### Option B: Dedicated Server Application

**Separate server application that can run on cloud infrastructure**

```
┌────────────────┐      ┌─────────────────────────┐
│ ADIAT Desktop  │──────│   ADIAT Server          │
│ (Processing)   │upload│   (Cloud/Dedicated)     │
└────────────────┘      │   - REST API            │
                        │   - Image storage       │
                        │   - User management     │
                        └───────────┬─────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
                Browser         Browser         Browser
```

**Pros:**
- Better scalability (cloud resources)
- Reliable connectivity (static IP, good bandwidth)
- Processing can continue while review happens
- Can support more concurrent users

**Cons:**
- Higher development effort
- Cloud hosting costs ($50-200/month)
- Data upload/sync complexity
- Two applications to maintain

**Estimated Effort:** 4-8 months

---

### Option C: Hybrid with Relay Service

**Desktop app + cloud relay for connectivity**

```
┌────────────────┐      ┌─────────────────┐      ┌─────────────┐
│ ADIAT Desktop  │◄────►│  Relay Service  │◄────►│   Browsers  │
│ + Web Server   │tunnel│  (Cloudflare/   │      │             │
└────────────────┘      │   ngrok/custom) │      └─────────────┘
                        └─────────────────┘
```

**Pros:**
- Solves NAT/firewall issues
- Provides SSL automatically
- Can cache images at edge (CDN benefit)
- Desktop workstation can have any connection

**Cons:**
- Dependency on third-party service
- Potential costs (ngrok: $8-20/month, Cloudflare: free-$20/month)
- Additional latency through relay
- Data passes through third party

**Estimated Effort:** 2-4 months (plus relay setup)

---

## 9. Distributed Processing Analysis

### Current Processing Architecture

```python
# Current: Local multiprocessing
AnalyzeService.run():
    with ProcessPoolExecutor(max_workers=cpu_count) as pool:
        results = pool.map(process_image, images)
```

### Distributed Processing Options

**Option 1: Work Queue Pattern**

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Server    │────►│  Work Queue  │◄────│  Worker 1   │
│  (Manager)  │     │   (Redis)    │◄────│  Worker 2   │
└─────────────┘     └──────────────┘◄────│  Worker 3   │
                                          └─────────────┘
```

**Complexity:** High
- Need message queue (Redis, RabbitMQ)
- Workers need access to images (network storage or transfer)
- Result aggregation
- Error handling for failed workers

**Option 2: Direct Delegation**

```
┌─────────────┐ HTTP ┌─────────────┐
│   Server    │─────►│  Worker 1   │ (processes batch 1)
│  (Manager)  │─────►│  Worker 2   │ (processes batch 2)
└─────────────┘─────►│  Worker 3   │ (processes batch 3)
                     └─────────────┘
```

**Complexity:** Medium
- REST API on workers
- Image transfer over network
- Simpler than message queue
- Less fault-tolerant

### Distributed Processing Bandwidth

| Batch Size | Image Data | Network Time (100 Mbps) |
|------------|------------|-------------------------|
| 10 images | 100 MB | 8 seconds |
| 50 images | 500 MB | 40 seconds |
| 150 images | 1.5 GB | 2 minutes |

**Recommendation:** Distributed processing is viable for scenarios where:
- Processing time >> transfer time
- Workers are on fast LAN
- Very large datasets need parallel processing

For typical use cases (1000-10000 images on a modern workstation), local processing is likely sufficient and simpler.

---

## 10. Recommended Implementation Roadmap

### Phase 1: Core Web Viewer (MVP)
**Duration: 6-8 weeks**

1. **Backend API Layer**
   - FastAPI server embedded in ADIAT
   - REST endpoints for images, AOIs, metadata
   - Static file serving with caching headers

2. **Basic Web UI**
   - Gallery view with thumbnail grid
   - Image viewer with zoom/pan
   - AOI overlay rendering
   - Basic flag/comment functionality

3. **Progressive Image Loading**
   - Generate preview images (1600×1000)
   - Implement 2-tier loading (preview → full)

### Phase 2: Multi-User Features
**Duration: 4-6 weeks**

1. **User Sessions**
   - Simple authentication (invite links/passwords)
   - Session tracking

2. **Batch Assignment**
   - Divide images into review batches
   - Assign batches to reviewers
   - Track progress

3. **Annotation Aggregation**
   - Store per-user flags/comments
   - Aggregate view ("3 users flagged this")
   - Export combined results

### Phase 3: Production Hardening
**Duration: 3-4 weeks**

1. **Connectivity**
   - Cloudflare Tunnel or ngrok integration
   - Auto-reconnection handling
   - Offline state preservation

2. **Performance**
   - Image pyramid/tiling for large images
   - CDN caching (if using cloud relay)
   - Virtual scrolling for large galleries

3. **Reliability**
   - Error handling and recovery
   - Progress persistence
   - Crash recovery

### Phase 4 (Optional): Distributed Processing
**Duration: 4-6 weeks**

1. Worker node application
2. Work distribution system
3. Result aggregation
4. Monitoring/management UI

---

## 11. Technology Recommendations

### Backend Stack
| Component | Recommended | Rationale |
|-----------|-------------|-----------|
| Web Framework | FastAPI | Async, fast, Python native, easy integration |
| WebSocket | Socket.IO or FastAPI WebSocket | Real-time updates |
| Database | SQLite (embedded) | Simple, no extra services, sufficient for 10 users |
| Image Processing | Pillow + existing OpenCV | Already in stack |
| Authentication | JWT tokens | Stateless, simple |

### Frontend Stack
| Component | Recommended | Rationale |
|-----------|-------------|-----------|
| Framework | React or Vue 3 | Rich ecosystem, component reuse |
| Image Viewer | OpenSeadragon or custom Canvas | Handles large images, zoom/pan |
| State Management | Zustand (React) or Pinia (Vue) | Simple, lightweight |
| Styling | Tailwind CSS | Rapid development |
| Build Tool | Vite | Fast development, easy bundling |

### Infrastructure
| Component | Recommended | Rationale |
|-----------|-------------|-----------|
| Tunnel Service | Cloudflare Tunnel (free) | Reliable, fast, includes SSL |
| DNS | Cloudflare DNS (free) | Integrates with tunnel |
| Monitoring | Built-in logging | Keep it simple |

---

## 12. Cost Analysis

### Development Costs
| Phase | Effort | Description |
|-------|--------|-------------|
| Phase 1 (MVP) | 6-8 weeks | Core viewer functionality |
| Phase 2 (Multi-user) | 4-6 weeks | Collaboration features |
| Phase 3 (Production) | 3-4 weeks | Reliability and polish |
| **Total** | **13-18 weeks** | Full implementation |

### Ongoing Costs

**Option A: Self-Hosted (Desktop Workstation)**
| Item | Monthly Cost |
|------|-------------|
| Cloudflare Tunnel | Free |
| Dynamic DNS | Free |
| Electricity (workstation) | ~$10-20 |
| **Total** | **~$10-20/month** |

**Option B: Cloud-Hosted**
| Item | Monthly Cost |
|------|-------------|
| VPS (4 CPU, 8GB RAM) | $40-80 |
| Storage (500 GB) | $25-50 |
| Bandwidth (1 TB) | $10-50 |
| **Total** | **$75-180/month** |

---

## 13. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Upload bandwidth insufficient | High | High | Cloud relay, aggressive caching |
| User experience too slow | Medium | High | Progressive loading, feedback |
| Development takes longer | Medium | Medium | Phased approach, MVP first |
| Security vulnerabilities | Low | High | Standard practices, auth |
| Workstation availability | Medium | Medium | Clear user expectations |
| Browser compatibility | Low | Low | Modern browsers only |

---

## 14. Conclusion

### Feasibility Summary

| Criterion | Assessment |
|-----------|------------|
| **Technical Feasibility** | ✅ Yes - Achievable with existing technology |
| **2-5 Concurrent Users** | ✅ Feasible with proper setup |
| **5-10 Concurrent Users** | ⚠️ Challenging - requires good upload bandwidth or cloud relay |
| **User Experience** | ✅ Acceptable with progressive loading |
| **Development Effort** | ⚠️ Significant - 3-5 months for full implementation |
| **Maintenance Burden** | ⚠️ Medium - new components to maintain |

### Key Recommendations

1. **Start with Option A (Embedded Server)** - Lower complexity, faster to implement, suits your 2-10 user requirement

2. **Use Cloudflare Tunnel** - Solves NAT/firewall/SSL issues at no cost

3. **Implement Progressive Loading** - Essential for acceptable latency over WAN

4. **Prioritize Viewer Features** - Get the review workflow working before adding distributed processing

5. **Plan for 50+ Mbps Upload** - Either ensure the server workstation has adequate upload bandwidth, or plan to use cloud relay with caching

### Answer to Original Questions

| Question | Answer |
|----------|--------|
| **How hard to implement?** | Moderate-High complexity, 3-5 months for experienced developer |
| **How viable?** | Viable for 2-10 users with proper infrastructure |
| **How many can connect?** | 2-5 easily, 5-10 with good bandwidth, 10+ needs cloud |
| **Data transfer for 8000×5000 image?** | ~8 MB, taking 0.6-6 seconds depending on connection |
| **Latency for AOI click?** | ~400ms to see preview, ~3s for full resolution |

---

## 15. Incremental Processing and Real-Time Review

### Current Architecture Limitation

The current ADIAT processing pipeline is **strictly batch-oriented**:

```
[Queue ALL Images] → [Process ALL] → [pool.join() BLOCKS] → [Write XML] → [View Results]
```

**Key blocker in AnalyzeService.py (lines 175-176):**
```python
self.pool.close()
self.pool.join()  # Main thread BLOCKS here until ALL workers complete
```

The "View Results" button is only enabled after `sig_done` is emitted, which occurs only after all processing completes. For a 1000-image dataset taking 30 minutes, reviewers must wait the full 30 minutes before seeing anything.

### Proposed: Incremental Processing Model

```
[Process Image 1] → [Results Available] → [Reviewer Starts Working]
[Process Image 2] → [Results Available] → [Reviewer Continues]
[Process Image 3] → [Results Available] → [New Images Appear]
...processing continues in background...
```

**Time to First Review:**
| Dataset Size | Current (Batch) | Incremental |
|--------------|-----------------|-------------|
| 150 images | 5-10 minutes | ~2 seconds |
| 1000 images | 30-60 minutes | ~2 seconds |
| 5000 images | 2-4 hours | ~2 seconds |

### Implementation Requirements

#### Changes to AnalyzeService

| Current Behavior | Required Change |
|------------------|-----------------|
| `pool.join()` blocks until complete | Use callbacks without blocking |
| XML written once at end | Incremental XML updates after each image |
| `sig_done` only signal for completion | Add `sig_image_ready(image_data)` signal |

**Proposed signal additions:**
```python
sig_image_ready = Signal(dict)      # Emitted when single image processed
sig_batch_ready = Signal(int)       # Emitted every N images (for batching)
sig_processing_complete = Signal()  # Final completion (replaces current sig_done)
```

#### Changes to XmlService

| Current Behavior | Required Change |
|------------------|-----------------|
| Build full XML tree in memory | Support incremental appends |
| Single atomic file write | Append-safe file updates or use database |

**Option A: Incremental XML**
```python
def append_image_to_xml(self, image_data):
    """Append single image to existing XML file"""
    # Parse existing, add new image element, save
```

**Option B: SQLite for Real-Time (Recommended for Client-Server)**
```python
def save_image_result(self, image_data):
    """Insert image result to database immediately"""
    # Atomic insert, instantly queryable by viewers
```

#### Changes to Viewer

| Current Behavior | Required Change |
|------------------|-----------------|
| Load all images on startup | Support dynamic loading |
| Static image list | Watch for new images, refresh UI |
| Gallery loads all AOIs upfront | Incremental gallery population |

**New viewer capabilities needed:**
- File watcher or WebSocket listener for new results
- Append new images to thumbnail list without full reload
- Gallery model that handles growing dataset
- "Processing in progress" indicator with live count

### Architecture for Client-Server with Incremental Processing

```
┌─────────────────────────────────────────────────────────────────┐
│                      MAIN COMPUTER                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐    ┌──────────────────┐                   │
│  │ AnalyzeService  │───►│  Results Queue   │                   │
│  │ (Processing)    │    │  (In-Memory)     │                   │
│  └─────────────────┘    └────────┬─────────┘                   │
│                                  │                              │
│                    ┌─────────────┼─────────────┐               │
│                    ▼             ▼             ▼               │
│              ┌──────────┐ ┌──────────┐ ┌──────────────┐        │
│              │ Database │ │   XML    │ │  WebSocket   │        │
│              │ (SQLite) │ │ (Backup) │ │   Server     │        │
│              └──────────┘ └──────────┘ └──────┬───────┘        │
│                    │                          │                 │
└────────────────────┼──────────────────────────┼─────────────────┘
                     │                          │
                     │              ┌───────────┴───────────┐
                     │              │    Push: "New image   │
                     │              │    ready for review"  │
                     │              └───────────┬───────────┘
                     │                          │
        ┌────────────┴────────────┬─────────────┼─────────────┐
        ▼                         ▼             ▼             ▼
   ┌─────────┐              ┌─────────┐   ┌─────────┐   ┌─────────┐
   │  Local  │              │ Browser │   │ Browser │   │ Browser │
   │ Qt GUI  │              │Client 1 │   │Client 2 │   │Client 3 │
   └─────────┘              └─────────┘   └─────────┘   └─────────┘
```

### Batch Assignment with Incremental Processing

This pairs excellently with the batch review system:

```
Processing:     [Image 1] [Image 2] [Image 3] ... [Image 150] [Image 151] ...
                    ↓         ↓         ↓            ↓            ↓
Results DB:     [Ready]   [Ready]   [Ready]  ...  [Ready]     [Ready]   ...

Batch 1 (Images 1-150):     Assigned to Reviewer A
                            ↓
                            Reviewer A can start as soon as Image 1 is ready!
                            New images appear as they're processed.

Batch 2 (Images 151-300):   Assigned to Reviewer B
                            ↓
                            Reviewer B waits for Image 151 to be ready,
                            then can start immediately.
```

### Complexity Assessment

| Component | Effort | Risk |
|-----------|--------|------|
| AnalyzeService refactor | Medium | Low - isolated changes |
| Database layer addition | Medium | Low - standard patterns |
| Viewer dynamic loading | Medium-High | Medium - UI complexity |
| WebSocket push notifications | Low | Low - well-understood |
| Batch assignment system | Medium | Low - new feature |

**Total Additional Effort:** +2-4 weeks beyond base client-server implementation

### Benefits Summary

| Benefit | Impact |
|---------|--------|
| **Immediate productivity** | Reviewers start in seconds, not hours |
| **Better resource utilization** | Review happens in parallel with processing |
| **Improved user experience** | Live progress, no waiting |
| **Natural fit for client-server** | Real-time updates via WebSocket |
| **Enables larger datasets** | No need to split into smaller batches for processing |

### Recommendation

**Strongly recommended for client-server implementation.** The incremental processing model:

1. Dramatically improves user experience
2. Is a natural fit for web-based real-time updates
3. Adds moderate complexity but high value
4. Solves the current pain point of waiting for large datasets

The batch XML write should be retained as a final step for data persistence and export compatibility, but the real-time viewing should use an in-memory queue or database.

---

## Appendix A: Alternative Approaches Considered

### Screen Sharing (Rejected)
- Simple: Use Zoom/TeamViewer to share ADIAT screen
- **Cons:** Only one person can control, no parallel review, doesn't scale

### File Sync (Rejected)
- Sync output folder via Dropbox/Google Drive, run local ADIAT copies
- **Cons:** Large data transfer, version conflicts, no central aggregation

### Remote Desktop (Partially Viable)
- Run multiple ADIAT instances on server, users connect via RDP/VNC
- **Cons:** Heavy server requirements, licensing costs, limited scalability

---

## Appendix B: Relevant Code Locations

For implementation reference:

| Component | Location |
|-----------|----------|
| Viewer Controller | `app/core/controllers/images/viewer/Viewer.py` |
| Gallery Controller | `app/core/controllers/images/viewer/gallery/GalleryController.py` |
| AOI Gallery Model | `app/core/controllers/images/viewer/gallery/AOIGalleryModel.py` |
| Thumbnail Cache | `app/core/services/ThumbnailCacheService.py` |
| Image Service | `app/core/services/ImageService.py` |
| XML Service | `app/core/services/XmlService.py` |
| AOI Service | `app/core/services/AOIService.py` |
| Analysis Service | `app/core/services/AnalyzeService.py` |

---

*Document generated: December 2024*
*ADIAT Version: 2.0.0*
