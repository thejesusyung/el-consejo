import { useState } from "react";
import { AUDIO_OUT_URL, PERSONAS } from "./config";
import { sendFeedback, submitText } from "./api";
import { useSession } from "./useSession";
import { PersonaCard } from "./components/PersonaCard";
import { StatusBar } from "./components/StatusBar";
import { Transcript } from "./components/Transcript";

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [voteSent, setVoteSent] = useState(false);
  const [textInput, setTextInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { state, connect, reset } = useSession(AUDIO_OUT_URL);

  const [submitError, setSubmitError] = useState<string | null>(null);

  const onTextSubmit = async () => {
    const text = textInput.trim();
    if (!text || submitting) return;
    try {
      setSubmitting(true);
      setSubmitError(null);
      setVoteSent(false);
      reset();
      const { session_id } = await submitText(text);
      setSessionId(session_id);
      connect(session_id);
      setTextInput("");
    } catch (e: any) {
      console.error(e);
      setSubmitError(e.message || "No se pudo conectar con el servidor.");
    } finally {
      setSubmitting(false);
    }
  };

  const vote = async (r: "up" | "down") => {
    if (!sessionId || voteSent) return;
    await sendFeedback(sessionId, r);
    setVoteSent(true);
  };

  const done = state.status === "done";

  return (
    <div className="app">
      <header>
        <h1>El Consejo</h1>
        <p className="subtitle">Cuéntale un problema a la familia.</p>
      </header>

      <section className="family">
        {PERSONAS.map((p, i) => (
          <PersonaCard
            key={p.key}
            personaKey={p.key}
            name={p.name}
            active={state.activeRole === p.key}
            index={i}
          />
        ))}
      </section>

      <section className="controls">


        <div className="text-input">
            <textarea
              placeholder="Cuéntame tu problema… (español o inglés)"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              rows={3}
              disabled={submitting || state.status === "running"}
            />
            <button
              onClick={onTextSubmit}
              disabled={!textInput.trim() || submitting || state.status === "running"}
            >
              {submitting ? "Enviando…" : "Consultar al Consejo"}
            </button>
          </div>
        <StatusBar status={state.status} />
      </section>

      {state.dilemma && (
        <section className="dilemma">
          <span className="dilemma-label">Tu problema:</span> {state.dilemma}
        </section>
      )}

      <section className="conversation">
        <Transcript lines={state.lines} />
      </section>

      {state.verdict && (
        <section className="verdict">
          <h2>Veredicto de la familia</h2>
          <p>{state.verdict.text}</p>
          {done && (
            <div className="feedback">
              {voteSent ? (
                <span>¡Gracias por el feedback!</span>
              ) : (
                <>
                  <button onClick={() => vote("up")}>👍 Me sirvió</button>
                  <button onClick={() => vote("down")}>👎 No me sirvió</button>
                </>
              )}
            </div>
          )}
        </section>
      )}

      {state.error && <div className="error">⚠️ {state.error}</div>}
      {submitError && <div className="error">⚠️ {submitError}</div>}
    </div>
  );
}
