import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import useWebSocket from '../hooks/useWebSocket';
import api from '../api/client';
import './Dashboard.css';

export default function StoreDashboard() {
  const { user } = useAuth();
  const [store, setStore] = useState(null);
  const [inventory, setInventory] = useState([]);
  const [sales, setSales] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [staff, setStaff] = useState([]);
  const [loading, setLoading] = useState(true);
  const { lastMessage, isConnected } = useWebSocket(user?.store_id);

  useEffect(() => {
    const loadData = async () => {
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
      } catch (err) {
        console.error('Failed to load store data:', err);
      } finally { setLoading(false); }
    };

    if (user?.store_id) {
      setTimeout(loadData, 0);
    }
  }, [user]);

  useEffect(() => {
    const loadAlerts = async () => {
      try {
        const res = await api.get(`/api/stores/${user?.store_id}/alerts?resolved=false`);
        setAlerts(res.data);
      } catch {
        // ignore
      }
    };

    if (lastMessage?.type === 'inventory_update' && lastMessage.store_id === user?.store_id) {
      setTimeout(() => {
        setInventory(prev => prev.map(inv =>
          inv.product_id === lastMessage.product_id ? { ...inv, quantity: lastMessage.new_quantity } : inv
        ));
        if (lastMessage.alert) {
          loadAlerts();
        }
      }, 0);
    }
  }, [lastMessage, user?.store_id]);

  if (loading) return <div className="dash-loading">Loading dashboard...</div>;

  const totalStock = inventory.reduce((s, i) => s + i.quantity, 0);
  const lowStockItems = inventory.filter(i => i.quantity < 20);

  return (
    <div className="dashboard">
      <div className="dash-header">
        <div>
          <h1>{store?.name || 'Store Dashboard'}</h1>
          <p className="dash-subtitle">Code: {store?.store_code} | Real-time inventory management</p>
        </div>
        <div className="ws-indicator">
          <span className={`ws-dot ${isConnected ? 'connected' : ''}`}></span>
          {isConnected ? 'Live' : 'Offline'}
        </div>
      </div>

      <div className="stat-cards">
        <div className="stat-card purple">
          <div className="stat-label">Total Stock</div>
          <div className="stat-value">{totalStock.toFixed(0)}</div>
          <div className="stat-detail">{inventory.length} products</div>
        </div>
        <div className="stat-card blue">
          <div className="stat-label">Weekly Sales</div>
          <div className="stat-value">{sales?.total_units?.toFixed(0) || 0}</div>
          <div className="stat-detail">{sales?.total_sales || 0} transactions</div>
        </div>
        <div className="stat-card green">
          <div className="stat-label">Revenue (7d)</div>
          <div className="stat-value">₹{sales?.total_revenue?.toFixed(0) || 0}</div>
          <div className="stat-detail">{sales?.period_days}-day period</div>
        </div>
        <div className={`stat-card ${alerts.length > 0 ? 'red' : 'gray'}`}>
          <div className="stat-label">Active Alerts</div>
          <div className="stat-value">{alerts.length}</div>
          <div className="stat-detail">{lowStockItems.length} low stock items</div>
        </div>
      </div>

      <div className="dash-grid">
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
                  <td className="num">{inv.quantity.toFixed(0)}</td>
                  <td><span className={`status-badge ${inv.quantity <= 5 ? 'critical' : inv.quantity <= 20 ? 'warning' : 'ok'}`}>
                    {inv.quantity <= 5 ? 'Critical' : inv.quantity <= 20 ? 'Low' : 'OK'}
                  </span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="dash-side">
          <div className="dash-panel small">
            <h2>Alerts</h2>
            {alerts.length === 0 ? (
              <p className="empty-state">No active alerts</p>
            ) : alerts.map(a => (
              <div key={a.id} className={`alert-item ${a.alert_type}`}>
                <span className="alert-type">{a.alert_type.replace('_', ' ')}</span>
                <span className="alert-product">{a.product_name}</span>
                <span className="alert-level">Level: {a.current_level}</span>
              </div>
            ))}
          </div>

          <div className="dash-panel small">
            <h2>Staff ({staff.length})</h2>
            {staff.map(s => (
              <div key={s.id} className="staff-item">
                <span className="staff-name">{s.display_name}</span>
                <span className="staff-role">{s.role.replace('_', ' ')}</span>
              </div>
            ))}
          </div>

          {sales?.top_products?.length > 0 && (
            <div className="dash-panel small">
              <h2>Top Products (7d)</h2>
              {sales.top_products.map((p, i) => (
                <div key={i} className="top-product">
                  <span className="tp-rank">#{i + 1}</span>
                  <span className="tp-name">{p.name}</span>
                  <span className="tp-qty">{p.units.toFixed(0)} units</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
