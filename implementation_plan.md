# Multi-Store Retail Management System — Implementation Plan v2

> Updated based on user feedback. Changes from v1 marked with 🔄.

## Key Decisions (from feedback)

| Decision | Choice |
|---|---|
| 🔄 Database | **PostgreSQL** (via SQLAlchemy) |
| 🔄 Frontend | **React/Vite SPA** (migrate from plain HTML) |
| 🔄 Regions | **2 regions** (North, South) |
| 🔄 Stores | **4 stores per region = 8 stores total** |
| 🔄 Staff | 8 Store Managers + 8 Inventory Managers + 8 Sales Managers + 2 Regional Managers = **26 users** |
| 🔄 Warehouses | **2 warehouses** (one per region) |
| 🔄 Auth | **Simple user ID + password** (no JWT/bcrypt — session-based) |
| 🔄 Products | **Shared 5 products** from existing `ProductCatalog` |
| 🔄 Sales UI | **Manual entry** of sale quantity per product |
| 🔄 Real-time | **WebSocket** instant inventory propagation |
| 🔄 ML | **Integrate existing RL/DQN** models for demand prediction |

---

## Architecture Overview

```mermaid
graph TD
    subgraph "Frontend — React/Vite SPA"
        LP["Login Page"]
        SD["Store Dashboard"]
        IM["Inventory Manager View"]
        SM["Sales Manager View"]
        RD["Regional Dashboard"]
        CS["Create Store Wizard"]
        WD["Warehouse Dashboard"]
    end

    subgraph "Backend — FastAPI"
        AUTH["auth_router"]
        STORE["store_router"]
        SALES["sales_router"]
        REG["regional_router"]
        ADMIN["admin_router"]
        TRANS["transfer_router"]
        WH["warehouse_router"]
        WS["WebSocket Hub"]
    end

    subgraph "Database — PostgreSQL"
        DB[(PostgreSQL)]
    end

    subgraph "Agents"
        SIA["StoreInventoryAgent"]
        SSA["SalesSyncAgent"]
        RAA["RegionalAnalyticsAgent"]
        ISA["InterStoreAgent"]
        WBA["WarehouseBalancerAgent"]
        DQN["DQN Agent (RL)"]
    end

    LP --> AUTH
    SD --> STORE
    IM --> STORE
    SM --> SALES
    RD --> REG
    CS --> ADMIN
    WD --> WH

    AUTH --> DB
    STORE --> DB
    SALES --> DB
    REG --> DB
    ADMIN --> DB
    TRANS --> DB
    WH --> DB

    SALES --> SIA
    SIA --> SSA
    REG --> RAA
    TRANS --> ISA
    WH --> WBA
    WBA --> DQN

    WS --> SD
    WS --> IM
    WS --> SM
```

---

## Phase 0 — Database Foundation & React Setup

### PostgreSQL + SQLAlchemy

#### [NEW] db/__init__.py, db/database.py
- SQLAlchemy engine: `postgresql://user:pass@localhost:5432/smart_mas`
- `SessionLocal` factory, `get_db()` FastAPI dependency
- Connection string from `.env`

#### [NEW] db/models.py

| Model | Key Fields |
|---|---|
| `User` | id, user_id (unique login), password, display_name, role, store_id, region_id, is_active |
| `Region` | id, name (North/South), warehouse_id |
| `Store` | id, name, store_code, region_id |
| `Product` | id, sku, name, category, unit_price, base_demand — *seeded from existing 5 products* |
| `StoreInventory` | id, store_id, product_id, quantity, last_updated |
| `Sale` | id, store_id, product_id, quantity, sale_price, sold_by, sold_at |
| `TransferRequest` | id, from_store_id, to_store_id, product_id, quantity, status, requested_by |
| `Warehouse` | id, name, region_id, capacity, current_stock |
| `WarehouseTransfer` | id, from_warehouse_id, to_warehouse_id, units, reason, status |
| `StockAlert` | id, store_id, product_id, alert_type, threshold, current_level |

#### [NEW] db/seed.py
Seeds the database with:
- 2 Regions: North, South
- 2 Warehouses: Warehouse-North, Warehouse-South
- 8 Stores: Store-N1..N4 (North), Store-S1..S4 (South)
- 5 Products (from `ProductCatalog.DEFAULT_PRODUCTS`)
- 40 StoreInventory rows (8 stores × 5 products, 100 units each)
- 26 Users with simple credentials:

| User ID Pattern | Role | Count |
|---|---|---|
| `sm_n1` … `sm_s4` | store_manager | 8 |
| `im_n1` … `im_s4` | inventory_manager | 8 |
| `slm_n1` … `slm_s4` | sales_manager | 8 |
| `rm_north`, `rm_south` | regional_manager | 2 |

Default password: `password123` (plain text comparison per user request)

### React/Vite SPA Setup

#### [NEW] frontend-app/ — Vite + React project

