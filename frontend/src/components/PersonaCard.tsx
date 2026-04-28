import { useState } from "react";
import { ASSETS_URL } from "../config";

interface Props {
  personaKey: string;
  name: string;
  active: boolean;
  index?: number;
}

export function PersonaCard({ personaKey, name, active, index = 0 }: Props) {
  const [error, setError] = useState(false);
  const baseUrl = ASSETS_URL ? ASSETS_URL.replace(/\/$/, "") : "";
  const src = `${baseUrl}/portraits/${personaKey}.png`;
  return (
    <div 
      className={`persona-card${active ? " active" : ""}`}
      style={{ animationDelay: `${index * 0.1}s` }}
    >
      {!error ? (
        <img src={src} alt={name} onError={() => setError(true)} />
      ) : (
        <div className="portrait-placeholder">{name[0]}</div>
      )}
      <div className="persona-name">{name}</div>
    </div>
  );
}
