import { useAuth } from '../context/AuthContext';
import { useNavigate, useLocation } from 'react-router-dom';
import './Navbar.css';

export default function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const navItems = [
    { path: '/shop', label: 'Shop' },
    { path: '/mas-ops', label: 'MAS Ops', external: true }
  ];
  
  if (user) {
    if (user.role === 'store_manager') {
      navItems.push({ path: '/store-dashboard', label: 'Dashboard' });
      navItems.push({ path: '/transfers', label: 'Transfers' });
    } else if (user.role === 'sales_person') {
      navItems.push({ path: '/sales', label: 'Sales' });
    } else if (user.role === 'regional_manager') {
      navItems.push({ path: '/regional', label: 'Dashboard' });
      navItems.push({ path: '/create-store', label: 'Create Store' });
      navItems.push({ path: '/warehouse', label: 'Warehouse' });
      navItems.push({ path: '/demand-forecast', label: 'Demand Forecast' });
    }
  }

  return (
    <nav className="navbar">
      <div className="navbar-brand" onClick={() => navigate('/')}>
        <span className="brand-icon">&#9881;</span>
        <span className="brand-text" style={{color: '#1E293B'}}>Supply Chain MAS</span>
      </div>
      <div className="navbar-links">
        {navItems.map((item) => (
          item.external ? (
            <a
              key={item.path}
              className="nav-link external"
              href={item.path}
              target="_blank"
              rel="noopener noreferrer"
            >
              {item.label}
            </a>
          ) : (
            <button
              key={item.path}
              className={`nav-link ${location.pathname === item.path ? 'active' : ''}`}
              onClick={() => navigate(item.path)}
            >
              {item.label}
            </button>
          )
        ))}
      </div>
      <div className="navbar-user">
        {user ? (
          <>
            <span className="user-role">
              {{ store_manager: 'Store Manager', sales_person: 'Sales Person', regional_manager: 'Regional Manager' }[user.role] || user.role}
            </span>
            <span className="user-name">{user.display_name}</span>
            <button className="logout-btn" onClick={() => { logout(); navigate('/login'); }}>
              Logout
            </button>
          </>
        ) : (
          <button className="logout-btn" onClick={() => navigate('/login')}>
            Login
          </button>
        )}
      </div>
    </nav>
  );
}
