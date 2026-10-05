// The live channel's state as a small dot on the corner of the user chip's
// avatar; its label shows on hover or keyboard focus.
import { useState } from "react";
import { useConnectionStore } from "../store/connection";
import { indicatorFor } from "./connectionIndicator";

export function ConnectionDot() {
  const status = useConnectionStore((s) => s.status);
  const [hovered, setHovered] = useState(false);
  const { tone, label } = indicatorFor(status);
  return (
    <div
      role="status"
      aria-label={label}
      tabIndex={0}
      className="acme-connection"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
    >
      <span className="acme-dot acme-connection-dot" data-tone={tone} />
      {hovered ? (
        <span role="tooltip" className="acme-tooltip acme-connection-tip">
          {label}
        </span>
      ) : null}
    </div>
  );
}
