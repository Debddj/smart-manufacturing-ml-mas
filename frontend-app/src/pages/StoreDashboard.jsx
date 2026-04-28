import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import useWebSocket from '../hooks/useWebSocket';
import api from '../api/client';
import './Dashboard.css';

export default function StoreDashboard() {
  const { user } = useAuth();
  const [store, setStore]         = useState(null);
  const [inventory, setInventory] = useState([]);
  const [sales, setSales]         = useState(null);
  const [alerts, setAlerts]       = useState([]);
  const [staff, setStaff]         = useState([]);
  const [loading, setLoading]     = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [statsFlash, setStatsFlash]   = useState(false);

  const { lastMessage, isConnected } = useWebSocket(user?.store_id);

  // ── Lightweight stats refresh (sales + alerts + inventory) ───────────────
  // Called every 30s and on every WebSocket event — does NOT show the full-
  // page loading spinner so the UI stays interactive.
  const refreshStats = useCallback(async () => {
    if (!user?.store_id) return;
    try {
      const [invRes, salesRes, alertRes] = await Promise.all([
        api.get(`/api/stores/${user.store_id}/inventory`),
        api.get(`/api/stores/${user.store_id}/sales/summary?days=7`),
        api.get(`/api/stores/${user.store_id}/alerts?resolved=false`),
      ]);
      setInventory(invRes.data);
      setSales(salesRes.data);
      setAlerts(alertRes.data);
      setLastUpdated(new Date());
      // Flash the stat cards briefly to signal a live update
      setStatsFlash(true);
      setTimeout(() => setStatsFlash(false), 1200);
    } catch (err) {
      console.error('Stats refresh failed:', err);
    }
  }, [user?.store_id]);

  // ── Full initial load (runs once when user is available) ─────────────────
  useEffect(() => {
    if (!user?.store_id) return;

    const loadAll = async () => {
      setLoading(true);
      try {
        const [storeRes, invRes, salesRes, alertRes, staffRes] = await Promise.all([
          api.get(`/api/stores/${user.store_id}`),
          api.get(`/api/stores/${user.store_id}/inventory`),
          api.get(`/api/stores/${user.store_id}/sales/summary?days=7`),
          api.get(`/api/stores/${user.store_id}/alerts?resolved=false`),
          api.get(`/api/stores/${user.store_id}/staff`),
        ]);
        setStore(storeRes.data);
        setInventory(invRes.data);
        setSales(salesRes.data);
        setAlerts(alertRes.data);
        setStaff(staffRes.data);
        setLastUpdated(new Date());
      } catch (err) {
        console.error('Failed to load store data:', err);
      } finally {
        setLoading(false);
      }
    };

    loadAll();
  }, [user?.store_id]);

  // ── 30-second polling for stats ───────────────────────────────────────────
  useEffect(() => {
    if (!user?.store_id) return;
    const interval = setInterval(refreshStats, 30_000);
    return () => clearInterval(interval);
  }, [refreshStats, user?.store_id]);

  // ── WebSocket: update inventory row + refresh stats immediately ───────────
  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type === 'inventory_update' && lastMessage.store_id === user?.store_id) {
      // Optimistic update on the specific inventory row
      setInventory(prev => prev.map(inv =>
        inv.product_id === lastMessage.product_id
          ? { ...inv, quantity: lastMessage.new_quantity }
          : inv
      ));
      // Always pull fresh sales + alert counts after any inventory change
      refreshStats();
    }
  }, [lastMessage, user?.store_id, refreshStats]);

  // ── Derived values ────────────────────────────────────────────────────────
  if (loading) return <div className="dash-loading">Loading dashboard…</div>;

  const totalStock    = inventory.reduce((s, i) => s + i.quantity, 0);
  const lowStockItems = inventory.filter(i => i.quantity < 20);

  const fmtNum = (n) => n == null ? '0' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  const fmtRupee = (n) => n == null ? '₹0' : '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });

  return (
    <div className="dashboard">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="dash-header">
        <div>
          <h1>{store?.name || 'Store Dashboard'}</h1>
          <p className="dash-subtitle">Code: {store?.store_code} | Real-time inventory management</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          {/* Last-updated timestamp */}
          {lastUpdated && (
            <span style={{ fontSize: '.68rem', color: '#8B6045', fontFamily: 'Inter, sans-serif' }}>
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          {/* Manual refresh */}
          <button
            onClick={refreshStats}
            title="Refresh stats"
            style={{
              padding: '.3rem .65rem', borderRadius: 7, fontSize: '.72rem', fontWeight: 600,
              border: '1px solid #D4B896', background: '#F5EDE0', color: '#8B4513',
              cursor: 'pointer', fontFamily: 'inherit',
            }}
          >
            ↻ Refresh
          </button>
          {/* Live / Offline indicator */}
          <div className="ws-indicator">
            <span
              className={`ws-dot ${isConnected ? 'connected' : ''}`}
              style={statsFlash ? { boxShadow: '0 0 0 4px rgba(34,197,94,.35)' } : {}}
            />
            {isConnected ? 'Live' : 'Offline'}
          </div>
        </div>
      </div>

      {/* ── KPI stat cards ─────────────────────────────────────────── */}
      <div className="stat-cards">
        <div className={`stat-card purple${statsFlash ? ' stat-flash' : ''}`}>
          <div className="stat-label">Total Stock</div>
          <div className="stat-value">{fmtNum(totalStock)}</div>
          <div className="stat-detail">{inventory.length} products</div>
        </div>

        <div className={`stat-card blue${statsFlash ? ' stat-flash' : ''}`}>
          <div className="stat-label">Weekly Sales</div>
          <div className="stat-value">{fmtNum(sales?.total_units)}</div>
          <div className="stat-detail">{fmtNum(sales?.total_sales)} transactions</div>
        </div>

        <div className={`stat-card green${statsFlash ? ' stat-flash' : ''}`}>
          <div className="stat-label">Revenue (7d)</div>
          <div className="stat-value">{fmtRupee(sales?.total_revenue)}</div>
          <div className="stat-detail">{sales?.period_days ?? 7}-day period</div>
        </div>

        <div className={`stat-card ${alerts.length > 0 ? 'red' : 'gray'}${statsFlash ? ' stat-flash' : ''}`}>
          <div className="stat-label">Active Alerts</div>
          <div className="stat-value">{alerts.length}</div>
          <div className="stat-detail">{lowStockItems.length} low stock items</div>
        </div>
      </div>

      {/* ── Main grid ──────────────────────────────────────────────── */}
      <div className="dash-grid">
        {/* Inventory table */}
        <div className="dash-panel">
          <h2>Inventory Status</h2>
          <table className="dash-table">
            <thead>
              <tr><th>Product</th><th>SKU</th><th>Stock</th><th>Status</th></tr>
            </thead>
            <tbody>
              {inventory.map(inv => (
                <tr key={inv.id}>
                  <td>{inv.product_name}</td>
                  <td className="mono">{inv.product_sku}</td>
                  <td className="num">{Number(inv.quantity).toFixed(0)}</td>
                  <td>
                    <span className={`status-badge ${inv.quantity <= 5 ? 'critical' : inv.quantity <= 20 ? 'warning' : 'ok'}`}>
                      {inv.quantity <= 5 ? 'Critical' : inv.quantity <= 20 ? 'Low' : 'OK'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Side panels */}
        <div className="dash-side">
          {/* Alerts */}
          <div className="dash-panel small">
            <h2>Alerts {alerts.length > 0 && <span style={{ fontSize: '.65rem', background: '#dc2626', color: '#fff', borderRadius: 10, padding: '1px 7px', marginLeft: 4 }}>{alerts.length}</span>}</h2>
            {alerts.length === 0 ? (
              <p className="empty-state">No active alerts</p>
            ) : alerts.map(a => (
              <div key={a.id} className={`alert-item ${a.alert_type}`}>
                <span className="alert-type">{a.alert_type.replace(/_/g, ' ')}</span>
                <span className="alert-product">{a.product_name}</span>
                <span className="alert-level">Level: {a.current_level != null ? Number(a.current_level).toFixed(0) : '—'}</span>
              </div>
            ))}
          </div>

          {/* Staff */}
          <div className="dash-panel small">
            <h2>Staff ({staff.length})</h2>
            {staff.map(s => (
              <div key={s.id} className="staff-item">
                <span className="staff-name">{s.display_name}</span>
                <span className="staff-role">{s.role.replace(/_/g, ' ')}</span>
              </div>
            ))}
          </div>

          {/* Top products (only shown when data exists) */}
          {sales?.top_products?.length > 0 && (
            <div className="dash-panel small">
              <h2>Top Products (7d)</h2>
              {sales.top_products.map((p, i) => (
                <div key={i} className="top-product">
                  <span className="tp-rank">#{i + 1}</span>
                  <span className="tp-name">{p.name}</span>
                  <span className="tp-qty">{Number(p.units).toFixed(0)} units</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
