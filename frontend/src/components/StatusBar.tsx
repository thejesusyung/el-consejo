const LABELS_ES: Record<string, string> = {
  idle: "Listo",
  connecting: "Conectando…",
  waiting: "Esperando a la familia…",
  ingest: "Subiendo…",
  transcribing: "Transcribiendo…",
  running: "La familia está discutiendo…",
  done: "Listo, escucha el veredicto",
  failed: "Algo salió mal",
};

interface Props {
  status: string;
}

export function StatusBar({ status }: Props) {
  const label = LABELS_ES[status] ?? status;
  return (
    <div className={`status-bar status-${status}`}>
      <span className="status-dot" />
      <span>{label}</span>
    </div>
  );
}
