import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import Navbar from './components/Navbar';
import LoginPage from './pages/LoginPage';
import StoreDashboard from './pages/StoreDashboard';
import SalesPersonView from './pages/SalesPersonView';
import RegionalDashboard from './pages/RegionalDashboard';
import CreateStore from './pages/CreateStore';
import WarehouseDashboard from './pages/WarehouseDashboard';
import TransfersPage from './pages/TransfersPage';
import ShopPage from './pages/ShopPage';
import DemandForecastPage from './pages/DemandForecastPage';

function AppRoutes() {
  const { user, getDefaultRoute } = useAuth();

  return (
    <>
      <Navbar />
      <Routes>
        <Route path="/login" element={user ? <Navigate to={getDefaultRoute(user.role)} /> : <LoginPage />} />

        <Route path="/store-dashboard" element={
          <ProtectedRoute allowedRoles={['store_manager']}>
            <StoreDashboard />
          </ProtectedRoute>
        } />

        <Route path="/sales" element={
          <ProtectedRoute allowedRoles={['sales_person', 'store_manager']}>
            <SalesPersonView />
          </ProtectedRoute>
        } />

        <Route path="/transfers" element={
          <ProtectedRoute allowedRoles={['store_manager', 'regional_manager']}>
            <TransfersPage />
          </ProtectedRoute>
        } />

        <Route path="/regional" element={
          <ProtectedRoute allowedRoles={['regional_manager']}>
            <RegionalDashboard />
          </ProtectedRoute>
        } />

        <Route path="/create-store" element={
          <ProtectedRoute allowedRoles={['regional_manager']}>
            <CreateStore />
          </ProtectedRoute>
        } />

        <Route path="/warehouse" element={
          <ProtectedRoute allowedRoles={['regional_manager']}>
            <WarehouseDashboard />
          </ProtectedRoute>
        } />

        <Route path="/demand-forecast" element={
          <ProtectedRoute allowedRoles={['regional_manager']}>
            <DemandForecastPage />
          </ProtectedRoute>
        } />

        <Route path="/shop" element={<ShopPage />} />

        <Route path="/" element={user ? <Navigate to={getDefaultRoute(user.role)} /> : <Navigate to="/login" />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
