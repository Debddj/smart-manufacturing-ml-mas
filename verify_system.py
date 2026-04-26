"""
Comprehensive system verification script for Smart Manufacturing MAS.
Tests all API endpoints, auth flows, and role-based access control.
"""
import requests
import json
import sys

BASE = "http://localhost:8000"
results = []


def test(name, fn):
    try:
        result = fn()
        results.append((name, "PASS", result))
        print(f"  [PASS] {name}: {result}")
    except Exception as e:
        results.append((name, "FAIL", str(e)))
        print(f"  [FAIL] {name}: {e}")


print("=" * 70)
print("API ENDPOINT VERIFICATION")
print("=" * 70)

# ── 1. AUTH ─────────────────────────────────────────────────────────────────

print("\n[1] AUTH ENDPOINTS")
print("-" * 40)


def login_sm():
    r = requests.post(f"{BASE}/api/auth/login", json={"user_id": "sm_kol1", "password": "password123"})
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    data = r.json()
    assert "token" in data, "No token in response"
    assert data["user"]["role"] == "store_manager"
    tok = data["token"][:8]
    return f"token={tok}... role={data['user']['role']}"


test("Login Store Manager (sm_kol1)", login_sm)


def login_sp():
    r = requests.post(f"{BASE}/api/auth/login", json={"user_id": "sp_kol1", "password": "password123"})
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    return f"role={r.json()['user']['role']}"


test("Login Sales Person (sp_kol1)", login_sp)


def login_rm():
    r = requests.post(f"{BASE}/api/auth/login", json={"user_id": "rm_kolkata", "password": "password123"})
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    return f"role={r.json()['user']['role']}"


test("Login Regional Manager (rm_kolkata)", login_rm)


def login_bad():
    r = requests.post(f"{BASE}/api/auth/login", json={"user_id": "sm_kol1", "password": "wrong"})
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    return "Correctly rejected"


test("Login bad password", login_bad)

# Get tokens
sm_data = requests.post(f"{BASE}/api/auth/login", json={"user_id": "sm_kol1", "password": "password123"}).json()
sp_data = requests.post(f"{BASE}/api/auth/login", json={"user_id": "sp_kol1", "password": "password123"}).json()
rm_data = requests.post(f"{BASE}/api/auth/login", json={"user_id": "rm_kolkata", "password": "password123"}).json()

sm_token = sm_data["token"]
sp_token = sp_data["token"]
rm_token = rm_data["token"]
sm_user = sm_data["user"]
rm_user = rm_data["user"]

headers_sm = {"Authorization": f"Bearer {sm_token}"}
headers_sp = {"Authorization": f"Bearer {sp_token}"}
headers_rm = {"Authorization": f"Bearer {rm_token}"}


def test_me():
    r = requests.get(f"{BASE}/api/auth/me", headers=headers_sm)
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert data["user_id"] == "sm_kol1"
    return f"user_id={data['user_id']}"


test("GET /api/auth/me", test_me)


def test_no_auth():
    r = requests.get(f"{BASE}/api/auth/me")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    return "Correctly denied"


test("GET /api/auth/me (no token)", test_no_auth)

# ── 2. STORES ───────────────────────────────────────────────────────────────

print("\n[2] STORE ENDPOINTS")
print("-" * 40)


def test_list_stores_sm():
    r = requests.get(f"{BASE}/api/stores", headers=headers_sm)
    assert r.status_code == 200
    stores = r.json()
    assert len(stores) == 1, f"Store manager should see 1 store, got {len(stores)}"
    return f"{len(stores)} store(s): {stores[0]['name']}"


test("GET /api/stores (store_manager)", test_list_stores_sm)


def test_list_stores_rm():
    r = requests.get(f"{BASE}/api/stores", headers=headers_rm)
    assert r.status_code == 200
    stores = r.json()
    assert len(stores) == 4, f"Regional manager should see 4 stores, got {len(stores)}"
    return f"{len(stores)} stores"


test("GET /api/stores (regional_manager)", test_list_stores_rm)


def test_get_store():
    store_id = sm_user["store_id"]
    r = requests.get(f"{BASE}/api/stores/{store_id}", headers=headers_sm)
    assert r.status_code == 200
    data = r.json()
    assert "inventory" in data
    return f"store={data['name']}, inventory_items={len(data['inventory'])}"


test("GET /api/stores/{id}", test_get_store)


