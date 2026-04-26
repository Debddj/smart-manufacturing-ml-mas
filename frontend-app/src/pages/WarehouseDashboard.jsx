import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './Dashboard.css';

export default function WarehouseDashboard() {
  // user auth context not needed here currently
  useAuth();
  const [warehouses, setWarehouses] = useState([]);
  const [imbalance, setImbalance] = useState(null);
  const [transfers, setTransfers] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [whRes, imbRes, trRes] = await Promise.all([
        api.get('/api/warehouses'),
        api.get('/api/warehouses/imbalance'),
        api.get('/api/warehouses/transfers'),
      ]);
      setWarehouses(whRes.data);
      setImbalance(imbRes.data);
      setTransfers(trRes.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { setTimeout(loadData, 0); }, [loadData]);

  const triggerTransfer = async (fromId, toId) => {
    try {
      await api.post('/api/warehouses/transfer', { from_warehouse_id: fromId, to_warehouse_id: toId, units: 50, reason: 'Manual rebalance' });
      loadData();
    } catch (err) { alert(err.response?.data?.detail || 'Transfer failed'); }
  };

  if (loading) return <div className="dash-loading">Loading warehouse data...</div>;

  return (
    <div className="dashboard">
      <div className="dash-header">
        <div>
          <h1>Warehouse Overview</h1>
          <p className="dash-subtitle">Cross-region stock management</p>
        </div>
      </div>

      <div className="stat-cards">
        {warehouses.map(w => (
          <div key={w.id} className={`stat-card ${w.utilization_pct < 25 ? 'red' : w.utilization_pct > 75 ? 'green' : 'blue'}`}>
            <div className="stat-label">{w.name}</div>
            <div className="stat-value">{w.current_stock.toFixed(0)}</div>
            <div className="stat-detail">{w.utilization_pct.toFixed(0)}% of {w.capacity} capacity</div>
            <div className="util-bar">
              <div className="util-fill" style={{ width: `${Math.min(w.utilization_pct, 100)}%` }}></div>
            </div>
          </div>
        ))}
      </div>

      {imbalance?.imbalance_detected && (
        <div className="dash-panel" style={{ marginBottom: '1.5rem', borderColor: 'rgba(255,107,107,0.3)' }}>
          <h2 style={{ color: '#dc2626' }}>Imbalance Detected</h2>
          <p style={{ color: '#64748b', marginBottom: '1rem' }}>
            Average utilization: {imbalance.average_utilization.toFixed(1)}%
          </p>
          {imbalance.warehouses.map(w => (
            <div key={w.id} className={`alert-item ${w.status === 'critical_low' || w.status === 'low' ? 'out_of_stock' : 'low_stock'}`}>
              <span className="alert-type">{w.status}</span>
              <span className="alert-product">{w.name}</span>
              <span className="alert-level">{w.utilization_pct.toFixed(0)}%</span>
            </div>
          ))}
          {warehouses.length >= 2 && (
            <button className="sale-btn" style={{ marginTop: '1rem' }} onClick={() => triggerTransfer(warehouses[0].id, warehouses[1].id)}>
              Transfer 50 units (WH1 → WH2)
            </button>
          )}
        </div>
      )}

      <div className="dash-panel">
        <h2>Transfer History</h2>
        <table className="dash-table">
          <thead><tr><th>From</th><th>To</th><th>Units</th><th>Reason</th><th>Status</th><th>Date</th></tr></thead>
          <tbody>
            {transfers.map(t => (
              <tr key={t.id}>
                <td>{t.from_warehouse}</td>
                <td>{t.to_warehouse}</td>
                <td className="num">{t.units}</td>
                <td>{t.reason || '-'}</td>
                <td><span className="status-badge ok">{t.status}</span></td>
                <td className="mono">{t.created_at ? new Date(t.created_at).toLocaleDateString() : '-'}</td>
              </tr>
            ))}
            {transfers.length === 0 && <tr><td colSpan={6} className="empty-state">No transfers yet</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
