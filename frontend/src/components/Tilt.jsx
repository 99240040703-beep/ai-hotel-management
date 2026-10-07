import { useCallback, useRef } from "react";

/**
 * Pointer-driven 3D tilt.
 *
 * Why the rotation lives on a child, not on the hovered element:
 * `perspective` is ignored on the element that also carries the
 * `transform`. So the scene owns the perspective and the card owns the
 * rotation - which is why this returns a wrapper component rather than
 * just a hook you apply yourself.
 *
 * Everything is written to CSS custom properties and applied through the
 * stylesheet, so the browser composites a transform rather than
 * re-laying out on every pointer move. No per-frame React state: at 60fps
 * a `setState` per pointer event would re-render the whole subtree.
 *
 * Disabled for touch (there is no hover on a phone, and the cost is not
 * worth it) and for anyone who asked for reduced motion.
 */
export function Tilt({
  children,
  max = 7,
  lift = -6,
  className = "",
  as: Tag = "div",
  ...rest
}) {
  const cardRef = useRef(null);
  const frame = useRef(0);

  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  const finePointer =
    typeof window !== "undefined" &&
    window.matchMedia?.("(hover: hover) and (pointer: fine)").matches;

  const write = useCallback(
    (rx, ry, ty) => {
      const node = cardRef.current;

      if (!node) return;

      node.style.setProperty("--rx", `${rx}deg`);
      node.style.setProperty("--ry", `${ry}deg`);
      node.style.setProperty("--ty", `${ty}px`);
    },
    [],
  );

  const handleMove = useCallback(
    (event) => {
      if (reduced || !finePointer) return;

      const node = cardRef.current;

      if (!node) return;

      const rect = node.getBoundingClientRect();

      // Normalised position across the card, -0.5 to 0.5.
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;

      // Coalesced into one write per frame. Without this, a fast mouse
      // queues a style write per pointer event and the main thread
      // spends its budget on layout instead of paint.
      if (frame.current) return;

      frame.current = requestAnimationFrame(() => {
        frame.current = 0;

        write(-y * max * 2, x * max * 2, lift);
      });
    },
    [max, lift, reduced, finePointer, write],
  );

  const handleLeave = useCallback(() => {
    if (frame.current) {
      cancelAnimationFrame(frame.current);
      frame.current = 0;
    }

    write(0, 0, 0);
  }, [write]);

  return (
    <div className={`tilt-scene ${className}`} {...rest}>
      <Tag
        ref={cardRef}
        className="tilt-card"
        onMouseMove={handleMove}
        onMouseLeave={handleLeave}
      >
        {children}
      </Tag>
    </div>
  );
}

export default Tilt;
