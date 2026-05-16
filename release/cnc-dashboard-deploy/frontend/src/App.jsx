import { Routes, Route, Navigate } from "react-router-dom";
import OperatorDashboard from "./OperatorDashboard.jsx";
import ProgramadorDashboard from "./ProgramadorDashboard.jsx";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/operador" replace />} />
      <Route path="/operador" element={<OperatorDashboard />} />
      <Route path="/operador/:cncId" element={<OperatorDashboard />} />

      <Route path="/programador" element={<ProgramadorDashboard />} />

      {/* ✅ Visual (mesmo painel, readonly por querystring) */}
      <Route path="/visual" element={<ProgramadorDashboard />} />
    </Routes>
  );
}