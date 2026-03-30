import { useCallback, useEffect, useRef, useState } from "react";

type ConnectionStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "error";

const HEARTBEAT_INTERVAL_MS = 15000;
const MAX_RECONNECT_DELAY_MS = 30000;

export function useWebSocket(onMessage?: (data: any) => void) {
  const [isConnected, setIsConnected] = useState(false);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("idle");
  const [lastMessage, setLastMessage] = useState<any>(null);
  const [lastMessageAt, setLastMessageAt] = useState<number | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);

  const ws = useRef<WebSocket | null>(null);
  const retryCount = useRef(0);
  const reconnectTimer = useRef<number | null>(null);
  const heartbeatTimer = useRef<number | null>(null);
  const animationFrame = useRef<number | null>(null);
  const pendingMessage = useRef<any>(null);
  const shouldReconnect = useRef(true);
  const onMessageRef = useRef(onMessage);
  const connectRef = useRef<() => void>(() => undefined);
  const scheduleReconnectRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimer.current !== null) {
      window.clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
  }, []);

  const clearHeartbeatTimer = useCallback(() => {
    if (heartbeatTimer.current !== null) {
      window.clearInterval(heartbeatTimer.current);
      heartbeatTimer.current = null;
    }
  }, []);

  const clearAnimationFrame = useCallback(() => {
    if (animationFrame.current !== null) {
      window.cancelAnimationFrame(animationFrame.current);
      animationFrame.current = null;
    }
  }, []);

  const flushPendingMessage = useCallback(() => {
    animationFrame.current = null;
    if (pendingMessage.current === null) return;
    setLastMessage(pendingMessage.current);
    pendingMessage.current = null;
  }, []);

  const startHeartbeat = useCallback(() => {
    clearHeartbeatTimer();
    heartbeatTimer.current = window.setInterval(() => {
      const socket = ws.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) return;

      try {
        socket.send(
          JSON.stringify({
            type: "PING",
            ts: Date.now(),
          })
        );
      } catch (error) {
        console.warn("WS Heartbeat Error:", error);
        try {
          socket.close();
        } catch {
          // noop
        }
      }
    }, HEARTBEAT_INTERVAL_MS);
  }, [clearHeartbeatTimer]);

  const scheduleReconnect = useCallback(() => {
    if (!shouldReconnect.current) return;

    clearReconnectTimer();
    setIsConnected(false);
    setConnectionStatus("reconnecting");

    const baseDelay = Math.min(
      MAX_RECONNECT_DELAY_MS,
      1000 * Math.pow(2, retryCount.current)
    );
    const jitter = Math.floor(baseDelay * 0.2 * Math.random());
    const delay = baseDelay + jitter;

    reconnectTimer.current = window.setTimeout(() => {
      retryCount.current += 1;
      connectRef.current();
    }, delay);
  }, [clearReconnectTimer]);

  scheduleReconnectRef.current = scheduleReconnect;

  const connect = useCallback(() => {
    if (
      ws.current?.readyState === WebSocket.OPEN ||
      ws.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    const token = localStorage.getItem("token");
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/ws${
      token ? `?token=${token}` : ""
    }`;

    clearReconnectTimer();
    clearHeartbeatTimer();
    setConnectionStatus(retryCount.current > 0 ? "reconnecting" : "connecting");

    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      ws.current = socket;
      setIsConnected(true);
      setLastError(null);
      setConnectionStatus("connected");
      retryCount.current = 0;
      startHeartbeat();
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setLastMessageAt(Date.now());

        if (data?.type === "PONG") {
          return;
        }

        pendingMessage.current = data;
        if (animationFrame.current === null) {
          animationFrame.current = window.requestAnimationFrame(
            flushPendingMessage
          );
        }

        onMessageRef.current?.(data);
      } catch (e) {
        console.warn("WS Message Parse Error:", e);
      }
    };

    socket.onclose = () => {
      if (ws.current === socket) {
        ws.current = null;
      }
      clearHeartbeatTimer();
      setIsConnected(false);

      if (!shouldReconnect.current) {
        setConnectionStatus("idle");
        return;
      }

      scheduleReconnectRef.current();
    };

    socket.onerror = () => {
      setLastError("WebSocket connection error");
      setConnectionStatus("error");
      try {
        socket.close();
      } catch {
        // noop
      }
    };

    ws.current = socket;
  }, [
    clearHeartbeatTimer,
    clearReconnectTimer,
    flushPendingMessage,
    startHeartbeat,
  ]);

  connectRef.current = connect;

  const reconnect = useCallback(() => {
    retryCount.current = 0;
    clearReconnectTimer();

    const socket = ws.current;
    if (
      socket &&
      (socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING)
    ) {
      try {
        socket.close();
      } catch {
        // noop
      }
      return;
    }

    connectRef.current();
  }, [clearReconnectTimer]);

  useEffect(() => {
    shouldReconnect.current = true;
    connectRef.current();

    return () => {
      shouldReconnect.current = false;
      clearReconnectTimer();
      clearHeartbeatTimer();
      clearAnimationFrame();
      pendingMessage.current = null;

      const socket = ws.current;
      ws.current = null;
      if (
        socket &&
        (socket.readyState === WebSocket.OPEN ||
          socket.readyState === WebSocket.CONNECTING)
      ) {
        socket.close();
      }
    };
  }, [clearAnimationFrame, clearHeartbeatTimer, clearReconnectTimer]);

  return {
    isConnected,
    connectionStatus,
    lastMessage,
    lastMessageAt,
    lastError,
    reconnect,
  };
}