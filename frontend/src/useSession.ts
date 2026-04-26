import { useEffect, useRef, useState } from "react";
import { WS_URL } from "./config";
import type { WsMessage } from "./api";

export interface SessionLine {
  index: number;
  role: string;
  text: string;
  audio_url?: string;
}

export interface SessionState {
  status: string;
  language?: string;
  dilemma?: string;
  error?: string;
  lines: SessionLine[];
  verdict?: { text: string; audio_url?: string };
  activeRole?: string;
}

const initial: SessionState = { status: "idle", lines: [] };

export function useSession(audioOutBase: string) {
  const [state, setState] = useState<SessionState>(initial);
  const socketRef = useRef<WebSocket | null>(null);

  const s3ToUrl = (key?: string) =>
    key && audioOutBase ? `${audioOutBase.replace(/\/$/, "")}/${key}` : undefined;

  const reset = () => setState(initial);

  const connect = (sessionId: string) => {
    if (socketRef.current) socketRef.current.close();
    setState({ ...initial, status: "connecting" });

    const ws = new WebSocket(WS_URL);
    socketRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ action: "watch", session_id: sessionId }));
      setState((s) => ({ ...s, status: "waiting" }));
    };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data) as WsMessage;
      setState((prev) => {
        if (msg.type === "status") {
          return {
            ...prev,
            status: msg.status,
            language: msg.language ?? prev.language,
            dilemma: msg.dilemma ?? prev.dilemma,
            error: msg.error,
          };
        }
        if (msg.type === "line") {
          return {
            ...prev,
            lines: [
              ...prev.lines,
              {
                index: msg.index,
                role: msg.role,
                text: msg.text,
                audio_url: s3ToUrl(msg.audio_s3_key),
              },
            ],
            activeRole: msg.role,
          };
        }
        if (msg.type === "verdict") {
          return {
            ...prev,
            verdict: { text: msg.text, audio_url: s3ToUrl(msg.audio_s3_key) },
            activeRole: undefined,
          };
        }
        return prev;
      });
    };
    ws.onerror = () => setState((s) => ({ ...s, status: "failed", error: "websocket error" }));
    ws.onclose = () => socketRef.current === ws && (socketRef.current = null);
  };

  useEffect(() => () => socketRef.current?.close(), []);

  return { state, connect, reset };
}
