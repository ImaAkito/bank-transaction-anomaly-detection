import { useEffect, useRef, useState } from "react";
import { getToken } from "./auth";
import type { LiveEvent } from "./types";

export type ConnectionState = "connecting" | "open" | "closed";

/** Подписка на поток результатов анализа (WebSocket) с автоматическим переподключением. */
export function useLiveFeed(onEvent: (event: LiveEvent) => void): ConnectionState {
  const [state, setState] = useState<ConnectionState>("connecting");
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let ping: number | undefined;
    let attempt = 0;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      setState("connecting");
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      const token = getToken();
      const query = token ? `?token=${encodeURIComponent(token)}` : "";
      socket = new WebSocket(`${scheme}://${window.location.host}/ws/transactions${query}`);
      socket.onopen = () => {
        attempt = 0;
        setState("open");
        ping = window.setInterval(() => socket?.readyState === WebSocket.OPEN && socket.send("ping"), 25000);
      };
      socket.onmessage = (message) => {
        try {
          handler.current(JSON.parse(message.data) as LiveEvent);
        } catch {
          /* некорректное сообщение игнорируется */
        }
      };
      socket.onclose = () => {
        window.clearInterval(ping);
        setState("closed");
        if (!disposed) {
          attempt += 1;
          timer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt, 15000));
        }
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      window.clearInterval(ping);
      socket?.close();
    };
  }, []);

  return state;
}
