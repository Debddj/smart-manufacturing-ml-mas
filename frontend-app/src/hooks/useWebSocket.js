import { useState, useEffect, useRef, useCallback } from 'react';

export default function useWebSocket(storeId) {
  const [lastMessage, setLastMessage] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  const connect = useCallback(() => {
    const url = `ws://localhost:8000/ws/inventory${storeId ? `?store_id=${storeId}` : ''}`;
    const ws = new WebSocket(url);

    ws.onopen = () => {
      setIsConnected(true);
      console.log('[WS] Connected to inventory updates');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setLastMessage(data);
      } catch (e) {
        console.warn('[WS] Non-JSON message:', event.data);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      console.log('[WS] Disconnected, reconnecting in 3s...');
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, [storeId]);

  useEffect(() => {
    connect();
    // Keep-alive ping every 30s
    const ping = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping');
      }
    }, 30000);

    return () => {
      clearInterval(ping);
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { lastMessage, isConnected };
}