```
frontend-app/
├── src/
│   ├── main.jsx
│   ├── App.jsx                 # Router + auth context
│   ├── api/                    # Axios API client
│   │   └── client.js
│   ├── context/
│   │   └── AuthContext.jsx     # Login state, user role, session
│   ├── pages/
│   │   ├── LoginPage.jsx
│   │   ├── StoreDashboard.jsx       # Store Manager
│   │   ├── InventoryManager.jsx     # Inventory Manager
│   │   ├── SalesManager.jsx         # Sales Manager
│   │   ├── RegionalDashboard.jsx    # Regional Manager
│   │   ├── CreateStore.jsx          # Store creation wizard
│   │   └── WarehouseDashboard.jsx   # Warehouse overview
│   ├── components/
│   │   ├── Navbar.jsx
│   │   ├── ProtectedRoute.jsx  # Role-based route guard
│   │   ├── AlertPanel.jsx
│   │   ├── InventoryTable.jsx
│   │   ├── SalesForm.jsx       # Manual qty entry per product
│   │   ├── StoreCard.jsx
│   │   └── TransferModal.jsx
│   └── hooks/
│       └── useWebSocket.js     # Real-time inventory updates
├── index.html
├── vite.config.js
└── package.json
```

#### [MODIFY] api/app.py
- Mount React build as static files (`/assets/*`)
- Serve `index.html` for all non-API routes (SPA fallback)
- Keep existing API routes intact (backward compatible)

#### [MODIFY] requirements.txt
Add: `SQLAlchemy>=2.0`, `psycopg2-binary>=2.9`, `python-dotenv>=1.0`

---

## Phase 1 — Simple Authentication

🔄 Simple user ID + password — no encryption, session-based.

#### [NEW] api/auth_router.py
- `POST /api/auth/login` — body: `{user_id, password}` → returns user profile + session token (simple UUID)
- `GET /api/auth/me` — returns current user from session token (passed as `Authorization: Bearer <token>`)
- `POST /api/auth/logout` — invalidates session
- In-memory session store: `{token: user_id}` dict (simple, no Redis needed)

#### [NEW] auth/dependencies.py
- `get_current_user(request)` — FastAPI dependency, reads token from header, looks up user
- `require_role(*roles)` — checks user role
- `require_store(store_id)` — ensures user belongs to store
- `require_region(region_id)` — ensures user is regional manager for region

#### Role → Page Routing

| Role | Default Page After Login |
|---|---|
| `store_manager` | `/store-dashboard` |
| `inventory_manager` | `/inventory` |
| `sales_manager` | `/sales` |
| `regional_manager` | `/regional` |

React's `ProtectedRoute` component checks role and redirects unauthorized users.

---

## Phase 2 — Local Store Structure (4 stores per region)

