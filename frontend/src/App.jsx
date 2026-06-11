import { Routes, Route, Navigate } from "react-router-dom";
import OperatorDashboard from "./OperatorDashboard.jsx";
import ProgramadorDashboard from "./ProgramadorDashboard.jsx";
import "./FestaJunina.css";

const FESTA_FLAGS = [
  "red", "yellow", "blue", "green", "orange", "purple",
  "red", "blue", "yellow", "green", "orange", "purple",
  "blue", "red", "yellow", "green", "orange", "purple",
];

function FestaJuninaDecor() {
  return (
    <div className="festaDecor" aria-hidden="true">
      <div className="festaCord">
        {FESTA_FLAGS.map((color, index) => (
          <span
            key={`${color}-${index}`}
            className={`festaFlag festaFlag-${color}`}
            style={{ "--festa-delay": `${index * -0.08}s` }}
          />
        ))}
      </div>
      <div className="festaRibbon">ARRAIA CNC</div>
    </div>
  );
}

export default function App() {
  return (
    <div className="festaJuninaApp">
      <FestaJuninaDecor />
      <Routes>
        <Route path="/" element={<Navigate to="/operador" replace />} />
        <Route path="/operador" element={<OperatorDashboard />} />
        <Route path="/operador/:cncId" element={<OperatorDashboard />} />
        <Route path="/programador" element={<ProgramadorDashboard />} />
        <Route path="/facilitador" element={<ProgramadorDashboard mode="facilitador" />} />
        <Route path="/visual" element={<ProgramadorDashboard />} />
      </Routes>
    </div>
  );
}
