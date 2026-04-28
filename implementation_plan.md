# Store-Specific Sales and Logging Implementation Plan

This plan focuses on fulfilling the new requirements for the Supply Chain MAS project. The previous phases (0-6) are already completed in the codebase. 

The goal of this phase is to:
1. Restrict shop catalogue access to salespersons only.
2. Remove manual store selection from the shop.
3. Establish a default inventory of 100 units across all stores.
4. Implement store-specific CSV logging for sales and inventory changes when orders are placed.

## Proposed Changes

---

### Database Initialization

#### [MODIFY] db/seed.py
- Update the `seed_all()` function to initialize the `quantity` of `StoreInventory` to exactly 100.0 units for every product across all stores, removing the random variation logic.

---

### Frontend Routing and Access Control

#### [MODIFY] frontend-app/src/App.jsx
- Wrap the `<Route path="/shop" ... />` in a `<ProtectedRoute allowedRoles={['sales_person']}>` to prevent unauthorized direct URL access.

#### [MODIFY] frontend-app/src/components/Navbar.jsx
- Conditionally render the "Shop" and "MAS Ops" navigation links.
- These links will only be added to `navItems` if `user.role === 'sales_person'`. Store managers and regional managers will no longer see them.

---

### Shop UI Updates

#### [MODIFY] frontend-app/src/pages/ShopPage.jsx
- Import and use the `useAuth` hook to retrieve the current logged-in user.
- Set the `selectedStoreId` automatically using `user.store_id`.
- Remove the "Order from Store" manual selection UI (buttons for KOL 1, KOL 2, etc.).

---

### Store Logging (Sales & Inventory)

#### [NEW] automations/store_logger.py
- Create a new utility to handle store-specific CSV logging.
- `log_store_sale(store_id, store_code, product_name, sku, qty, price, order_id)`: Appends a record to `store_{store_code}_sales_log.csv`.
- `log_store_inventory(store_id, store_code, product_name, sku, remaining_qty)`: Appends a record to `store_{store_code}_inventory_log.csv` indicating the new stock level.

#### [MODIFY] agents/inventory_simulator.py
- Import the new logging functions from `automations/store_logger.py`.
- Inside `process_order_deduction()`, after updating the database and generating alerts, call the logging functions to record the sale and the new inventory level.
- (Note: Real-time deduction on the Store Manager's dashboard is already handled by the existing WebSocket broadcast in `process_order_deduction()`).

## Verification Plan

### Automated Tests
- Check if `db/seed.py` creates exactly 100 units of each item: `sqlite3 smart_mas.db "SELECT quantity FROM storeinventory LIMIT 10;"`

### Manual Verification
1. Login as `sm_kol1` (Store Manager) -> Verify "Shop" and "MAS Ops" are hidden in Navbar.
2. Login as `sp_kol1` (Sales Person) -> Verify "Shop" and "MAS Ops" are visible.
3. Open Shop as `sp_kol1` -> Verify manual store selection is gone.
4. Place an order in the Shop -> Verify `store_KOL1_sales_log.csv` and `store_KOL1_inventory_log.csv` are created and contain the correct items.
5. Open another browser tab as `sm_kol1` -> Verify the Store Manager dashboard updates the inventory in real-time as soon as the salesperson places the order.
