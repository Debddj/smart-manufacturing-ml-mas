import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './Dashboard.css';

export default function CreateStore() {
  const { user } = useAuth();
  const [name, setName] = useState('');
  const [step, setStep] = useState(1);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    setLoading(true); setError('');
    try {
      const res = await api.post('/api/admin/stores/create', { name, region_id: user.region_id });
      setResult(res.data);
      setStep(3);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create store');
    } finally { setLoading(false); }
  };

  return (
    <div className="dashboard">
      <div className="dash-header">
        <div>
          <h1>Create New Store</h1>
          <p className="dash-subtitle">Step {step} of 3 - Store creation wizard</p>
        </div>
      </div>

      <div className="dash-panel" style={{ maxWidth: 600, margin: '0 auto' }}>
        {step === 1 && (
          <>
            <h2>Store Details</h2>
            {error && <div className="sale-message error">{error}</div>}
            <div className="form-row">
              <label>Store Name</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Downtown Branch" className="form-input" required />
            </div>
            <div className="form-row">
              <label>Assigned Region</label>
              <input type="text" value={user.region_id === 1 ? 'Kolkata' : 'Kashmir'} disabled className="form-input" />
            </div>
            <button className="sale-btn" onClick={() => { if (name.trim()) setStep(2); }} disabled={!name.trim()}>
              Preview Credentials
            </button>
          </>
        )}

        {step === 2 && (
          <>
            <h2>Confirm Creation</h2>
            <p style={{ color: '#8B6045', marginBottom: '1rem' }}>
              Store "<strong style={{ color: '#2C1A0E' }}>{name}</strong>" will be created with auto-generated staff accounts.
            </p>
            <div className="confirm-box">
              <p>Store Manager + Sales Person accounts will be auto-created.</p>
              <p>Inventory will be seeded from regional averages.</p>
              <p>Default password will be generated for each user.</p>
            </div>
            <div style={{ display: 'flex', gap: '1rem', marginTop: '1.5rem' }}>
              <button className="sale-btn secondary" onClick={() => setStep(1)}>Back</button>
              <button className="sale-btn" onClick={handleCreate} disabled={loading}>
                {loading ? 'Creating...' : 'Create Store'}
              </button>
            </div>
          </>
        )}

        {step === 3 && result && (
          <>
            <h2>Store Created Successfully!</h2>
            <div className="success-box">
              <p><strong>Store:</strong> {result.store.name} ({result.store.store_code})</p>
              <p><strong>Region:</strong> {result.store.region}</p>
            </div>
            <h3 style={{ color: '#2C1A0E', margin: '1.5rem 0 0.8rem' }}>Staff Credentials</h3>
            <table className="dash-table">
              <thead><tr><th>User ID</th><th>Password</th><th>Role</th></tr></thead>
              <tbody>
                {result.credentials.map((c, i) => (
                  <tr key={i}>
                    <td className="mono">{c.user_id}</td>
                    <td className="mono">{c.password}</td>
                    <td>{c.role.replace('_', ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button className="sale-btn" onClick={() => { setStep(1); setName(''); setResult(null); }} style={{ marginTop: '1.5rem' }}>
              Create Another Store
            </button>
          </>
        )}
      </div>
    </div>
  );
}
