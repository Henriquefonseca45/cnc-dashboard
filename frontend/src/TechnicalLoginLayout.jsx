import { ShieldCheck } from "lucide-react";
import rvbLogo from "./assets/rvb-logo.png";
import cncBlueprint from "./assets/cnc-login-blueprint.svg";
import "./TechnicalLoginLayout.css";

// Presentation only: authentication and form state remain in ProgramadorLogin.
export default function TechnicalLoginLayout({ children }) {
  return (
    <main className="technicalLoginPage">
      <div className="technicalLoginTopline" aria-hidden="true"><span>RVB / SISTEMAS INDUSTRIAIS</span><span>CNC · CONTROLE & PRECISÃO</span></div>
      <div className="technicalLoginComposition">
        <section className="technicalLoginPanel" aria-labelledby="technical-login-title">
          <div className="technicalLoginBrand">
            <div className="technicalLoginLogo"><img src={rvbLogo} alt="RVB — Isolantes para transformadores" /></div>
            <div className="technicalLoginProduct"><span>CNC</span><strong>DASHBOARD</strong></div>
          </div>
          <div className="technicalLoginRule" />
          <p className="technicalLoginEyebrow">ADMINISTRAÇÃO TÉCNICA</p>
          <h1 id="technical-login-title">Acesso administrativo</h1>
          <p className="technicalLoginDescription">Entre com suas credenciais para continuar.</p>
          {children}
          <footer className="technicalLoginRestricted"><ShieldCheck size={17} aria-hidden="true" /><span>Acesso restrito à equipe autorizada.</span></footer>
        </section>
        <div className="technicalLoginArtwork" aria-hidden="true">
          <div className="technicalLoginDrawingLabel"><span>01 / CNC ROUTER</span><small>VISTA ISOMÉTRICA · BLUEPRINT</small></div>
          <img className="technicalLoginMachine" src={cncBlueprint} alt="" draggable="false" />
          <div className="technicalLoginCoordinates"><span>G54 · ABS</span><span>X <b>245.128</b></span><span>Y <b>134.682</b></span><span>Z <b>098.573</b></span></div>
          <div className="technicalLoginCode">N010 G90 G54<br />N020 S18000 M03<br />N030 G01 F1200.000</div>
          <div className="technicalLoginDrawingFooter"><span>PROGRAMAÇÃO · MOVIMENTO · PRECISÃO</span><small>ILUSTRAÇÃO TÉCNICA</small></div>
        </div>
      </div>
      <div className="technicalLoginBottomline" aria-hidden="true"><span>RVB CNC DASHBOARD</span><span>ENGENHARIA EM CADA MOVIMENTO</span></div>
    </main>
  );
}
