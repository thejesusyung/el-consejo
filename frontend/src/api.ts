import { API_URL } from "./config";

export type WsMessage =
  | { type: "status"; status: string; language?: string; dilemma?: string; error?: string }
  | { type: "line"; index: number; role: string; text: string; audio_s3_key?: string }
  | { type: "verdict"; text: string; audio_s3_key?: string };

export async function presign(ext = "webm"): Promise<{
  session_id: string;
  put_url: string;
  content_type: string;
}> {
  const r = await fetch(`${API_URL}/presign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ext }),
  });
  if (!r.ok) throw new Error(`presign failed: ${r.status}`);
  return r.json();
}

export async function uploadAudio(
  putUrl: string,
  blob: Blob,
  contentType: string,
): Promise<void> {
  const r = await fetch(putUrl, {
    method: "PUT",
    headers: { "Content-Type": contentType },
    body: blob,
  });
  if (!r.ok) throw new Error(`upload failed: ${r.status}`);
}

export async function submitText(text: string, lang: "es" | "en" = "es"): Promise<{ session_id: string }> {
  const r = await fetch(`${API_URL}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, lang }),
  });
  if (!r.ok) throw new Error(`session failed: ${r.status}`);
  return r.json();
}

export async function sendFeedback(sessionId: string, rating: "up" | "down", comment = ""): Promise<void> {
  await fetch(`${API_URL}/feedback/${sessionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating, comment }),
  });
}
