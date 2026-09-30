import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  // <StrictMode> 的双挂载会建立两条 WS 连接，调试期关闭
  <App />
);
