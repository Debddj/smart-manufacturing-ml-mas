import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './ShopPage.css';

const DEMO_PRODUCTS = [
  {id:'RM-001',name:'Cold-Rolled Steel Coils',category:'Raw Materials',description:'High-strength HSLA steel coils, 1.5mm gauge. For stamping and roll-forming operations.',price:{amount:2840},sku:'CRSC-1500',lead:'5–7 days'},
  {id:'RM-002',name:'6061-T6 Aluminium Sheet',category:'Raw Materials',description:'Aerospace-grade aluminium alloy, 3mm thickness. Excellent machinability and corrosion resistance.',price:{amount:1250},sku:'AL61-T6',lead:'3–5 days'},
  {id:'RM-003',name:'Electrolytic Copper Wire',category:'Raw Materials',description:'99.9% pure copper conductor, 2.5mm AWG. Industrial grade for winding and cabling.',price:{amount:780},sku:'ECW-25',lead:'2–4 days'},
  {id:'RM-004',name:'Carbon Fiber Prepreg',category:'Raw Materials',description:'Unidirectional carbon fiber, 240 GSM. High modulus for structural composite applications.',price:{amount:4200},sku:'CFP-240',lead:'8–12 days'},
  {id:'RM-005',name:'Polyamide 66 Pellets (GF30)',category:'Raw Materials',description:'Glass-filled PA66 pellets, 30% GF. High heat and chemical resistance for injection moulding.',price:{amount:380},sku:'PA66-GF30',lead:'2–3 days'},
  {id:'RM-006',name:'Borosilicate Glass Tubes',category:'Raw Materials',description:'Precision borosilicate tubing, OD 25mm. Low thermal expansion, high purity.',price:{amount:290},sku:'BGT-25',lead:'6–9 days'},
  {id:'CP-001',name:'AC Servo Motor 2.0 kW',category:'Components',description:'Closed-loop AC servo, 2000W, IP65. Integrated encoder for precise CNC motion control.',price:{amount:1640},sku:'SRV-2K',lead:'5–8 days'},
  {id:'CP-002',name:'PLC Controller S7-1200',category:'Components',description:'Compact PLC, 14 DI/10 DO, PROFINET enabled. Industry 4.0 ready, TIA Portal programmable.',price:{amount:2180},sku:'PLC-S71200',lead:'7–10 days'},
  {id:'CP-003',name:'Inductive Proximity Sensor',category:'Components',description:'NPN NO, M18 housing, 8mm sensing range. Stainless steel face, IP67 rated.',price:{amount:95},sku:'IPS-M18',lead:'1–2 days'},
  {id:'CP-004',name:'4-Layer Industrial PCB',category:'Components',description:'FR4 substrate, 1oz copper, ENIG finish. Designed for high-frequency switching circuits.',price:{amount:220},sku:'PCB-4L',lead:'4–6 days'},
  {id:'CP-005',name:'Hydraulic Cylinder 50 kN',category:'Components',description:'Double-acting, 50kN force, 300mm stroke. Honed barrel, hard chrome rod, BSPP ports.',price:{amount:3100},sku:'HYD-50K',lead:'10–14 days'},
  {id:'CP-006',name:'Angular Contact Bearing 7208',category:'Components',description:'40×80×18mm angular contact ball bearing. Grease lubricated, C3 clearance, steel cage.',price:{amount:145},sku:'ACB-7208',lead:'2–3 days'},
  {id:'CP-007',name:'Pt100 RTD Temperature Probe',category:'Components',description:'Class A resistance temperature detector, 6mm dia, 150mm insertion. −50 to +400 °C.',price:{amount:185},sku:'RTD-PT100',lead:'3–5 days'},
  {id:'CP-008',name:'24 VDC Power Supply 10 A',category:'Components',description:'DIN-rail mount SMPS, 24VDC / 10A output. Wide input 85–264 VAC, CE/UL listed.',price:{amount:165},sku:'PSU-24V10',lead:'2–3 days'},
  {id:'AS-001',name:'6-Axis Robotic Arm Module',category:'Assemblies',description:'Industrial robot, 6kg payload, 900mm reach. Pre-calibrated with teach pendant and safety I/O.',price:{amount:28500},sku:'ARM-6AX',lead:'15–21 days'},
  {id:'AS-002',name:'CNC Spindle Unit 7.5 kW',category:'Assemblies',description:'High-speed CNC spindle, 7.5kW, 24000 RPM. HSK-A63 tooling interface, liquid cooled.',price:{amount:9800},sku:'SPD-7K5',lead:'12–16 days'},
  {id:'AS-003',name:'Modular Conveyor Belt — 3 m',category:'Assemblies',description:'Variable-speed belt conveyor, 80kg capacity, plug-and-play. SEW inverter drive included.',price:{amount:6400},sku:'CVR-3M',lead:'10–14 days'},
  {id:'AS-004',name:'Automated MIG Welding Head',category:'Assemblies',description:'Torch assembly with wire feeder, gas solenoid and automated nozzle cleaning station.',price:{amount:4750},sku:'WLD-MIG',lead:'8–12 days'},
  {id:'AS-005',name:'Machine Vision Inspection Unit',category:'Assemblies',description:'12MP colour camera, telecentric lens, integrated LED ring light and onboard defect-detection PC.',price:{amount:11200},sku:'VIS-12M',lead:'14–18 days'},
  {id:'CN-001',name:'Carbide Turning Inserts ×10',category:'Consumables',description:'CNMG 120408 grade, PVD TiAlN coated. For steel and stainless steels at medium to high feeds.',price:{amount:68},sku:'INS-CNMG',lead:'1–2 days'},
  {id:'CN-002',name:'Hydraulic Oil ISO VG 46 — 20L',category:'Consumables',description:'Anti-wear mineral hydraulic oil, 20-litre drum. Anti-foam, rust inhibited, zinc-based.',price:{amount:115},sku:'LUB-VG46',lead:'1–2 days'},
  {id:'CN-003',name:'MIG Wire ER70S-6 — 15 kg',category:'Consumables',description:'AWS ER70S-6 copper-coated mild steel wire, 0.9mm dia, 15kg spool. Excellent weld bead finish.',price:{amount:92},sku:'WIR-70S6',lead:'1–2 days'},
  {id:'CN-004',name:'H14 HEPA Filter Set ×4',category:'Consumables',description:'HEPA filter panels for CNC enclosures, 610×610mm, H14 class. Set of 4.',price:{amount:145},sku:'FLT-HEPA',lead:'3–5 days'},
  {id:'CN-005',name:'Zirconia Flap Discs ×25',category:'Consumables',description:'125mm, 40 grit zirconia alumina flap discs. Heavy stock removal on weld seams and steel.',price:{amount:48},sku:'GRD-ZA40',lead:'1–2 days'},
];

