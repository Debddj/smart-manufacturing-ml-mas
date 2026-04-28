import { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell,
  LineChart, Line, ReferenceLine,
} from 'recharts';
import './DemandForecastPage.css';

const COLORS_DEMAND = { HIGH: '#dc2626', MEDIUM: '#ca8a04', LOW: '#16a34a' };
const CAT_COLORS = ['#8B4513', '#A0522D', '#C8956C', '#D4A574', '#7B5A3C', '#6B3410', '#9C6B3C', '#B8825A'];

// ── Pulse dot for live indicator ───────────────────────────────────────────────
function PulseDot() {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '.35rem', fontSize: '.72rem', color: '#16a34a', fontWeight: 600 }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%', background: '#16a34a',
        boxShadow: '0 0 0 0 rgba(22,163,74,.6)',
        animation: 'livePulse 1.4s ease-in-out infinite',
        display: 'inline-block',
      }} />
      LIVE
    </span>
  );
}

export default function StoreForecastPage() {
  const { user } = useAuth();
  const [forecast, setForecast] = useState(null);
  const [sales, setSales] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('forecast');
  const [categoryFilter, setCategoryFilter] = useState('All');
  const [lastUpdated, setLastUpdated] = useState(null);

  // ── Sales-over-time series: [{time, units, product}] ──────────────────────
  // Starts empty (zero baseline) and grows as orders arrive via WebSocket
  const [salesTimeline, setSalesTimeline] = useState([]);
  const wsRef = useRef(null);

  // ── Core data loader ───────────────────────────────────────────────────────
  const loadData = useCallback(async () => {
    if (!user?.store_id) return;
    try {
      const [forecastRes, salesRes] = await Promise.all([
        api.get(`/api/stores/${user.store_id}/forecast`),
        api.get(`/api/stores/${user.store_id}/sales?days=1`),
      ]);
      setForecast(forecastRes.data);
      setSales(salesRes.data);
      setLastUpdated(new Date());

      // Build today's sales timeline from DB (sorted oldest → newest)
      const sorted = [...salesRes.data].reverse();
      let cumulative = 0;
      const timeline = sorted.map(s => {
        cumulative += s.quantity;
        return {
          time: new Date(s.sold_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          units: cumulative,
          product: s.product_name,
          orderQty: s.quantity,
        };
      });
      // Always start from zero
      setSalesTimeline(timeline.length > 0
        ? [{ time: 'Start', units: 0, product: '', orderQty: 0 }, ...timeline]
        : [{ time: 'Start', units: 0, product: '', orderQty: 0 }]
      );
    } catch (e) {
      console.error('Failed to load forecast data', e);
    } finally {
      setLoading(false);
    }
  }, [user]);

  // ── Initial load + polling every 15 s ─────────────────────────────────────
  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 15000);
    return () => clearInterval(interval);
  }, [loadData]);

  // ── WebSocket: push new point to timeline immediately on inventory_update ──
  useEffect(() => {
    if (!user?.store_id) return;
    const wsUrl = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/inventory?store_id=${user.store_id}`;
    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === 'inventory_update' && msg.store_id === user.store_id) {
            const change = Math.abs(msg.change || 0);
            if (change > 0) {
              const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
              setSalesTimeline(prev => {
                const lastUnits = prev[prev.length - 1]?.units || 0;
                return [...prev, {
                  time: now,
                  units: lastUnits + change,
                  product: msg.product_name,
                  orderQty: change,
                }];
              });
              // Also refresh full forecast data so bar chart and table update
              loadData();
            }
          }
        } catch {}
      };
      ws.onclose = () => {
        // Reconnect after 3 s
        setTimeout(connect, 3000);
      };
    };
    connect();
    return () => { wsRef.current?.close(); };
  }, [user, loadData]);

  if (loading) {
    return <div className="forecast-loading">Loading demand forecast...</div>;
  }

  const products = forecast?.products || [];
  const categories = ['All', ...new Set(products.map(p => p.category))];
  const filteredProducts = categoryFilter === 'All'
    ? products
    : products.filter(p => p.category === categoryFilter);

  const highCount = products.filter(p => p.demand_status === 'HIGH').length;
  const medCount  = products.filter(p => p.demand_status === 'MEDIUM').length;
  const lowCount  = products.filter(p => p.demand_status === 'LOW').length;

  // ── Chart data ─────────────────────────────────────────────────────────────
  // Bar chart: current stock vs base demand (updates every 15 s from DB)
  const stockDemandBar = [...products]
    .sort((a, b) => b.current_stock - a.current_stock)
    .slice(0, 12)
    .map(p => ({
      name: p.sku,
      fullName: p.name,
      stock: Math.round(p.current_stock),
      demand: Math.round(p.base_demand),
      daysOfStock: Math.round(p.current_stock / Math.max(p.base_demand, 1)),
    }));

  // Pies
  const demandPie = [
    { name: 'High Demand',   value: highCount, color: COLORS_DEMAND.HIGH   },
    { name: 'Medium Demand', value: medCount,  color: COLORS_DEMAND.MEDIUM },
    { name: 'Low Demand',    value: lowCount,  color: COLORS_DEMAND.LOW    },
  ];
  const catGroups = {};
  products.forEach(p => { catGroups[p.category] = (catGroups[p.category] || 0) + p.current_stock; });
  const catPie = Object.entries(catGroups).map(([name, value], i) => ({
    name, value: Math.round(value), color: CAT_COLORS[i % CAT_COLORS.length],
  }));

  // Total units sold today
  const totalSoldToday = salesTimeline[salesTimeline.length - 1]?.units || 0;

  const CustomTooltip = ({ active, payload, label }) => {
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
        {d?.daysOfStock !== undefined && (
          <p style={{ color: '#8B6045', marginTop: '.2rem', fontSize: '.72rem' }}>≈ {d.daysOfStock} days of stock</p>
        )}
      </div>
    );
  };

  const TimelineTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload;
    return (
      <div style={{ background: '#FFF8F2', border: '1px solid #D4B896', borderRadius: 8, padding: '.6rem .8rem', fontSize: '.8rem' }}>
        <p style={{ fontWeight: 700, color: '#2C1A0E', marginBottom: '.3rem' }}>{d?.time}</p>
        <p style={{ color: '#8B4513' }}>Total units sold: <strong>{d?.units}</strong></p>
        {d?.product && <p style={{ color: '#C8A882', fontSize: '.72rem' }}>Last: {d.product} (+{d.orderQty})</p>}
      </div>
    );
  };

  return (
    <div className="forecast-dashboard">
      {/* Pulse animation style */}
      <style>{`
        @keyframes livePulse {
          0%   { box-shadow: 0 0 0 0 rgba(22,163,74,.6); }
          70%  { box-shadow: 0 0 0 8px rgba(22,163,74,0); }
          100% { box-shadow: 0 0 0 0 rgba(22,163,74,0); }
        }
      `}</style>

      <div className="forecast-header">
        <div>
          <h1>{forecast?.store_name} — Demand Forecast</h1>
          <p>{forecast?.store_code} · {products.length} products · {forecast?.total_stock?.toFixed(0)} units</p>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '.3rem' }}>
          <PulseDot />
          {lastUpdated && (
            <span style={{ fontSize: '.65rem', color: '#C8A882' }}>
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {/* Tab switcher */}
      <div style={{ display: 'flex', gap: '.5rem', marginBottom: '1.5rem' }}>
        <button
          className="enlarge-btn"
          style={activeTab === 'forecast' ? { background: '#8B4513', color: '#fff', borderColor: '#8B4513' } : {}}
          onClick={() => setActiveTab('forecast')}
        >📊 Product Forecast</button>
        <button
          className="enlarge-btn"
          style={activeTab === 'sales' ? { background: '#8B4513', color: '#fff', borderColor: '#8B4513' } : {}}
          onClick={() => setActiveTab('sales')}
        >📋 Sales Records ({sales.length})</button>
      </div>

      {activeTab === 'forecast' && (
        <>
          {/* Summary cards */}
          <div className="forecast-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', marginBottom: '1.5rem' }}>
            <div className="forecast-card highlight-card" style={{ minHeight: 'auto' }}>
              <h2>Total Products</h2>
              <div className="card-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
                <span style={{ fontSize: '2rem', fontWeight: 700, color: '#2C1A0E' }}>{products.length}</span>
              </div>
            </div>
            <div className="forecast-card" style={{ minHeight: 'auto', borderLeft: '3px solid #dc2626' }}>
              <h2>High Demand</h2>
              <div className="card-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
                <span style={{ fontSize: '2rem', fontWeight: 700, color: '#dc2626' }}>{highCount}</span>
              </div>
            </div>
            <div className="forecast-card" style={{ minHeight: 'auto', borderLeft: '3px solid #ca8a04' }}>
              <h2>Medium Demand</h2>
              <div className="card-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
                <span style={{ fontSize: '2rem', fontWeight: 700, color: '#ca8a04' }}>{medCount}</span>
              </div>
            </div>
            <div className="forecast-card" style={{ minHeight: 'auto', borderLeft: '3px solid #16a34a' }}>
              <h2>Low Demand</h2>
              <div className="card-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
                <span style={{ fontSize: '2rem', fontWeight: 700, color: '#16a34a' }}>{lowCount}</span>
              </div>
            </div>
          </div>

          {/* ── Real-Time Sales Timeline ───────────────────────────────── */}
          <div className="forecast-chart-container" style={{ marginBottom: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '.6rem' }}>
              <h2>Real-Time Sales Today — Cumulative Units</h2>
              <div style={{ display: 'flex', alignItems: 'center', gap: '.8rem' }}>
                <span style={{ fontSize: '.75rem', fontWeight: 700, color: '#8B4513' }}>
                  Total: <strong>{totalSoldToday}</strong> units
                </span>
                <PulseDot />
              </div>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={salesTimeline} margin={{ top: 10, right: 30, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#D4B896" />
                <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#8B6045' }} />
                <YAxis tick={{ fontSize: 11, fill: '#8B6045' }} domain={[0, 'auto']} allowDataOverflow={false} />
                <Tooltip content={<TimelineTooltip />} />
                <ReferenceLine y={0} stroke="#D4B896" strokeWidth={1} />
                <Line
                  type="monotone"
                  dataKey="units"
                  stroke="#8B4513"
                  strokeWidth={2.5}
                  dot={{ fill: '#8B4513', r: 4, strokeWidth: 0 }}
                  activeDot={{ r: 6, fill: '#C8956C' }}
                  name="Units Sold"
                  isAnimationActive={true}
                  animationDuration={600}
                />
              </LineChart>
            </ResponsiveContainer>
            {salesTimeline.length <= 1 && (
              <div style={{ textAlign: 'center', color: '#C8A882', fontSize: '.8rem', marginTop: '.5rem', fontStyle: 'italic' }}>
                Waiting for first sale today… Place an order from the Shop to see the graph update live.
              </div>
            )}
          </div>

          {/* ── Charts row ─────────────────────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
            {/* Bar chart — Stock vs Base Demand */}
            <div className="forecast-chart-container">
              <h2>Stock vs Daily Demand (Top 12)</h2>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={stockDemandBar} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#D4B896" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#8B6045' }} angle={-25} textAnchor="end" height={50} />
                  <YAxis tick={{ fontSize: 11, fill: '#8B6045' }} domain={[0, 'auto']} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: '.78rem' }} />
                  <Bar dataKey="stock" name="Current Stock" fill="#8B4513" radius={[4, 4, 0, 0]} isAnimationActive={true} />
                  <Bar dataKey="demand" name="Daily Demand" fill="#C8956C" radius={[4, 4, 0, 0]} isAnimationActive={true} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Pie charts side column */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div className="forecast-chart-container" style={{ flex: 1 }}>
                <h2>Demand Classification</h2>
                <ResponsiveContainer width="100%" height={130}>
                  <PieChart>
                    <Pie data={demandPie} cx="50%" cy="50%" innerRadius={28} outerRadius={50} paddingAngle={3} dataKey="value"
                      label={({ value }) => `${value}`} isAnimationActive={true}>
                      {demandPie.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                    </Pie>
                    <Tooltip formatter={(value, name) => [`${value} products`, name]} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ display: 'flex', justifyContent: 'center', gap: '.6rem', flexWrap: 'wrap' }}>
                  {demandPie.map(d => (
                    <span key={d.name} style={{ fontSize: '.62rem', display: 'flex', alignItems: 'center', gap: '.2rem', color: '#8B6045' }}>
                      <span style={{ width: 7, height: 7, borderRadius: '50%', background: d.color, display: 'inline-block' }} />
                      {d.name}
                    </span>
                  ))}
                </div>
              </div>
              <div className="forecast-chart-container" style={{ flex: 1 }}>
                <h2>Stock by Category</h2>
                <ResponsiveContainer width="100%" height={130}>
                  <PieChart>
                    <Pie data={catPie} cx="50%" cy="50%" innerRadius={28} outerRadius={50} paddingAngle={3} dataKey="value"
                      label={({ name }) => name.split(' ')[0]} isAnimationActive={true}>
                      {catPie.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                    </Pie>
                    <Tooltip formatter={(value) => [`${value} units`]} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Category filter */}
          <div style={{ display: 'flex', gap: '.4rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
            {categories.map(cat => (
              <button
                key={cat}
                className="enlarge-btn"
                style={categoryFilter === cat ? { background: '#8B4513', color: '#fff', borderColor: '#8B4513' } : {}}
                onClick={() => setCategoryFilter(cat)}
              >{cat}</button>
            ))}
          </div>

          {/* Product table */}
          <div className="forecast-chart-container">
            <h2>Product Demand Analysis ({filteredProducts.length})</h2>
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
                {filteredProducts
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
        </>
      )}

      {activeTab === 'sales' && (
        <div className="forecast-chart-container">
          <h2>Sales Records (Today)</h2>
          {sales.length === 0 ? (
            <div className="empty-state" style={{ padding: '2rem' }}>No sales recorded today. Place an order from the Shop to see records here.</div>
          ) : (
            <table className="modal-product-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Product</th>
                  <th>Quantity</th>
                  <th>Sale Price</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {sales.map((s, i) => (
                  <tr key={s.id}>
                    <td style={{ color: '#C8A882', fontSize: '.78rem' }}>{i + 1}</td>
                    <td style={{ fontWeight: 600 }}>{s.product_name}</td>
                    <td style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{s.quantity}</td>
                    <td style={{ fontVariantNumeric: 'tabular-nums' }}>₹{s.sale_price?.toFixed(2)}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: '.78rem', color: '#8B6045' }}>
                      {new Date(s.sold_at).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
