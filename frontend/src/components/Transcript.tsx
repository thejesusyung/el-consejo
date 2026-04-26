import type { SessionLine } from "../useSession";
import { PERSONAS } from "../config";

const LABEL: Record<string, string> = {
  moderator_open: "Moderador",
  moderator_close: "Moderador",
  ...Object.fromEntries(PERSONAS.map((p) => [p.key, p.name])),
};

interface Props {
  lines: SessionLine[];
}

export function Transcript({ lines }: Props) {
  if (lines.length === 0) {
    return <div className="transcript-empty">La familia se está reuniendo…</div>;
  }
  return (
    <div className="transcript">
      {lines.map((ln) => (
        <div key={ln.index} className={`line line-${ln.role}`}>
          <div className="line-who">{LABEL[ln.role] ?? ln.role}</div>
          <div className="line-text">{ln.text}</div>
          {ln.audio_url && (
            <audio controls preload="none" src={ln.audio_url} className="line-audio" />
          )}
        </div>
      ))}
    </div>
  );
}
