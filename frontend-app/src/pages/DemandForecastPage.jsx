import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import api from '../api/client';
import './DemandForecastPage.css';

export default function DemandForecastPage() {
  const [history, setHistory] = useState([]);
  const [aggregate, setAggregate] = useState({});
  const [prediction, setPrediction] = useState({});
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    try {
      const [histRes, aggRes, predRes] = await Promise.all([
        api.get('/api/demand/history'),
        api.get('/api/demand/aggregate'),
        api.get('/api/demand/prediction')
      ]);
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
    setTimeout(loadData, 0);
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, []);

  const chartData = Object.keys(aggregate).map(key => ({
    name: key,
    Demand: aggregate[key]
  }));

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
        <p>Real-time analytics and predictions for product demand</p>
      </div>

      {loading && Object.keys(aggregate).length === 0 ? (
        <div className="forecast-loading">Loading analytics...</div>
      ) : (
        <>
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

          <div className="forecast-chart-container">
            <h2>Demand Visualization</h2>
            {chartData.length > 0 ? (
              <div style={{ width: '100%', height: 350 }}>
                <ResponsiveContainer>
                  <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 50 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis 
                      dataKey="name" 
                      tick={{ fill: '#64748b', fontSize: 12 }}
                      tickLine={false}
                      axisLine={{ stroke: '#cbd5e1' }}
                      angle={-45}
                      textAnchor="end"
                      height={80}
                    />
                    <YAxis 
                      tick={{ fill: '#64748b', fontSize: 12 }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <Tooltip 
                      cursor={{ fill: '#f8fafc' }}
                      contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)' }}
                    />
                    <Bar dataKey="Demand" fill="#3b82f6" radius={[4, 4, 0, 0]} barSize={40} />
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
    </div>
  );
}
