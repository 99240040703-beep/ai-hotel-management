import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Stylesheet order is deliberate:
//
//   index.css    the browser reset, first so nothing is fought over
//   theme.css   tokens and primitives, before anything that uses them
//   App.css     the existing portal styles every component already relies on
//   premium.css the public site's surfaces
//   portal.css  the authenticated surfaces, last so it wins
//
// portal.css is last because it is the layer that replaces App.css's
// look with the premium one. Moving it earlier would let App.css win.
import "./index.css";
import "./theme.css";
import "./App.css";
import "./premium.css";
import "./portal.css";

import App from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);