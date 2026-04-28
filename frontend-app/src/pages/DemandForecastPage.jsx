import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell,
  RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar,
} from 'recharts';
import './DemandForecastPage.css';

const COLORS_DEMAND = { HIGH: '#dc2626', MEDIUM: '#ca8a04', LOW: '#16a34a' };
const PIE_COLORS = ['#8B4513', '#A0522D', '#C8956C', '#D4A574', '#7B5A3C', '#6B3410', '#9C6B3C', '#B8825A'];

export default function DemandForecastPage() {
  const { user } = useAuth();
  const [stores, setStores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedStore, setSelectedStore] = useState(null);

  const [lastUpdated, setLastUpdated] = useState(null);
  const [liveFlash, setLiveFlash] = useState(false);

  const loadForecastData = async (silent = false) => {
    if (!user?.region_id) return;
    if (!silent) setLoading(true);
    try {
      const res = await api.get(`/api/regions/${user.region_id}/stores/forecast`);
      setStores(res.data);
      setLastUpdated(new Date());
    } catch (e) {
      console.error("Failed to load forecast data", e);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // Initial load + 30-second polling
  useEffect(() => {
    if (!user?.region_id) return;
    loadForecastData();
    const interval = setInterval(() => loadForecastData(true), 30000);
    return () => clearInterval(interval);
  }, [user?.region_id]);

  // SSE — listen for order_inventory_change events → refresh immediately
  useEffect(() => {
    if (!user?.region_id) return;
    const evtSource = new EventSource('/api/stream');
    evtSource.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (ev.type === 'order_inventory_change') {
          setLiveFlash(true);
          setTimeout(() => setLiveFlash(false), 2500);
          loadForecastData(true);
        }
      } catch { /* ignore */ }
    };
    evtSource.onerror = () => {};
    return () => evtSource.close();
  }, [user?.region_id]);

  const totalProducts = stores.reduce((sum, s) => sum + s.product_count, 0);
  const highDemandCount = stores.reduce(
    (sum, s) => sum + s.products.filter(p => p.demand_status === 'HIGH').length, 0
  );
  const totalStock = stores.reduce((sum, s) => sum + s.total_stock, 0);

  // ── Chart data ────────────────────────────────────────────────
  // Bar chart: stock & high-demand count per store
  const storeBarData = stores.map(s => ({
    name: s.store_code,
    fullName: s.name,
    stock: s.total_stock,
    highDemand: s.products.filter(p => p.demand_status === 'HIGH').length,
    medDemand: s.products.filter(p => p.demand_status === 'MEDIUM').length,
    lowDemand: s.products.filter(p => p.demand_status === 'LOW').length,
  }));

  // Pie chart: aggregate demand distribution across region
  const regionDemandPie = [
    { name: 'High Demand', value: highDemandCount, color: COLORS_DEMAND.HIGH },
    { name: 'Medium Demand', value: stores.reduce((s, st) => s + st.products.filter(p => p.demand_status === 'MEDIUM').length, 0), color: COLORS_DEMAND.MEDIUM },
    { name: 'Low Demand', value: stores.reduce((s, st) => s + st.products.filter(p => p.demand_status === 'LOW').length, 0), color: COLORS_DEMAND.LOW },
  ];

  // Stock distribution pie
  const stockPie = stores.map((s, i) => ({
    name: s.store_code,
    value: s.total_stock,
    color: PIE_COLORS[i % PIE_COLORS.length],
  }));

  // Custom tooltip
  const CustomBarTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload;
    return (
      <div style={{ background: '#FFF8F2', border: '1px solid #D4B896', borderRadius: 8, padding: '.6rem .8rem', boxShadow: '0 4px 12px rgba(61,28,10,.10)', fontSize: '.8rem' }}>
        <p style={{ fontWeight: 700, marginBottom: '.3rem', color: '#2C1A0E' }}>{d?.fullName || label}</p>
        {payload.map((p, i) => (
          <p key={i} style={{ color: p.color, margin: '.15rem 0' }}>
            {p.name}: <strong>{p.value}</strong>
          </p>
        ))}
      </div>
    );
  };

  return (
    <div className="forecast-dashboard">
      <div className="forecast-header">
        <div>
          <h1>Regional Demand Forecast</h1>
          <p>Store-level demand analysis for your region · Live inventory-driven updates</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexShrink: 0 }}>
          {/* Live update flash badge */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '.4rem',
            padding: '.3rem .7rem', borderRadius: 20,
            background: liveFlash ? '#f97316' : '#22c55e',
            color: '#fff', fontSize: '.7rem', fontWeight: 700,
            transition: 'background .4s ease',
            boxShadow: liveFlash ? '0 0 8px rgba(249,115,22,.6)' : '0 0 6px rgba(34,197,94,.4)',
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%', background: '#fff',
              display: 'inline-block',
              animation: 'pulse 1.5s infinite',
            }} />
            {liveFlash ? '⚡ ORDER UPDATE' : '● LIVE'}
          </div>
          {/* Last updated */}
          {lastUpdated && (
            <span style={{ fontSize: '.68rem', color: '#8B6045' }}>
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          {/* Manual refresh */}
          <button
            onClick={() => loadForecastData(false)}
            style={{
              padding: '.3rem .7rem', borderRadius: 8, fontSize: '.72rem', fontWeight: 600,
              border: '1px solid #D4B896', background: '#F5EDE0', color: '#8B4513',
              cursor: 'pointer',
            }}
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {loading ? (
        <div className="forecast-loading">Loading store forecasts...</div>
      ) : (
        <>
          {/* Summary cards */}
          <div className="forecast-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', marginBottom: '1.5rem' }}>
            <div className="forecast-card highlight-card" style={{ minHeight: 'auto' }}>
              <h2>Stores</h2>
              <div className="card-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
                <span style={{ fontSize: '2rem', fontWeight: 700, color: '#2C1A0E' }}>{stores.length}</span>
              </div>
            </div>
            <div className="forecast-card highlight-card" style={{ minHeight: 'auto' }}>
              <h2>Total Products</h2>
              <div className="card-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
                <span style={{ fontSize: '2rem', fontWeight: 700, color: '#2C1A0E' }}>{totalProducts}</span>
              </div>
            </div>
            <div className="forecast-card highlight-card" style={{ minHeight: 'auto' }}>
              <h2>High Demand Items</h2>
              <div className="card-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
                <span style={{ fontSize: '2rem', fontWeight: 700, color: '#dc2626' }}>{highDemandCount}</span>
              </div>
            </div>
            <div className="forecast-card highlight-card" style={{ minHeight: 'auto' }}>
              <h2>Total Stock</h2>
              <div className="card-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
                <span style={{ fontSize: '2rem', fontWeight: 700, color: '#2C1A0E' }}>{totalStock.toFixed(0)}</span>
              </div>
            </div>
          </div>

          {/* ── Charts Section ──────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
            {/* Bar chart — Demand by Store */}
            <div className="forecast-chart-container">
              <h2>Demand Distribution by Store</h2>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={storeBarData} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#D4B896" />
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#8B6045' }} />
                  <YAxis tick={{ fontSize: 12, fill: '#8B6045' }} />
                  <Tooltip content={<CustomBarTooltip />} />
                  <Legend wrapperStyle={{ fontSize: '.78rem' }} />
                  <Bar dataKey="highDemand" name="High Demand" fill="#dc2626" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="medDemand" name="Medium Demand" fill="#ca8a04" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="lowDemand" name="Low Demand" fill="#16a34a" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Pie charts */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div className="forecast-chart-container" style={{ flex: 1 }}>
                <h2>Regional Demand Split</h2>
                <ResponsiveContainer width="100%" height={130}>
                  <PieChart>
                    <Pie data={regionDemandPie} cx="50%" cy="50%" innerRadius={30} outerRadius={55} paddingAngle={3} dataKey="value" label={({ name, value }) => `${value}`}>
                      {regionDemandPie.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value, name) => [`${value} items`, name]} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ display: 'flex', justifyContent: 'center', gap: '.8rem', marginTop: '.3rem' }}>
                  {regionDemandPie.map(d => (
                    <span key={d.name} style={{ fontSize: '.65rem', display: 'flex', alignItems: 'center', gap: '.25rem', color: '#8B6045' }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: d.color, display: 'inline-block' }} />
                      {d.name}
                    </span>
                  ))}
                </div>
              </div>

              <div className="forecast-chart-container" style={{ flex: 1 }}>
                <h2>Stock Distribution</h2>
                <ResponsiveContainer width="100%" height={130}>
                  <PieChart>
                    <Pie data={stockPie} cx="50%" cy="50%" innerRadius={30} outerRadius={55} paddingAngle={3} dataKey="value" label={({ name }) => name}>
                      {stockPie.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value) => [`${value} units`]} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Store forecast cards */}
          <div className="forecast-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
            {stores.map(store => {
              const highItems = store.products.filter(p => p.demand_status === 'HIGH');
              const medItems = store.products.filter(p => p.demand_status === 'MEDIUM');
              const lowItems = store.products.filter(p => p.demand_status === 'LOW');

              return (
                <div key={store.store_id} className="store-forecast-card">
                  <div className="store-card-header">
                    <div>
                      <h3>{store.name}</h3>
                      <span className="store-code">{store.store_code}</span>
                    </div>
                    <button className="enlarge-btn" onClick={() => setSelectedStore(store)}>
                      <span>🔍</span> Enlarge
                    </button>
                  </div>

                  <div style={{ display: 'flex', gap: '.6rem', marginBottom: '.8rem', flexWrap: 'wrap' }}>
                    <span className="row-badge high">{highItems.length} High</span>
                    <span className="row-badge medium">{medItems.length} Medium</span>
                    <span className="row-badge low">{lowItems.length} Low</span>
                    <span style={{ fontSize: '.7rem', color: '#8B6045', marginLeft: 'auto' }}>
                      Stock: {store.total_stock.toFixed(0)} units
                    </span>
                  </div>

                  <div className="store-products-mini">
                    {store.products
                      .sort((a, b) => ({ HIGH: 0, MEDIUM: 1, LOW: 2 }[a.demand_status] - { HIGH: 0, MEDIUM: 1, LOW: 2 }[b.demand_status]))
                      .slice(0, 5)
                      .map(p => (
                        <span key={p.product_id} className="product-chip">
                          {p.name.length > 22 ? p.name.slice(0, 22) + '…' : p.name}
                        </span>
                      ))}
                    {store.products.length > 5 && (
                      <span className="product-chip" style={{ color: '#8B4513', fontWeight: 600 }}>
                        +{store.products.length - 5} more
                      </span>
                    )}
                  </div>
                </div>
              );
            })}

            {stores.length === 0 && (
              <div className="empty-state" style={{ gridColumn: '1 / -1' }}>No stores found in your region.</div>
            )}
          </div>
        </>
      )}

      {/* ── Enlarge Modal ─────────────────────────────────────── */}
      {selectedStore && (
        <div className="forecast-modal-overlay" onClick={() => setSelectedStore(null)}>
          <div className="forecast-modal" onClick={e => e.stopPropagation()} style={{ position: 'relative', maxWidth: '900px', width: '92vw' }}>
            <button
              onClick={() => setSelectedStore(null)}
              style={{
                position: 'absolute', top: '1rem', right: '1rem',
                background: '#EDD9C2', border: '1px solid #D4B896',
                color: '#8B6045', width: 32, height: 32, borderRadius: 8,
                cursor: 'pointer', fontSize: '1rem',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >✕</button>

            <h2>{selectedStore.name}</h2>
            <p className="modal-subtitle">
              {selectedStore.store_code} · {selectedStore.product_count} products · {selectedStore.total_stock.toFixed(0)} total units
            </p>

            {/* Charts inside modal */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
              <div style={{ background: '#F5EDE0', borderRadius: 8, padding: '.8rem', border: '1px solid #D4B896' }}>
                <p style={{ fontSize: '.72rem', fontWeight: 700, color: '#8B6045', textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: '.5rem' }}>Stock vs Base Demand (Top 10)</p>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={selectedStore.products.sort((a, b) => b.base_demand - a.base_demand).slice(0, 10).map(p => ({
                    name: p.sku,
                    stock: p.current_stock,
                    demand: p.base_demand,
                  }))} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#D4B896" />
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#8B6045' }} angle={-30} textAnchor="end" height={50} />
                    <YAxis tick={{ fontSize: 10, fill: '#8B6045' }} />
                    <Tooltip />
                    <Bar dataKey="stock" name="Stock" fill="#8B4513" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="demand" name="Daily Demand" fill="#C8956C" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div style={{ background: '#F5EDE0', borderRadius: 8, padding: '.8rem', border: '1px solid #D4B896' }}>
                <p style={{ fontSize: '.72rem', fontWeight: 700, color: '#8B6045', textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: '.5rem' }}>Demand Classification</p>
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={[
                        { name: 'High', value: selectedStore.products.filter(p => p.demand_status === 'HIGH').length, color: '#dc2626' },
                        { name: 'Medium', value: selectedStore.products.filter(p => p.demand_status === 'MEDIUM').length, color: '#ca8a04' },
                        { name: 'Low', value: selectedStore.products.filter(p => p.demand_status === 'LOW').length, color: '#16a34a' },
                      ]}
                      cx="50%" cy="50%" innerRadius={40} outerRadius={70} paddingAngle={4} dataKey="value"
                      label={({ name, value }) => `${name}: ${value}`}
                    >
                      <Cell fill="#dc2626" />
                      <Cell fill="#ca8a04" />
                      <Cell fill="#16a34a" />
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            <table className="modal-product-table">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>SKU</th>
                  <th>Category</th>
                  <th>Stock</th>
                  <th>Base Demand</th>
                  <th>Price</th>
                  <th>Forecast</th>
                </tr>
              </thead>
              <tbody>
                {selectedStore.products
                  .sort((a, b) => ({ HIGH: 0, MEDIUM: 1, LOW: 2 }[a.demand_status] - { HIGH: 0, MEDIUM: 1, LOW: 2 }[b.demand_status]))
                  .map(p => (
                    <tr key={p.product_id}>
                      <td style={{ fontWeight: 600 }}>{p.name}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: '.78rem', color: '#8B6045' }}>{p.sku}</td>
                      <td style={{ fontSize: '.78rem' }}>{p.category}</td>
                      <td style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{p.current_stock.toFixed(0)}</td>
                      <td style={{ fontVariantNumeric: 'tabular-nums', color: '#8B6045' }}>{p.base_demand}/day</td>
                      <td style={{ fontVariantNumeric: 'tabular-nums' }}>₹{p.unit_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                      <td><span className={`row-badge ${p.demand_status.toLowerCase()}`}>{p.demand_status}</span></td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
