import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './LoginPage.css';

export default function LoginPage() {
  const [userId, setUserId] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const { login, loading, getDefaultRoute } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const result = await login(userId.trim(), password);
    if (result.success) {
      navigate(getDefaultRoute(result.user.role));
    } else {
      setError(result.error);
    }
  };

  return (
    <div className="login-container">
      <div className="login-bg-grid"></div>
      <div className="login-card">
        <div className="login-header">
          <div className="login-icon">&#9881;</div>
          <h1>Supply Chain MAS</h1>
          <p className="login-subtitle">Multi-Store Management System</p>
        </div>
        <form onSubmit={handleSubmit} className="login-form">
          {error && <div className="login-error">{error}</div>}
          <div className="input-group">
            <label htmlFor="userId">User ID</label>
            <input
              id="userId"
              type="text"
              value={userId}
              onChange={(e) => setUserId(e.target.value.trim())}
              placeholder="e.g. sm_n1, sp_n1, rm_north"
              autoFocus
              required
            />
          </div>
          <div className="input-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              required
            />
          </div>
          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
        <div className="login-footer">
          <p>Demo Accounts</p>
          <div className="demo-accounts">
            <span className="demo-tag" onClick={() => { setUserId('sm_n1'); setPassword('password123'); }}>Store Manager</span>
            <span className="demo-tag" onClick={() => { setUserId('sp_n1'); setPassword('password123'); }}>Sales Person</span>
            <span className="demo-tag" onClick={() => { setUserId('rm_north'); setPassword('password123'); }}>Regional Mgr</span>
          </div>
        </div>
      </div>
    </div>
  );
}
