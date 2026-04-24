import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './Dashboard.css';

export default function TransfersPage() {
  const { user } = useAuth();
  const [nearby, setNearby] = useState([]);
  const [transfers, setTransfers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [transferForm, setTransferForm] = useState({ from_store_id: '', product_id: '', quantity: '' });
  const [products, setProducts] = useState([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [nearbyRes, transferRes, invRes] = await Promise.all([
        api.get(`/api/stores/${user.store_id}/nearby`),
        api.get('/api/transfers'),
        api.get(`/api/stores/${user.store_id}/inventory`),
      ]);
      setNearby(nearbyRes.data);
      setTransfers(transferRes.data);
      setProducts(invRes.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [user]);

  useEffect(() => { setTimeout(loadData, 0); }, [loadData]);

  const requestTransfer = async () => {
    try {
      await api.post('/api/transfers/request', {
        from_store_id: parseInt(transferForm.from_store_id),
        to_store_id: user.store_id,
        product_id: parseInt(transferForm.product_id),
        quantity: parseFloat(transferForm.quantity),
      });
      setShowModal(false);
      loadData();
    } catch (err) { alert(err.response?.data?.detail || 'Request failed'); }
  };

  const approveTransfer = async (id) => {
    try { await api.put(`/api/transfers/${id}/approve`); loadData(); }
    catch (err) { alert(err.response?.data?.detail || 'Approve failed'); }
  };

  const completeTransfer = async (id) => {
    try { await api.put(`/api/transfers/${id}/complete`); loadData(); }
    catch (err) { alert(err.response?.data?.detail || 'Complete failed'); }
  };

  if (loading) return <div className="dash-loading">Loading...</div>;

  return (
    <div className="dashboard">
      <div className="dash-header">
        <div>
          <h1>Inter-Store Transfers</h1>
          <p className="dash-subtitle">Request stock from nearby stores in your region</p>
        </div>
        <button className="sale-btn" onClick={() => setShowModal(true)}>Request Transfer</button>
      </div>

      <div className="dash-grid">
        <div className="dash-panel">
          <h2>Transfer Requests</h2>
          <table className="dash-table">
            <thead><tr><th>From</th><th>To</th><th>Product</th><th>Qty</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
              {transfers.map(t => (
                <tr key={t.id}>
                  <td>{t.from_store_name}</td>
                  <td>{t.to_store_name}</td>
                  <td>{t.product_name}</td>
                  <td className="num">{t.quantity}</td>
                  <td><span className={`status-badge ${t.status === 'completed' ? 'ok' : t.status === 'pending' ? 'warning' : 'critical'}`}>{t.status}</span></td>
                  <td>
                    {t.status === 'pending' && t.from_store_id === user.store_id && (
                      <button className="action-btn" onClick={() => approveTransfer(t.id)}>Approve</button>
                    )}
                    {t.status === 'approved' && (
                      <button className="action-btn" onClick={() => completeTransfer(t.id)}>Complete</button>
                    )}
                  </td>
                </tr>
              ))}
              {transfers.length === 0 && <tr><td colSpan={6} className="empty-state">No transfers</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="dash-side">
          <div className="dash-panel small">
            <h2>Nearby Stores</h2>
            {nearby.map(s => (
              <div key={s.id} className="staff-item">
                <span className="staff-name">{s.name}</span>
                <span className="staff-role">Stock: {s.total_stock.toFixed(0)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>Request Transfer</h2>
            <div className="form-row">
              <label>From Store</label>
              <select value={transferForm.from_store_id} onChange={(e) => setTransferForm({ ...transferForm, from_store_id: e.target.value })} className="form-select">
                <option value="">Select source store</option>
                {nearby.map(s => <option key={s.id} value={s.id}>{s.name} (Stock: {s.total_stock.toFixed(0)})</option>)}
              </select>
            </div>
            <div className="form-row">
              <label>Product</label>
              <select value={transferForm.product_id} onChange={(e) => setTransferForm({ ...transferForm, product_id: e.target.value })} className="form-select">
                <option value="">Select product</option>
                {products.map(p => <option key={p.product_id} value={p.product_id}>{p.product_name}</option>)}
              </select>
            </div>
            <div className="form-row">
              <label>Quantity</label>
              <input type="number" value={transferForm.quantity} onChange={(e) => setTransferForm({ ...transferForm, quantity: e.target.value })} className="form-input" min="1" />
            </div>
            <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
              <button className="sale-btn secondary" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="sale-btn" onClick={requestTransfer}>Submit Request</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
