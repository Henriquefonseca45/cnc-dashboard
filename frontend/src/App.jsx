import { Routes, Route, Navigate } from "react-router-dom";
import OperatorDashboard from "./OperatorDashboard.jsx";
import ProgramadorDashboard from "./ProgramadorDashboard.jsx";
import AlmoxarifadoChatPage from "./AlmoxarifadoChatPage.jsx";
import AlmoxarifadoPage from "./AlmoxarifadoPage.jsx";
import AlmoxarifadoTvPage from "./AlmoxarifadoTvPage.jsx";
import AdminStatusApontamentos from "./AdminStatusApontamentos.jsx";
import AdminRoutesPortal from "./AdminRoutesPortal.jsx";
import AssistenteCncPage from "./AssistenteCncPage.jsx";
import MaintenanceTvPage from "./MaintenanceTvPage.jsx";

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<Navigate to="/operador" replace />} />
        <Route path="/operador" element={<OperatorDashboard />} />
        <Route path="/operador/:cncId" element={<OperatorDashboard />} />
        <Route path="/programador" element={<ProgramadorDashboard />} />
        <Route path="/facilitador" element={<ProgramadorDashboard mode="facilitador" />} />
        <Route path="/visual" element={<ProgramadorDashboard />} />
        <Route path="/almoxarifado" element={<AlmoxarifadoPage />} />
        <Route path="/almoxarifado-tv" element={<AlmoxarifadoTvPage />} />
        <Route path="/manutencao-tv" element={<MaintenanceTvPage />} />
        <Route path="/almoxarifado-chat" element={<AlmoxarifadoChatPage />} />
        <Route path="/almoxarifado-chat/:solicitacaoId" element={<AlmoxarifadoChatPage />} />
        <Route path="/assistente-cnc" element={<AssistenteCncPage />} />
        <Route path="/admin/rotas" element={<AdminRoutesPortal />} />
        <Route path="/admin/status-apontamentos" element={<AdminStatusApontamentos />} />
      </Routes>
    </>
  );
}