const STAGES = [
  {id:'received',icon:'📥',label:'Order Received'},
  {id:'inventory_check',icon:'🔍',label:'Inventory Check'},
  {id:'fulfillment',icon:'📦',label:'Fulfillment'},
  {id:'warehouse_transfer',icon:'🔄',label:'Warehouse Transfer'},
  {id:'procurement',icon:'🛒',label:'Procurement'},
  {id:'restock',icon:'📨',label:'Supplier Restock'},
  {id:'logistics',icon:'🚚',label:'Logistics'},
  {id:'last_mile',icon:'🏠',label:'Last Mile'},
  {id:'delivered',icon:'✅',label:'Delivered'},
];

export default function ShopPage() {
  // Auth context — must be first so all functions below can access user
  const { user } = useAuth();

  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [activeCategory, setActiveCategory] = useState(null);
  const [cart, setCart] = useState({});
  const [toastMsg, setToastMsg] = useState('');
  
  // Warehouse transfer state
  const [logTransfer, setLogTransfer] = useState(false);
  const [transferFrom, setTransferFrom] = useState('Warehouse A');
  const [transferTo, setTransferTo] = useState('Warehouse B');
  const [transferLoading, setTransferLoading] = useState(false);
  const [transferResult, setTransferResult] = useState(null);

  // Order state
  const [orderProcessing, setOrderProcessing] = useState(false);
  const [orderId, setOrderId] = useState(null);
  const [activeStage, setActiveStage] = useState(null);
  const [stageDetails, setStageDetails] = useState({});
  const [orderDone, setOrderDone] = useState(false);

  const loadProducts = async () => {
    let prods = [...DEMO_PRODUCTS];
    // If a salesperson is logged in, load REAL inventory from their store's DB
    if (user?.store_id) {
      try {
        const res = await api.get(`/api/stores/${user.store_id}/inventory`);
        // res.data is [{product_id, product_sku, product_name, quantity, ...}]
        const invMap = {};
        res.data.forEach(row => { invMap[row.product_sku] = row.quantity; });
        prods = prods.map(p => ({
          ...p,
          inventory: { available: invMap[p.sku] ?? 100 }
        }));
      } catch {
        prods = prods.map(p => ({ ...p, inventory: { available: 100 } }));
      }
    } else {
      // Fallback: try legacy /api/inventory endpoint
      try {
        const res = await api.get('/api/inventory');
        const invData = res.data;
        prods = prods.map(p => ({
          ...p,
          inventory: invData[p.sku] ? { available: invData[p.sku].inventory } : { available: 100 }
        }));
      } catch {
        prods = prods.map(p => ({ ...p, inventory: { available: 100 } }));
      }
    }
    setProducts(prods);
    const cats = [...new Set(prods.map(p => p.category))];
    setCategories(cats);
  };

  useEffect(() => {
    setTimeout(loadProducts, 0);
    const interval = setInterval(loadProducts, 30000);
    return () => clearInterval(interval);
  }, []);

  const addToCart = (productSku) => {
    // Cart key is the product's real SKU (e.g. "ECW-25") so it matches the DB
    setCart(prev => ({ ...prev, [productSku]: (prev[productSku] || 0) + 1 }));
    const p = products.find(p => p.sku === productSku);
    showToast(`Added ${p?.name || productSku} to cart`);
  };

  const changeQty = (sku, delta) => {
    setCart(prev => {
      const newQty = (prev[sku] || 0) + delta;
      if (newQty <= 0) {
        const newCart = {...prev};
        delete newCart[sku];
        return newCart;
      }
      return { ...prev, [sku]: newQty };
    });
  };

  const removeItem = (sku) => {
    setCart(prev => {
      const newCart = {...prev};
      delete newCart[sku];
      return newCart;
    });
  };

  const showToast = (msg) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(''), 3200);
  };

  const handleWarehouseTransferLog = async () => {
    if (!logTransfer) return;
    setTransferLoading(true);
    setTransferResult(null);
    try {
      const res = await api.post('/api/v1/warehouse_transfer', {
        from_warehouse: transferFrom,
        to_warehouse: transferTo
      });
      setTransferResult({ type: 'success', text: `✅ Logged: ${res.data.from} → ${res.data.to} | ${res.data.units} units | ID: ${res.data.order_id}` });
      showToast('Transfer logged to warehouse_log.csv ✓');
    } catch (e) {
      const err = e.response?.data?.error || e.message;
      setTransferResult({ type: 'error', text: `⚠️ ${err}` });
      showToast('Transfer logging failed: ' + err);
    } finally {
      setTransferLoading(false);
    }
  };

  const selectedStoreId = user?.store_id || null;

  const placeOrder = async () => {
    if (Object.keys(cart).length === 0) return;
    setOrderProcessing(true);
    
    // cart keys are real SKUs (e.g. "ECW-25") — directly usable by the backend
    const cartItems = Object.entries(cart).map(([sku, qty]) => ({sku, qty}));
    const month = new Date().getMonth() + 1;
    const environmentContext = month <= 7 ? 'Summer' : 'Winter';
    const customerId = 'CUST-' + crypto.randomUUID().substr(0, 6).toUpperCase();

    try {
      const res = await api.post('/api/v1/trigger_order', {
        cart_items: cartItems,
        environment_context: environmentContext,
        customer_id: customerId,
        store_id: selectedStoreId,   // ← tells backend which store to deduct
      });
      const oId = res.data.order_id;
      setOrderId(oId);
      setOrderDone(false);
      setActiveStage('received');
      showToast('📨 Procurement + fulfillment emails will be sent on completion.');

      // ── Immediate inventory update from deduction response ─────────────────
      // The backend returns which items were deducted and their new quantities.
      // Update the product cards right away so the user sees stock drop live.
      const updates = res.data.inventory_updates || [];
      if (updates.length > 0) {
        setProducts(prev => prev.map(p => {
          const hit = updates.find(u => u.sku === p.sku);
          if (hit) {
            return { ...p, inventory: { available: Math.max(0, hit.new_qty) } };
          }
          return p;
        }));
        const deductedNames = updates.map(u => u.product_name).join(', ');
        showToast(`📉 Inventory deducted at Store ${selectedStoreId}: ${deductedNames}`);
      }
      // ──────────────────────────────────────────────────────────────────────

      const evtSource = new EventSource(`/api/stream/${oId}`);
      evtSource.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        if (ev.type === 'order_status') {
          setActiveStage(ev.stage);
          setStageDetails(prev => ({ ...prev, [ev.stage]: ev.detail || '' }));
          if (ev.status === 'DELIVERED') {
            setOrderDone(true);
            setOrderProcessing(false);
            setCart({});
            showToast('✅ Order delivered! Check your email for invoice + procurement contract.');
            evtSource.close();
            // Refresh product inventory after delivery to reflect latest DB state
            setTimeout(loadProducts, 1500);
          }
        }
      };
    } catch (e) {
      setOrderProcessing(false);
      alert('Order failed: ' + e.message);
    }
  };

  const filteredProducts = activeCategory ? products.filter(p => p.category === activeCategory) : products;
  
  let cartTotal = 0;
  let cartUnits = 0;
  Object.keys(cart).forEach(sku => {
    const p = products.find(p => p.sku === sku);
    const price = p?.price?.amount || 0;
    cartTotal += price * cart[sku];
    cartUnits += cart[sku];
  });

  return (
    <div className="shop-container">
      <div className="shop-products-panel">
        <div className="shop-panel-title">Product Catalogue</div>
        <div className="shop-category-filter">
          <button 
            className={`shop-cat-btn ${!activeCategory ? 'active' : ''}`}
            onClick={() => setActiveCategory(null)}
          >All</button>
          {categories.map(cat => (
            <button 
              key={cat}
              className={`shop-cat-btn ${activeCategory === cat ? 'active' : ''}`}
              onClick={() => setActiveCategory(cat)}
            >{cat}</button>
          ))}
        </div>
        
        <div className="shop-product-grid">
          {products.length === 0 && <div style={{color: 'var(--shop-muted)', fontSize: '.85rem', gridColumn: '1/-1'}}>Loading products…</div>}
          {filteredProducts.map(p => {
            const inv = p.inventory?.available || 0;
            const base = 10;
            const status = inv > base * 3 ? 'in_stock' : inv > 0 ? 'low_stock' : 'out_of_stock';
            const scls = status === 'in_stock' ? 'shop-stock-in' : status === 'low_stock' ? 'shop-stock-low' : 'shop-stock-out';
            const slbl = status === 'in_stock' ? 'In Stock' : status === 'low_stock' ? 'Low Stock' : 'Out of Stock';
            const inCart = cart[p.sku] || 0;

            return (
              <div key={p.id} className="shop-product-card">
                <div className="shop-pc-header">
                  <div className="shop-product-cat">{p.category}</div>
                  <div className="shop-product-sku">#{p.sku || p.id}</div>
                </div>
                <div className="shop-product-abbr">{(p.sku || p.id).split('-')[0]}-{(p.sku || p.id).split('-')[1] || ''}</div>
                <div className="shop-product-name">{p.name}</div>
                <div className="shop-product-desc">{p.description}</div>
                <div className="shop-product-meta">
                  <div className="shop-product-price">₹{p.price.amount.toLocaleString('en-IN', {minimumFractionDigits: 2})}</div>
                  <div className={`shop-product-stock ${scls}`}>{slbl}</div>
                </div>
                <div className="shop-product-lead">Lead time: {p.lead}</div>
                <button 
                  className={`shop-add-btn ${inCart > 0 ? 'in-cart' : ''}`}
                  onClick={() => addToCart(p.sku)}
                >
                  {inCart > 0 ? `In Cart — ${inCart} unit${inCart > 1 ? 's' : ''}` : 'Add to Cart'}
                </button>
              </div>
            );
          })}
        </div>
      </div>

      <div className="shop-cart-panel" id="cartPanel">
        <div className="shop-cart-header">
          <div className="shop-panel-title">Shopping Cart</div>
        </div>
        
        {Object.keys(cart).length === 0 ? (
          <div className="shop-cart-empty">
            <div style={{fontSize: '3rem', opacity: 0.1, marginBottom: '1rem'}}>🛒</div>
            <div style={{fontSize: '.9rem', fontWeight: 600, color: 'var(--shop-ink)', marginBottom: '.4rem'}}>Your cart is empty</div>
            <div style={{fontSize: '.72rem', color: 'var(--shop-muted2)'}}>Add products to get started</div>
          </div>
        ) : (
          <>
            <div className="shop-cart-items">
              {Object.keys(cart).map(sku => {
                const p = products.find(p => p.sku === sku) || {};
                const qty = cart[sku];
                const price = p.price?.amount || 0;
                return (
                  <div key={sku} className="shop-cart-item">
                    <div className="shop-cart-item-header">
                      <div className="shop-cart-item-info">
                        <div className="shop-cart-item-name">{p.name || sku}</div>
                        <div className="shop-cart-item-sku">#{p.sku || sku}</div>
                      </div>
                      <button className="shop-remove-btn" onClick={() => removeItem(sku)}>Remove</button>
                    </div>
                    <div className="shop-cart-item-footer">
                      <div className="shop-cart-item-price">₹{(price * qty).toLocaleString('en-IN', {minimumFractionDigits: 2})}</div>
                      <div className="shop-cart-qty">
                        <button className="shop-qty-btn" onClick={() => changeQty(sku, -1)}>−</button>
                        <div className="shop-qty-val">{qty}</div>
                        <button className="shop-qty-btn" onClick={() => changeQty(sku, 1)}>+</button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="shop-cart-footer">
              <div className="shop-summary-section">
                <div className="shop-summary-row">
                  <span className="shop-summary-row-label">Items in cart</span>
                  <span className="shop-summary-row-value">{Object.keys(cart).length}</span>
                </div>
                <div className="shop-summary-row">
                  <span className="shop-summary-row-label">Total units</span>
                  <span className="shop-summary-row-value">{cartUnits}</span>
                </div>
                <div className="shop-summary-total">
                  <span>Total Amount</span>
                  <span>₹{cartTotal.toLocaleString('en-IN', {minimumFractionDigits: 2})}</span>
                </div>
              </div>

              {/* Warehouse Transfer Control */}
              <div className="shop-wh-section">
                <div className="shop-wh-section-title">Warehouse Transfer</div>
                <label className="shop-checkbox-row" htmlFor="wh-transfer-check">
                  <input 
                    type="checkbox" 
                    id="wh-transfer-check" 
                    checked={logTransfer} 
                    onChange={(e) => setLogTransfer(e.target.checked)}
                  />
                  <span>Log Transfer from Warehouse</span>
                </label>

                {logTransfer && (
                  <div className="shop-transfer-controls visible">
                    <div className="shop-wh-row" style={{marginTop: '.6rem'}}>
                      <div>
                        <label className="shop-wh-lbl">From</label>
                        <select className="shop-wh-select" value={transferFrom} onChange={(e) => {
                          setTransferFrom(e.target.value);
                          if (transferTo === e.target.value) setTransferTo(e.target.value === 'Warehouse A' ? 'Warehouse B' : 'Warehouse A');
                        }}>
                          <option value="Warehouse A">Warehouse A</option>
                          <option value="Warehouse B">Warehouse B</option>
                        </select>
                      </div>
                      <div>
                        <label className="shop-wh-lbl">To</label>
                        <select className="shop-wh-select" value={transferTo} onChange={(e) => setTransferTo(e.target.value)}>
                          {['Warehouse A', 'Warehouse B'].filter(w => w !== transferFrom).map(w => (
                            <option key={w} value={w}>{w}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <button 
                      className="shop-xfer-log-btn" 
                      onClick={handleWarehouseTransferLog}
                      disabled={transferLoading}
                    >
                      {transferLoading ? '⏳ Logging…' : '🔄 Log Transfer to CSV'}
                    </button>
                    {transferResult && (
                      <div className={`shop-transfer-result ${transferResult.type}`}>
                        {transferResult.text}
                      </div>
                    )}
                  </div>
                )}
              </div>


              <button 
                className="shop-checkout-btn" 
                onClick={placeOrder}
                disabled={orderProcessing}
              >
                {orderProcessing ? 'Agents Working…' : orderDone ? 'Order Delivered! ✅' : 'Proceed to Checkout'}
              </button>

              {orderId && (
                <div className="shop-status-box">
                  <div className="shop-status-order-id">Order: {orderId} | Items: {Object.keys(cart).length}</div>
                  <div className="shop-status-title">Order Journey</div>
                  <div className="shop-timeline">
                    {STAGES.map((s, idx) => {
                      const activeIdx = STAGES.findIndex(st => st.id === activeStage);
                      const isDone = activeIdx > idx || orderDone;
                      const isActive = activeIdx === idx && !orderDone;
                      return (
                        <div key={s.id} className={`shop-tl-step ${isActive ? 'active' : ''} ${isDone ? 'done' : ''}`}>
                          <div className="shop-tl-dot">{isDone ? '✓' : ''}</div>
                          <div>
                            <div>{s.icon} {s.label}</div>
                            <div className="shop-tl-detail">{stageDetails[s.id] || ''}</div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
      
      {toastMsg && (
        <div className="toast show" style={{
          position:'fixed', bottom:'2rem', right:'2rem', padding:'.65rem 1.1rem', 
          background:'var(--shop-ink)', borderRadius:'8px', color:'var(--shop-surface2)', 
          fontSize:'.78rem', fontWeight:600, zIndex:999, maxWidth:'320px',
          animation: 'shopSlideIn .3s ease'
        }}>
          {toastMsg}
        </div>
      )}
    </div>
  );
}
