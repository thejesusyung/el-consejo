import { useCallback, useRef, useState } from "react";

export type RecorderState = "idle" | "recording" | "processing";

export function useRecorder() {
  const [state, setState] = useState<RecorderState>("idle");
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const resolveRef = useRef<((b: Blob) => void) | null>(null);

  const start = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mr = new MediaRecorder(stream, { mimeType: "audio/webm" });
    chunksRef.current = [];
    mr.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
    mr.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      resolveRef.current?.(blob);
    };
    mr.start();
    mediaRef.current = mr;
    setState("recording");
  }, []);

  const stop = useCallback((): Promise<Blob> => {
    return new Promise((resolve) => {
      resolveRef.current = resolve;
      mediaRef.current?.stop();
      setState("processing");
    });
  }, []);

  const finish = useCallback(() => setState("idle"), []);

  return { state, start, stop, finish };
}
