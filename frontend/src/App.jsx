import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import OperatorDashboard from "./OperatorDashboard.jsx";
import ProgramadorDashboard from "./ProgramadorDashboard.jsx";
import AlmoxarifadoChatPage from "./AlmoxarifadoChatPage.jsx";
import AlmoxarifadoPage from "./AlmoxarifadoPage.jsx";
import AlmoxarifadoTvPage from "./AlmoxarifadoTvPage.jsx";
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
  const location = useLocation();
  const hideDecor = location.pathname === "/almoxarifado-tv";

  return (
    <div className="festaJuninaApp">
      {!hideDecor && <FestaJuninaDecor />}
      <Routes>
        <Route path="/" element={<Navigate to="/operador" replace />} />
        <Route path="/operador" element={<OperatorDashboard />} />
        <Route path="/operador/:cncId" element={<OperatorDashboard />} />
        <Route path="/programador" element={<ProgramadorDashboard />} />
        <Route path="/facilitador" element={<ProgramadorDashboard mode="facilitador" />} />
        <Route path="/visual" element={<ProgramadorDashboard />} />
        <Route path="/almoxarifado" element={<AlmoxarifadoPage />} />
        <Route path="/almoxarifado-tv" element={<AlmoxarifadoTvPage />} />
        <Route path="/almoxarifado-chat" element={<AlmoxarifadoChatPage />} />
        <Route path="/almoxarifado-chat/:solicitacaoId" element={<AlmoxarifadoChatPage />} />
      </Routes>
    </div>
  );
}