#### [NEW] api/store_router.py
- `GET /api/stores` — list stores (filtered by user's region/role)
- `GET /api/stores/{store_id}` — store detail + inventory summary
- `GET /api/stores/{store_id}/inventory` — full inventory
- `PUT /api/stores/{store_id}/inventory/{product_id}` — update stock (Inventory Manager)
- `GET /api/stores/{store_id}/alerts` — low stock / high demand alerts
- `GET /api/stores/{store_id}/staff` — staff list (Store Manager only)

#### [NEW] api/sales_router.py
- `POST /api/stores/{store_id}/sales` — record a sale (manual qty entry)
  - Auto-decrements `StoreInventory.quantity`
  - Triggers `StockAlert` if below threshold
  - Broadcasts inventory change via **WebSocket**
- `GET /api/stores/{store_id}/sales` — sales history with date filter
- `GET /api/stores/{store_id}/sales/summary` — daily/weekly/monthly aggregates

#### [NEW] api/websocket_hub.py
- `WebSocket /ws/inventory` — broadcasts real-time inventory changes to all connected managers
- On any inventory change (sale, restock, transfer): push `{store_id, product_id, new_qty, change_type}`
- React `useWebSocket` hook auto-reconnects and updates UI state

#### [NEW] agents/store_inventory_agent.py
- Monitor stock levels per store
- Trigger `LOW_STOCK_ALERT` when below reorder point (3× base_demand)
- Trigger `HIGH_DEMAND_ALERT` when sales velocity exceeds supply rate

#### [NEW] agents/sales_sync_agent.py
- On sale recorded → verify inventory decremented correctly
- Aggregate daily sales velocity for demand forecasting input

#### [MODIFY] communication/message_bus.py
Add message types: `SALE_RECORDED`, `STOCK_ALERT`, `RESTOCK_REQUEST`, `STORE_CREATED`, `TRANSFER_REQUEST`, `TRANSFER_APPROVED`

---

## Phase 3 — Regional Manager System

#### [NEW] api/regional_router.py
- `GET /api/regions/{region_id}/overview` — total sales, inventory, store count KPIs
- `GET /api/regions/{region_id}/stores` — all stores with performance scores
- `GET /api/regions/{region_id}/sales/by-store` — store-wise sales comparison
- `GET /api/regions/{region_id}/products/top` — highest-demand products
- `GET /api/regions/{region_id}/stores/underperforming` — below-average stores

#### [NEW] agents/regional_analytics_agent.py
- Aggregate sales across 4 stores in a region
- Identify high-demand products (top 20% by volume)
- Flag underperforming stores (below regional average by >15%)
- Compute profit margins per store

#### React: RegionalDashboard.jsx
- Region summary hero cards (total revenue, units, store count, avg fill rate)
- Store-wise performance bar chart
- Top products heatmap
- Underperforming stores alert table

---

## Phase 4 — Store Creation System

#### [NEW] api/admin_router.py
- `POST /api/stores/create` — (Regional Manager only)
  - Input: `{name, region_id}`
  - Auto-generates: store_code, 3 user accounts (SM, IM, SLM)
  - Seeds inventory from regional average
  - Links to regional warehouse + nearby stores
  - Returns all credentials

#### React: CreateStore.jsx
- Step 1: Enter store name + select region
- Step 2: Preview auto-generated credentials
- Step 3: Confirm → success with printable credential card

---

## Phase 5 — Inter-Store Connectivity

#### [NEW] api/transfer_router.py
- `GET /api/stores/{store_id}/nearby` — nearby stores (same region) with inventory
- `GET /api/stores/{store_id}/product-availability/{product_id}` — check availability across region
  - Returns: `"Product available at Store-N2 — 45 units in stock"`
- `POST /api/transfers/request` — create transfer request
- `PUT /api/transfers/{id}/approve` — approve (Store Manager / Regional Manager)
- `PUT /api/transfers/{id}/complete` — mark completed, update both inventories

#### [NEW] agents/inter_store_agent.py
- When product goes OOS at a store → query all stores in region → suggest source
- Auto-create transfer request when stock critically low

---

## Phase 6 — Warehouse Interconnection + RL/DQN Demand Prediction

#### [NEW] api/warehouse_router.py
- `GET /api/warehouses` — all warehouses with stock levels
- `GET /api/warehouses/imbalance` — cross-region stock imbalance detection
- `POST /api/warehouses/transfer` — trigger cross-region transfer
- `GET /api/warehouses/demand-prediction` — RL/DQN-powered demand forecast

#### [NEW] agents/warehouse_balancer_agent.py
- Monitor demand per region from aggregated sales data
- Detect imbalance (Region North high demand + Region South surplus)
- **🔄 RL/DQN integration:**
  - Use existing `rl/dqn_agent.py` `DQNAgent` for demand prediction
  - Feed regional sales history as state vector to trained model
  - Model outputs recommended production/transfer quantities
  - Falls back to rule-based (moving average + threshold) if model unavailable
- Stock thresholds: CRITICAL=10%, LOW=25%, SURPLUS=75% of capacity
- Auto-suggest transfers when imbalance detected

#### [MODIFY] warehouse/warehouse_network.py
- Add `region_id` to `WarehouseNode`
- Add `cross_region_transfer()` and `imbalance_report()` methods

#### [MODIFY] automations/warehouse_logger.py
- Add `log_cross_region_transfer()` with `transfer_type` column

---

## File Summary

| Phase | New Files | Modified Files |
|---|---|---|
| 0 | `db/` (4 files), `frontend-app/` (full React project) | `api/app.py`, `requirements.txt` |
| 1 | `api/auth_router.py`, `auth/dependencies.py` | `api/app.py` |
| 2 | `api/store_router.py`, `api/sales_router.py`, `api/websocket_hub.py`, 2 agents | `communication/message_bus.py` |
| 3 | `api/regional_router.py`, 1 agent | — |
| 4 | `api/admin_router.py` | — |
| 5 | `api/transfer_router.py`, 1 agent | — |
| 6 | `api/warehouse_router.py`, 1 agent | `warehouse/warehouse_network.py`, `automations/warehouse_logger.py` |

**Total: ~30 new files + React SPA project, ~6 modified files**

---

## Verification Plan

### Automated Tests
```bash
# DB & Seed
python -c "from db.seed import seed_all; seed_all(); print('OK')"

# Auth
curl -X POST localhost:8000/api/auth/login -d '{"user_id":"sm_n1","password":"password123"}'

# Store + Sales
python -m pytest tests/test_store_operations.py tests/test_sales.py -v

# Regional + Transfers + Warehouse
python -m pytest tests/test_regional.py tests/test_transfers.py tests/test_warehouse_balancer.py -v
```

### Manual Verification
1. Login as each role → verify correct dashboard redirect
2. Sales Manager: record sale → verify WebSocket pushes inventory update to Store Manager
3. Inventory Manager: view nearby stores → request transfer → Store Manager approves
4. Regional Manager: view all 4 stores → create new store → verify credentials
5. Warehouse: simulate demand imbalance → verify RL/DQN prediction → trigger transfer