def test_get_inventory():
    store_id = sm_user["store_id"]
    r = requests.get(f"{BASE}/api/stores/{store_id}/inventory", headers=headers_sm)
    assert r.status_code == 200
    inv = r.json()
    assert len(inv) == 5, f"Expected 5 products, got {len(inv)}"
    total = sum(i["quantity"] for i in inv)
    return f"{len(inv)} products, total={total} units"


test("GET /api/stores/{id}/inventory", test_get_inventory)


def test_get_alerts():
    store_id = sm_user["store_id"]
    r = requests.get(f"{BASE}/api/stores/{store_id}/alerts", headers=headers_sm)
    assert r.status_code == 200
    return f"{len(r.json())} alerts"


test("GET /api/stores/{id}/alerts", test_get_alerts)


def test_get_staff():
    store_id = sm_user["store_id"]
    r = requests.get(f"{BASE}/api/stores/{store_id}/staff", headers=headers_sm)
    assert r.status_code == 200
    staff = r.json()
    assert len(staff) >= 2
    return f"{len(staff)} staff members"


test("GET /api/stores/{id}/staff", test_get_staff)


def test_store_access_denied():
    r = requests.get(f"{BASE}/api/stores/99", headers=headers_sm)
    assert r.status_code in (403, 404), f"Expected 403/404, got {r.status_code}"
    return f"Correctly denied (status={r.status_code})"


test("Store access denied for wrong store", test_store_access_denied)

# ── 3. SALES ────────────────────────────────────────────────────────────────

print("\n[3] SALES ENDPOINTS")
print("-" * 40)


def test_record_sale():
    store_id = sm_user["store_id"]
    inv = requests.get(f"{BASE}/api/stores/{store_id}/inventory", headers=headers_sp).json()
    product_id = inv[0]["product_id"]
    old_qty = inv[0]["quantity"]
    r = requests.post(
        f"{BASE}/api/stores/{store_id}/sales",
        headers=headers_sp,
        json={"product_id": product_id, "quantity": 5.0},
    )
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    data = r.json()
    assert data["remaining_stock"] == old_qty - 5.0
    return f"sale_id={data['sale_id']}, remaining={data['remaining_stock']}"


test("POST /api/stores/{id}/sales", test_record_sale)


def test_record_sale_insufficient():
    store_id = sm_user["store_id"]
    inv = requests.get(f"{BASE}/api/stores/{store_id}/inventory", headers=headers_sp).json()
    product_id = inv[0]["product_id"]
    r = requests.post(
        f"{BASE}/api/stores/{store_id}/sales",
        headers=headers_sp,
        json={"product_id": product_id, "quantity": 99999},
    )
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"
    return "Correctly rejected insufficient stock"


test("POST /api/stores/{id}/sales (insufficient)", test_record_sale_insufficient)


def test_get_sales():
    store_id = sm_user["store_id"]
    r = requests.get(f"{BASE}/api/stores/{store_id}/sales", headers=headers_sp)
    assert r.status_code == 200
    sales = r.json()
    assert len(sales) >= 1
    return f"{len(sales)} sale(s)"


test("GET /api/stores/{id}/sales", test_get_sales)


def test_sales_summary():
    store_id = sm_user["store_id"]
    r = requests.get(f"{BASE}/api/stores/{store_id}/sales/summary", headers=headers_sp)
    assert r.status_code == 200
    data = r.json()
    return f"total_sales={data['total_sales']}, revenue={data['total_revenue']}"


test("GET /api/stores/{id}/sales/summary", test_sales_summary)

# ── 4. REGIONAL ─────────────────────────────────────────────────────────────

print("\n[4] REGIONAL ENDPOINTS")
print("-" * 40)


def test_region_overview():
    region_id = rm_user["region_id"]
    r = requests.get(f"{BASE}/api/regions/{region_id}/overview", headers=headers_rm)
    assert r.status_code == 200
    data = r.json()
    assert data["store_count"] == 4
    return f"region={data['region_name']}, stores={data['store_count']}, inv={data['total_inventory']}"


test("GET /api/regions/{id}/overview", test_region_overview)


def test_region_stores():
    region_id = rm_user["region_id"]
    r = requests.get(f"{BASE}/api/regions/{region_id}/stores", headers=headers_rm)
    assert r.status_code == 200
    stores = r.json()
    assert len(stores) == 4
    return f"{len(stores)} stores with performance data"


test("GET /api/regions/{id}/stores", test_region_stores)


def test_region_sales_by_store():
    region_id = rm_user["region_id"]
    r = requests.get(f"{BASE}/api/regions/{region_id}/sales/by-store", headers=headers_rm)
    assert r.status_code == 200
    return f"{len(r.json())} stores with sales"


