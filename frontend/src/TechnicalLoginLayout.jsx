import { ShieldCheck } from "lucide-react";
import rvbLogo from "./assets/rvb-logo.png";
import cncReference from "./assets/cnc-login-reference.png";
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
          {/* Frame the original artwork without redrawing or stretching the CNC.
              The reference login card is entirely outside this viewport. */}
          <svg className="technicalLoginMachine" viewBox="775 45 880 850" focusable="false">
            <defs>
              <clipPath id="technical-login-reference-crop">
                <rect x="775" y="45" width="880" height="850" />
              </clipPath>
            </defs>
            <image href={cncReference} width="1672" height="941" clipPath="url(#technical-login-reference-crop)" />
          </svg>
        </div>
      </div>
      <div className="technicalLoginBottomline" aria-hidden="true"><span>RVB CNC DASHBOARD</span><span>ENGENHARIA EM CADA MOVIMENTO</span></div>
    </main>
  );
}
