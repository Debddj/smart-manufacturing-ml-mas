import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './Dashboard.css';

export default function SalesPersonView() {
  const { user } = useAuth();
  const [products, setProducts] = useState([]);
  const [selectedProduct, setSelectedProduct] = useState('');
  const [quantity, setQuantity] = useState('');
  const [message, setMessage] = useState(null);
  const [sales, setSales] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchDashboardData = useCallback(async () => {
    try {
      const [invRes, salesRes] = await Promise.all([
        api.get(`/api/stores/${user.store_id}/inventory`),
        api.get(`/api/stores/${user.store_id}/sales?days=1`),
      ]);
      setProducts(invRes.data);
      setSales(salesRes.data);
      if (invRes.data.length > 0) {
        setSelectedProduct(prev => prev || invRes.data[0].product_id);
      }
    } catch (err) { console.error(err); }
  }, [user]);

  useEffect(() => { 
    let active = true;
    const init = async () => {
      await fetchDashboardData();
      if (active) setLoading(false);
    };
    init();
    return () => { active = false; };
  }, [fetchDashboardData]);

  const handleSale = async (e) => {
    e.preventDefault();
    if (!selectedProduct || !quantity || parseFloat(quantity) <= 0) return;
    try {
      const res = await api.post(`/api/stores/${user.store_id}/sales`, {
        product_id: parseInt(selectedProduct),
        quantity: parseFloat(quantity),
      });
      setMessage({ type: 'success', text: `Sale recorded: ${res.data.quantity_sold} x ${res.data.product_name} | Remaining: ${res.data.remaining_stock}` });
      if (res.data.alert) setMessage({ type: 'warning', text: `Alert: ${res.data.alert.replace('_', ' ')} for ${res.data.product_name}!` });
      setQuantity('');
      fetchDashboardData();
    } catch (err) {
      setMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to record sale' });
    }
  };

  if (loading) return <div className="dash-loading">Loading...</div>;

  return (
    <div className="dashboard">
      <div className="dash-header">
        <div>
          <h1>Record Sale</h1>
          <p className="dash-subtitle">Manual quantity entry per product</p>
        </div>
      </div>

      <div className="dash-grid">
        <div className="dash-panel">
          <h2>New Sale</h2>
          {message && (
            <div className={`sale-message ${message.type}`}>{message.text}</div>
          )}
          <form onSubmit={handleSale} className="sale-form">
            <div className="form-row">
              <label>Product</label>
              <select value={selectedProduct} onChange={(e) => setSelectedProduct(e.target.value)} className="form-select">
                {products.map(p => (
                  <option key={p.product_id} value={p.product_id}>
                    {p.product_name} (Stock: {p.quantity.toFixed(0)})
                  </option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <label>Quantity</label>
              <input type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} min="1" step="1" placeholder="Enter quantity" className="form-input" required />
            </div>
            <button type="submit" className="sale-btn">Record Sale</button>
          </form>

          <h2 style={{ marginTop: '2rem' }}>Today's Sales ({sales.length})</h2>
          <table className="dash-table">
            <thead><tr><th>Product</th><th>Qty</th><th>Price</th><th>Time</th></tr></thead>
            <tbody>
              {sales.map(s => (
                <tr key={s.id}>
                  <td>{s.product_name}</td>
                  <td className="num">{s.quantity}</td>
                  <td className="num">₹{s.sale_price?.toFixed(2)}</td>
                  <td className="mono">{new Date(s.sold_at).toLocaleTimeString()}</td>
                </tr>
              ))}
              {sales.length === 0 && <tr><td colSpan={4} className="empty-state">No sales today</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="dash-side">
          <div className="dash-panel small">
            <h2>Current Stock</h2>
            {products.map(p => (
              <div key={p.product_id} className="stock-row">
                <span className="stock-name">{p.product_name}</span>
                <span className={`stock-qty ${p.quantity <= 5 ? 'critical' : p.quantity <= 20 ? 'low' : ''}`}>
                  {p.quantity.toFixed(0)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