test("GET /api/regions/{id}/sales/by-store", test_region_sales_by_store)


def test_top_products():
    region_id = rm_user["region_id"]
    r = requests.get(f"{BASE}/api/regions/{region_id}/products/top", headers=headers_rm)
    assert r.status_code == 200
    return f"{len(r.json())} top products"


test("GET /api/regions/{id}/products/top", test_top_products)


def test_underperforming():
    region_id = rm_user["region_id"]
    r = requests.get(f"{BASE}/api/regions/{region_id}/stores/underperforming", headers=headers_rm)
    assert r.status_code == 200
    return f"{len(r.json())} underperforming stores"


test("GET /api/regions/{id}/stores/underperforming", test_underperforming)


def test_region_access_denied():
    region_id = rm_user["region_id"]
    r = requests.get(f"{BASE}/api/regions/{region_id}/overview", headers=headers_sm)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"
    return "Store manager correctly denied"


test("Regional endpoint role check", test_region_access_denied)

# ── 5. TRANSFERS ────────────────────────────────────────────────────────────

print("\n[5] TRANSFER ENDPOINTS")
print("-" * 40)


def test_nearby():
    store_id = sm_user["store_id"]
    r = requests.get(f"{BASE}/api/stores/{store_id}/nearby", headers=headers_sm)
    assert r.status_code == 200
    nearby = r.json()
    assert len(nearby) == 3, f"Expected 3 nearby stores, got {len(nearby)}"
    return f"{len(nearby)} nearby stores"


test("GET /api/stores/{id}/nearby", test_nearby)


def test_product_availability():
    store_id = sm_user["store_id"]
    inv = requests.get(f"{BASE}/api/stores/{store_id}/inventory", headers=headers_sm).json()
    product_id = inv[0]["product_id"]
    r = requests.get(f"{BASE}/api/stores/{store_id}/product-availability/{product_id}", headers=headers_sm)
    assert r.status_code == 200
    data = r.json()
    return f"{data['product_name']}: {data['total_available']} units at {len(data['available_at'])} stores"


test("GET /api/stores/{id}/product-availability/{pid}", test_product_availability)


def test_transfer_request():
    store_id = sm_user["store_id"]
    nearby = requests.get(f"{BASE}/api/stores/{store_id}/nearby", headers=headers_sm).json()
    inv = requests.get(f"{BASE}/api/stores/{store_id}/inventory", headers=headers_sm).json()
    r = requests.post(
        f"{BASE}/api/transfers/request",
        headers=headers_sm,
        json={
            "from_store_id": nearby[0]["id"],
            "to_store_id": store_id,
            "product_id": inv[0]["product_id"],
            "quantity": 10.0,
        },
    )
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    data = r.json()
    return f"transfer_id={data['id']}, status={data['status']}"


test("POST /api/transfers/request", test_transfer_request)


def test_list_transfers():
    r = requests.get(f"{BASE}/api/transfers", headers=headers_sm)
    assert r.status_code == 200
    return f"{len(r.json())} transfers"


test("GET /api/transfers", test_list_transfers)


def test_approve_transfer():
    r = requests.get(f"{BASE}/api/transfers", headers=headers_sm)
    transfers = r.json()
    pending = [t for t in transfers if t["status"] == "pending"]
    if not pending:
        return "No pending transfers to approve"
    tid = pending[0]["id"]
    # Approve as SM of from_store
    from_store_id = pending[0]["from_store_id"]
    # Get a token for the from-store manager
    import sys; sys.path.insert(0, ".")
    from db.database import SessionLocal
    from db.models import User
    db = SessionLocal()
    from_sm = db.query(User).filter(User.store_id == from_store_id, User.role == "store_manager").first()
    db.close()
    if from_sm:
        login_r = requests.post(f"{BASE}/api/auth/login", json={"user_id": from_sm.user_id, "password": "password123"})
        from_headers = {"Authorization": f"Bearer {login_r.json()['token']}"}
        r = requests.put(f"{BASE}/api/transfers/{tid}/approve", headers=from_headers)
        assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
        return f"Transfer {tid} approved"
    return "Could not find from-store manager"


test("PUT /api/transfers/{id}/approve", test_approve_transfer)

# ── 6. WAREHOUSES ───────────────────────────────────────────────────────────

print("\n[6] WAREHOUSE ENDPOINTS")
print("-" * 40)


