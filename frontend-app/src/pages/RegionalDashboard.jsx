import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './Dashboard.css';

export default function RegionalDashboard() {
  const { user } = useAuth();
  const [overview, setOverview] = useState(null);
  const [stores, setStores] = useState([]);
  const [topProducts, setTopProducts] = useState([]);
  const [underperforming, setUnderperforming] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        const [ovRes, stRes, tpRes, upRes] = await Promise.all([
          api.get(`/api/regions/${user.region_id}/overview?days=7`),
          api.get(`/api/regions/${user.region_id}/stores?days=7`),
          api.get(`/api/regions/${user.region_id}/products/top?days=7&limit=5`),
          api.get(`/api/regions/${user.region_id}/stores/underperforming?days=7`),
        ]);
        setOverview(ovRes.data);
        setStores(stRes.data);
        setTopProducts(tpRes.data);
        setUnderperforming(upRes.data);
      } catch (err) { console.error(err); }
      finally { setLoading(false); }
    };

    if (user?.region_id) {
      setTimeout(loadData, 0);
    }
  }, [user]);

  if (loading) return <div className="dash-loading">Loading regional data...</div>;

  return (
    <div className="dashboard">
      <div className="dash-header">
        <div>
          <h1>Region {overview?.region_name} - Overview</h1>
          <p className="dash-subtitle">{overview?.store_count} stores | Last {overview?.period_days} days</p>
        </div>
      </div>

      <div className="stat-cards">
        <div className="stat-card purple">
          <div className="stat-label">Total Inventory</div>
          <div className="stat-value">{overview?.total_inventory?.toFixed(0) || 0}</div>
          <div className="stat-detail">units across all stores</div>
        </div>
        <div className="stat-card blue">
          <div className="stat-label">Units Sold</div>
          <div className="stat-value">{overview?.total_units_sold?.toFixed(0) || 0}</div>
          <div className="stat-detail">{overview?.total_sales || 0} transactions</div>
        </div>
        <div className="stat-card green">
          <div className="stat-label">Revenue</div>
          <div className="stat-value">₹{overview?.total_revenue?.toFixed(0) || 0}</div>
          <div className="stat-detail">{overview?.period_days}-day total</div>
        </div>
        <div className={`stat-card ${overview?.active_alerts > 0 ? 'red' : 'gray'}`}>
          <div className="stat-label">Active Alerts</div>
          <div className="stat-value">{overview?.active_alerts || 0}</div>
          <div className="stat-detail">WH stock: {overview?.warehouse_stock?.toFixed(0) || 0}</div>
        </div>
      </div>

      <div className="dash-grid">
        <div className="dash-panel">
          <h2>Store Performance</h2>
          <table className="dash-table">
            <thead><tr><th>Store</th><th>Code</th><th>Inventory</th><th>Units Sold</th><th>Revenue</th><th>Alerts</th></tr></thead>
            <tbody>
              {stores.map(s => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td className="mono">{s.store_code}</td>
                  <td className="num">{s.total_inventory.toFixed(0)}</td>
                  <td className="num">{s.units_sold.toFixed(0)}</td>
                  <td className="num">₹{s.revenue.toFixed(0)}</td>
                  <td><span className={`status-badge ${s.active_alerts > 0 ? 'warning' : 'ok'}`}>{s.active_alerts}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="dash-side">
          <div className="dash-panel small">
            <h2>Top Products</h2>
            {topProducts.map((p, i) => (
              <div key={i} className="top-product">
                <span className="tp-rank">#{i + 1}</span>
                <span className="tp-name">{p.name}</span>
                <span className="tp-qty">{p.total_units.toFixed(0)} units</span>
              </div>
            ))}
            {topProducts.length === 0 && <p className="empty-state">No sales data yet</p>}
          </div>

          {underperforming.length > 0 && (
            <div className="dash-panel small">
              <h2>Underperforming Stores</h2>
              {underperforming.map(s => (
                <div key={s.store_id} className="alert-item low_stock">
                  <span className="alert-product">{s.name}</span>
                  <span className="alert-level">-{s.deficit_pct.toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
