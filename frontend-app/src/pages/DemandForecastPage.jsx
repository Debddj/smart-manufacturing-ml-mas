import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './DemandForecastPage.css';

export default function DemandForecastPage() {
  const { user } = useAuth();
  const [stores, setStores] = useState([]);
  const [loading, setLoading] = useState(true);

  // Modal state
  const [selectedStore, setSelectedStore] = useState(null);
  const [modalData, setModalData] = useState(null);
  const [modalLoading, setModalLoading] = useState(false);

  // Global demand data (region-level)
  const [history, setHistory] = useState([]);
  const [aggregate, setAggregate] = useState({});
  const [prediction, setPrediction] = useState({});

  const loadData = async () => {
    try {
      const [stRes, histRes, aggRes, predRes] = await Promise.all([
        api.get(`/api/regions/${user.region_id}/stores?days=30`),
        api.get('/api/demand/history'),
        api.get('/api/demand/aggregate'),
        api.get('/api/demand/prediction'),
      ]);
      setStores(stRes.data);
      setHistory(histRes.data);
      setAggregate(aggRes.data);
      setPrediction(predRes.data);
    } catch (e) {
      console.error("Failed to load demand forecast data", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.region_id) {
      setTimeout(loadData, 0);
      const interval = setInterval(loadData, 10000);
      return () => clearInterval(interval);
    }
  }, [user]);

  // Open the drill-down modal for a specific store
  const openStoreModal = async (store) => {
    setSelectedStore(store);
    setModalLoading(true);
    setModalData(null);
    try {
      const [invRes, salesRes] = await Promise.all([
        api.get(`/api/stores/${store.id}/inventory`),
        api.get(`/api/stores/${store.id}/sales/summary?days=30`),
      ]);
      setModalData({
        inventory: invRes.data,
        sales: salesRes.data,
      });
    } catch (e) {
      console.error("Failed to load store details", e);
      setModalData({ inventory: [], sales: {} });
    } finally {
      setModalLoading(false);
    }
  };

  const closeModal = () => {
    setSelectedStore(null);
    setModalData(null);
  };

  // Chart data from aggregate demand
  const chartData = Object.keys(aggregate).map(key => ({
    name: key,
    Demand: aggregate[key]
  }));

  // Insights
  const items = Object.keys(aggregate);
  let mostDemanded = items[0];
  let leastDemanded = items[0];
  let totalOrders = 0;
  items.forEach(item => {
    const qty = aggregate[item];
    totalOrders += qty;
    if (qty > aggregate[mostDemanded]) mostDemanded = item;
    if (qty < aggregate[leastDemanded]) leastDemanded = item;
  });

  return (
    <div className="forecast-dashboard">
      <div className="forecast-header">
        <h1>Demand Forecast Dashboard</h1>
        <p>Region-level analytics · {stores.length} stores</p>
      </div>

      {loading ? (
        <div className="forecast-loading">Loading analytics...</div>
      ) : (
        <>
          {/* ── Store cards ──────────────────────────────── */}
          <div className="store-cards-grid">
            {stores.map(s => (
              <div key={s.id} className="store-card">
                <div className="store-card-header">
                  <span className="store-card-name">{s.name}</span>
                  <span className="store-card-code">{s.store_code}</span>
                </div>
                <div className="store-card-stats">
                  <div className="store-stat">
                    <div className="store-stat-label">Inventory</div>
                    <div className="store-stat-value">{s.total_inventory?.toFixed(0) || 0}</div>
                  </div>
                  <div className="store-stat">
                    <div className="store-stat-label">Units Sold</div>
                    <div className="store-stat-value">{s.units_sold?.toFixed(0) || 0}</div>
                  </div>
                  <div className="store-stat">
                    <div className="store-stat-label">Revenue</div>
                    <div className="store-stat-value">₹{s.revenue?.toFixed(0) || 0}</div>
                  </div>
                  <div className="store-stat">
                    <div className="store-stat-label">Alerts</div>
                    <div className="store-stat-value" style={{color: s.active_alerts > 0 ? '#DC2626' : '#16A34A'}}>
                      {s.active_alerts || 0}
                    </div>
                  </div>
                </div>
                <button className="enlarge-btn" onClick={() => openStoreModal(s)}>
                  🔍 Enlarge — View Product Forecast
                </button>
              </div>
            ))}
            {stores.length === 0 && <div className="empty-state">No stores found in your region.</div>}
          </div>

          {/* ── Region-level demand summary ────────────── */}
          <div className="forecast-grid">
            <div className="forecast-card">
              <h2>Recent Orders</h2>
              <div className="card-content scrollable">
                {history.length > 0 ? history.slice().reverse().map((item, i) => (
                  <div key={i} className="forecast-row">
                    <span className="row-label">{item.item_name}</span>
                    <span className="row-value">{item.quantity}</span>
                  </div>
                )) : <div className="empty-state">No recent orders</div>}
              </div>
            </div>

            <div className="forecast-card">
              <h2>Demand Summary</h2>
              <div className="card-content scrollable">
                {Object.keys(aggregate).length > 0 ? Object.keys(aggregate).map(item => (
                  <div key={item} className="forecast-row">
                    <span className="row-label">{item}</span>
                    <span className="row-value">{aggregate[item]}</span>
                  </div>
                )) : <div className="empty-state">No data available</div>}
              </div>
            </div>

            <div className="forecast-card">
              <h2>Predicted Demand</h2>
              <div className="card-content scrollable">
                {Object.keys(prediction).length > 0 ? Object.keys(prediction).map(item => {
                  const status = prediction[item].toUpperCase();
                  const colorClass = status === 'HIGH' ? 'high' : status === 'LOW' ? 'low' : 'medium';
                  return (
                    <div key={item} className="forecast-row">
                      <span className="row-label">{item}</span>
                      <span className={`row-badge ${colorClass}`}>{status}</span>
                    </div>
                  );
                }) : <div className="empty-state">No predictions available</div>}
              </div>
            </div>

            <div className="forecast-card highlight-card">
              <h2>Insights</h2>
              <div className="card-content">
                {items.length > 0 ? (
                  <>
                    <div className="insight-row">
                      <span>Most Demanded</span>
                      <strong>{mostDemanded}</strong>
                    </div>
                    <div className="insight-row">
                      <span>Least Demanded</span>
                      <strong>{leastDemanded}</strong>
                    </div>
                    <div className="insight-row">
                      <span>Total Units Ordered</span>
                      <strong>{totalOrders}</strong>
                    </div>
                    <div className="insight-row">
                      <span>Unique Items</span>
                      <strong>{items.length}</strong>
                    </div>
                  </>
                ) : (
                  <div className="empty-state">Not enough data to generate insights.</div>
                )}
              </div>
            </div>
          </div>

          {/* ── Region demand chart ───────────────────── */}
          <div className="forecast-chart-container">
            <h2>Demand Visualization</h2>
            {chartData.length > 0 ? (
              <div style={{ width: '100%', height: 350 }}>
                <ResponsiveContainer>
                  <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 50 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
                    <XAxis
                      dataKey="name"
                      tick={{ fill: '#64748B', fontSize: 12 }}
                      tickLine={false}
                      axisLine={{ stroke: '#D6E0EB' }}
                      angle={-45}
                      textAnchor="end"
                      height={80}
                    />
                    <YAxis
                      tick={{ fill: '#64748B', fontSize: 12 }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <Tooltip
                      cursor={{ fill: '#F8FAFC' }}
                      contentStyle={{
                        borderRadius: '8px',
                        border: '1px solid #D6E0EB',
                        boxShadow: '0 4px 10px rgba(0,0,0,0.08)',
                        backgroundColor: '#FFFFFF',
                        color: '#1E293B'
                      }}
                    />
                    <Bar dataKey="Demand" fill="#2563EB" radius={[6, 6, 0, 0]} barSize={40} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="empty-state" style={{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                No visualization data available.
              </div>
            )}
          </div>
        </>
      )}

      {/* ── Store drill-down modal ────────────────────── */}
      {selectedStore && (
        <div className="forecast-modal-overlay" onClick={closeModal}>
          <div className="forecast-modal" onClick={(e) => e.stopPropagation()}>
            <div className="forecast-modal-header">
              <h2>{selectedStore.name} — Product Demand</h2>
              <button className="modal-close-btn" onClick={closeModal}>✕</button>
            </div>

            {modalLoading ? (
              <div className="forecast-loading">Loading store data...</div>
            ) : modalData ? (
              <>
                {/* Product inventory table */}
                <div className="forecast-card" style={{ minHeight: 'auto', marginBottom: '1rem' }}>
                  <h2>Product Inventory</h2>
                  <div className="card-content scrollable" style={{ maxHeight: '260px' }}>
                    {modalData.inventory.length > 0 ? modalData.inventory.map(inv => (
                      <div key={inv.id || inv.product_id} className="forecast-row">
                        <span className="row-label">{inv.product_name}</span>
                        <span className="row-value" style={{ display: 'flex', alignItems: 'center', gap: '.4rem' }}>
                          {inv.quantity?.toFixed(0) || 0}
                          <span className={`row-badge ${inv.quantity <= 5 ? 'high' : inv.quantity <= 20 ? 'medium' : 'low'}`}>
                            {inv.quantity <= 5 ? 'CRITICAL' : inv.quantity <= 20 ? 'LOW' : 'OK'}
                          </span>
                        </span>
                      </div>
                    )) : <div className="empty-state">No inventory data</div>}
                  </div>
                </div>

                {/* Product demand bar chart */}
                {modalData.inventory.length > 0 && (
                  <div className="forecast-chart-container" style={{ marginBottom: '1rem' }}>
                    <h2>Stock Distribution</h2>
                    <div style={{ width: '100%', height: 280 }}>
                      <ResponsiveContainer>
                        <BarChart
                          data={modalData.inventory.map(inv => ({
                            name: inv.product_name?.length > 18
                              ? inv.product_name.substring(0, 18) + '…'
                              : inv.product_name,
                            Stock: inv.quantity || 0,
                          }))}
                          margin={{ top: 10, right: 20, left: 10, bottom: 60 }}
                        >
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
                          <XAxis
                            dataKey="name"
                            tick={{ fill: '#64748B', fontSize: 11 }}
                            tickLine={false}
                            axisLine={{ stroke: '#D6E0EB' }}
                            angle={-45}
                            textAnchor="end"
                            height={80}
                          />
                          <YAxis tick={{ fill: '#64748B', fontSize: 12 }} tickLine={false} axisLine={false} />
                          <Tooltip
                            cursor={{ fill: '#F8FAFC' }}
                            contentStyle={{
                              borderRadius: '8px', border: '1px solid #D6E0EB',
                              boxShadow: '0 4px 10px rgba(0,0,0,0.08)',
                              backgroundColor: '#FFFFFF', color: '#1E293B'
                            }}
                          />
                          <Bar dataKey="Stock" fill="#3B82F6" radius={[6, 6, 0, 0]} barSize={32} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* Sales summary */}
                {modalData.sales && (
                  <div className="forecast-card highlight-card" style={{ minHeight: 'auto' }}>
                    <h2>Sales Summary (30 days)</h2>
                    <div className="card-content">
                      <div className="insight-row">
                        <span>Total Sales</span>
                        <strong>{modalData.sales.total_sales || 0} transactions</strong>
                      </div>
                      <div className="insight-row">
                        <span>Units Sold</span>
                        <strong>{modalData.sales.total_units?.toFixed(0) || 0}</strong>
                      </div>
                      <div className="insight-row">
                        <span>Revenue</span>
                        <strong>₹{modalData.sales.total_revenue?.toFixed(0) || 0}</strong>
                      </div>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="empty-state">No data available for this store.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