def test_list_warehouses():
    r = requests.get(f"{BASE}/api/warehouses", headers=headers_rm)
    assert r.status_code == 200
    whs = r.json()
    assert len(whs) == 2
    names = [w["name"] for w in whs]
    return f"{len(whs)} warehouses: {names}"


test("GET /api/warehouses", test_list_warehouses)


def test_imbalance():
    r = requests.get(f"{BASE}/api/warehouses/imbalance", headers=headers_rm)
    assert r.status_code == 200
    data = r.json()
    return f"imbalance={data['imbalance_detected']}, avg_util={data.get('average_utilization')}%"


test("GET /api/warehouses/imbalance", test_imbalance)


def test_warehouse_transfers():
    r = requests.get(f"{BASE}/api/warehouses/transfers", headers=headers_rm)
    assert r.status_code == 200
    return f"{len(r.json())} warehouse transfers"


test("GET /api/warehouses/transfers", test_warehouse_transfers)


def test_warehouse_detail():
    whs = requests.get(f"{BASE}/api/warehouses", headers=headers_rm).json()
    wh_id = whs[0]["id"]
    r = requests.get(f"{BASE}/api/warehouses/{wh_id}", headers=headers_rm)
    assert r.status_code == 200
    data = r.json()
    return f"name={data['name']}, stock={data['current_stock']}, stores={len(data['stores_served'])}"


test("GET /api/warehouses/{id}", test_warehouse_detail)

# ── 7. ADMIN ────────────────────────────────────────────────────────────────

print("\n[7] ADMIN ENDPOINTS")
print("-" * 40)


def test_create_store():
    region_id = rm_user["region_id"]
    r = requests.post(
        f"{BASE}/api/admin/stores/create",
        headers=headers_rm,
        json={"name": "Verification Test Store", "region_id": region_id},
    )
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    data = r.json()
    return f"store={data['store']['store_code']}, creds={len(data['credentials'])} users"


test("POST /api/admin/stores/create", test_create_store)


def test_create_store_wrong_region():
    # Try creating in wrong region
    r = requests.post(
        f"{BASE}/api/admin/stores/create",
        headers=headers_rm,
        json={"name": "Wrong Region Store", "region_id": 999},
    )
    assert r.status_code in (403, 404), f"Expected 403/404, got {r.status_code}"
    return "Correctly denied"


test("POST /api/admin/stores/create (wrong region)", test_create_store_wrong_region)

# ── 8. LEGACY / SHOP ───────────────────────────────────────────────────────

print("\n[8] LEGACY / SHOP ENDPOINTS")
print("-" * 40)


def test_products():
    r = requests.get(f"{BASE}/api/products")
    assert r.status_code == 200
    prods = r.json()
    assert len(prods) == 5
    return f"{len(prods)} products"


test("GET /api/products", test_products)


def test_shop_page():
    r = requests.get(f"{BASE}/")
    assert r.status_code == 200
    assert "html" in r.text.lower()
    return f"HTML page ({len(r.text)} bytes)"


test("GET / (shop.html)", test_shop_page)


def test_dashboard_page():
    r = requests.get(f"{BASE}/dashboard")
    assert r.status_code == 200
    return f"HTML page ({len(r.text)} bytes)"


test("GET /dashboard (mas-ops.html)", test_dashboard_page)


def test_demand_page():
    r = requests.get(f"{BASE}/demand")
    assert r.status_code == 200
    return f"HTML page ({len(r.text)} bytes)"


test("GET /demand (demand_forecast.html)", test_demand_page)


def test_demand_api():
    r = requests.get(f"{BASE}/api/demand/prediction")
    assert r.status_code == 200
    return f"Prediction data: {type(r.json()).__name__}"


test("GET /api/demand/prediction", test_demand_api)


def test_agents_api():
    r = requests.get(f"{BASE}/api/agents")
    assert r.status_code == 200
    agents = r.json()
    return f"{len(agents)} agents tracked"


test("GET /api/agents", test_agents_api)

# ── SUMMARY ─────────────────────────────────────────────────────────────────

print()
print("=" * 70)
total = len(results)
passed = sum(1 for _, s, _ in results if s == "PASS")
failed = sum(1 for _, s, _ in results if s == "FAIL")
print(f"RESULTS: {passed}/{total} PASSED, {failed} FAILED")
if failed > 0:
    print()
    print("FAILURES:")
    for name, status, detail in results:
        if status == "FAIL":
            print(f"  X {name}: {detail}")
print("=" * 70)
