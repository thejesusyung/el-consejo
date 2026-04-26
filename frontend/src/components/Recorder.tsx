import { useRecorder } from "../useRecorder";

interface Props {
  onRecorded: (blob: Blob) => void | Promise<void>;
  disabled?: boolean;
}

export function Recorder({ onRecorded, disabled }: Props) {
  const { state, start, stop, finish } = useRecorder();

  const click = async () => {
    if (state === "idle") return start();
    if (state === "recording") {
      const blob = await stop();
      finish();
      await onRecorded(blob);
    }
  };

  const label =
    state === "idle" ? "Grabar un problema"
    : state === "recording" ? "Parar y enviar"
    : "Procesando…";

  return (
    <button
      className={`record-btn record-${state}`}
      onClick={click}
      disabled={disabled || state === "processing"}
    >
      <span className="record-dot" />
      {label}
    </button>
  );
}
