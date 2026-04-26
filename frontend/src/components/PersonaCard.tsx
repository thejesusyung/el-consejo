import { ASSETS_URL } from "../config";

interface Props {
  personaKey: string;
  name: string;
  active: boolean;
}

export function PersonaCard({ personaKey, name, active }: Props) {
  const src = ASSETS_URL ? `${ASSETS_URL.replace(/\/$/, "")}/portraits/${personaKey}.png` : "";
  return (
    <div className={`persona-card${active ? " active" : ""}`}>
      {src ? (
        <img src={src} alt={name} />
      ) : (
        <div className="portrait-placeholder">{name[0]}</div>
      )}
      <div className="persona-name">{name}</div>
    </div>
  );
}
