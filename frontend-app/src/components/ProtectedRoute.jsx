import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function ProtectedRoute({ children, allowedRoles }) {
  const { user } = useAuth();

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#0f0f23', color: '#ff6b6b', fontFamily: 'Inter, sans-serif' }}>
        <div style={{ textAlign: 'center' }}>
          <h1 style={{ fontSize: '3rem', marginBottom: '1rem' }}>403</h1>
          <p style={{ fontSize: '1.2rem', color: '#8892b0' }}>Access Denied. Your role ({user.role}) does not have permission to view this page.</p>
        </div>
      </div>
    );
  }

  return children;
}
