import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell,
  AreaChart, Area,
} from 'recharts';
import './DemandForecastPage.css';

const COLORS_DEMAND = { HIGH: '#dc2626', MEDIUM: '#ca8a04', LOW: '#16a34a' };
const CAT_COLORS = ['#8B4513', '#A0522D', '#C8956C', '#D4A574', '#7B5A3C', '#6B3410', '#9C6B3C', '#B8825A'];

export default function StoreForecastPage() {
  const { user } = useAuth();
  const [forecast, setForecast] = useState(null);
  const [sales, setSales] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('forecast');
  const [categoryFilter, setCategoryFilter] = useState('All');

  useEffect(() => {
    const loadData = async () => {
      try {
        const [forecastRes, salesRes] = await Promise.all([
          api.get(`/api/stores/${user.store_id}/forecast`),
          api.get(`/api/stores/${user.store_id}/sales?days=30`),
        ]);
        setForecast(forecastRes.data);
        setSales(salesRes.data);
      } catch (e) {
        console.error('Failed to load forecast data', e);
      } finally {
        setLoading(false);
      }
    };
    if (user?.store_id) setTimeout(loadData, 0);
  }, [user]);

  if (loading) {
    return <div className="forecast-loading">Loading demand forecast...</div>;
  }

  const products = forecast?.products || [];
  const categories = ['All', ...new Set(products.map(p => p.category))];
  const filteredProducts = categoryFilter === 'All'
    ? products
    : products.filter(p => p.category === categoryFilter);

  const highCount = products.filter(p => p.demand_status === 'HIGH').length;
  const medCount = products.filter(p => p.demand_status === 'MEDIUM').length;
  const lowCount = products.filter(p => p.demand_status === 'LOW').length;

  // ── Chart data ─────────────────────────────────────────────────
  // Bar chart: stock vs base demand per product (top 12)
  const stockDemandBar = [...products]
    .sort((a, b) => b.base_demand - a.base_demand)
    .slice(0, 12)
    .map(p => ({
      name: p.sku,
      fullName: p.name,
      stock: p.current_stock,
      demand: p.base_demand,
      daysOfStock: Math.round(p.current_stock / Math.max(p.base_demand, 1)),
    }));

  // Pie: demand status distribution
  const demandPie = [
    { name: 'High Demand', value: highCount, color: COLORS_DEMAND.HIGH },
    { name: 'Medium Demand', value: medCount, color: COLORS_DEMAND.MEDIUM },
    { name: 'Low Demand', value: lowCount, color: COLORS_DEMAND.LOW },
  ];

  // Pie: stock by category
  const catGroups = {};
  products.forEach(p => {
    catGroups[p.category] = (catGroups[p.category] || 0) + p.current_stock;
  });
  const catPie = Object.entries(catGroups).map(([name, value], i) => ({
    name,
    value,
    color: CAT_COLORS[i % CAT_COLORS.length],
  }));

  // Area chart: days of stock coverage per product
  const coverageData = [...products]
    .map(p => ({
      name: p.sku,
      days: Math.round(p.current_stock / Math.max(p.base_demand, 1)),
    }))
    .sort((a, b) => a.days - b.days);

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

  return (
    <div className="forecast-dashboard">
      <div className="forecast-header">
        <h1>{forecast?.store_name} — Demand Forecast</h1>
        <p>{forecast?.store_code} · {products.length} products · {forecast?.total_stock?.toFixed(0)} units</p>
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

          {/* ── Charts ─────────────────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
            {/* Bar chart — Stock vs Daily Demand */}
            <div className="forecast-chart-container">
              <h2>Stock vs Daily Demand (Top 12)</h2>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={stockDemandBar} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#D4B896" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#8B6045' }} angle={-25} textAnchor="end" height={50} />
                  <YAxis tick={{ fontSize: 11, fill: '#8B6045' }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: '.78rem' }} />
                  <Bar dataKey="stock" name="Current Stock" fill="#8B4513" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="demand" name="Daily Demand" fill="#C8956C" radius={[4, 4, 0, 0]} />
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
                      label={({ name, value }) => `${value}`}>
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
                      label={({ name }) => name.split(' ')[0]}>
                      {catPie.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                    </Pie>
                    <Tooltip formatter={(value) => [`${value} units`]} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Area chart — days of stock coverage */}
          <div className="forecast-chart-container" style={{ marginBottom: '1.5rem' }}>
            <h2>Stock Coverage (Days of Supply)</h2>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={coverageData} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#D4B896" />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#8B6045' }} angle={-25} textAnchor="end" height={45} />
                <YAxis tick={{ fontSize: 11, fill: '#8B6045' }} label={{ value: 'Days', angle: -90, position: 'insideLeft', style: { fontSize: 11, fill: '#C8A882' } }} />
                <Tooltip formatter={(value) => [`${value} days`, 'Coverage']} />
                <defs>
                  <linearGradient id="coverageGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#8B4513" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#8B4513" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <Area type="monotone" dataKey="days" stroke="#8B4513" fill="url(#coverageGrad)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
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
          <h2>Sales Records (Last 30 Days)</h2>
          {sales.length === 0 ? (
            <div className="empty-state" style={{ padding: '2rem' }}>No sales recorded in the last 30 days.</div>
          ) : (
            <table className="modal-product-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Product</th>
                  <th>Quantity</th>
                  <th>Sale Price</th>
                  <th>Sold By</th>
                  <th>Date & Time</th>
                </tr>
              </thead>
              <tbody>
                {sales.map((s, i) => (
                  <tr key={s.id}>
                    <td style={{ color: '#C8A882', fontSize: '.78rem' }}>{i + 1}</td>
                    <td style={{ fontWeight: 600 }}>{s.product_name}</td>
                    <td style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{s.quantity}</td>
                    <td style={{ fontVariantNumeric: 'tabular-nums' }}>₹{s.sale_price?.toFixed(2)}</td>
                    <td style={{ fontSize: '.78rem', color: '#8B6045' }}>{s.sold_by || '—'}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: '.78rem', color: '#8B6045' }}>
                      {new Date(s.sold_at).toLocaleString()}
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
