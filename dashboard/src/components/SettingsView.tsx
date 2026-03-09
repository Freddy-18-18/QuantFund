import { Settings as SettingsIcon, Key, Database } from "lucide-react";

export function SettingsView() {
  return (
    <div className="settings-view">
      <div className="view-header">
        <h2><SettingsIcon size={24} style={{ marginRight: "0.5rem", verticalAlign: "middle" }} />Configuración</h2>
        <p>Administra API keys y preferencias</p>
      </div>

      <div className="card-grid">
        <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem" }}>
          <h3 style={{ marginBottom: "1rem" }}><Key size={18} style={{ marginRight: "0.5rem" }} />API Keys</h3>
          
          <div style={{ marginBottom: "1rem" }}>
            <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.5rem" }}>FRED API Key</label>
            <input type="password" placeholder="Ingresa tu FRED API key" style={{ width: "100%", padding: "0.625rem", background: "var(--bg-tertiary)", border: "1px solid var(--border-color)", borderRadius: "0.5rem", color: "var(--text-primary)" }} />
          </div>
          
          <div style={{ marginBottom: "1rem" }}>
            <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "0.5rem" }}>IMF API Key</label>
            <input type="password" placeholder="Ingresa tu API key del FMI" style={{ width: "100%", padding: "0.625rem", background: "var(--bg-tertiary)", border: "1px solid var(--border-color)", borderRadius: "0.5rem", color: "var(--text-primary)" }} />
          </div>
          
          <button style={{ padding: "0.625rem 1rem", background: "var(--accent-blue)", border: "none", borderRadius: "0.5rem", color: "white", cursor: "pointer" }}>
            Guardar Cambios
          </button>
        </div>

        <div style={{ background: "var(--bg-secondary)", borderRadius: "0.75rem", padding: "1.5rem" }}>
          <h3 style={{ marginBottom: "1rem" }}><Database size={18} style={{ marginRight: "0.5rem" }} />Datos</h3>
          
          <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem" }}>
            <button style={{ flex: 1, padding: "0.625rem", background: "var(--bg-tertiary)", border: "1px solid var(--border-color)", borderRadius: "0.5rem", color: "var(--text-primary)", cursor: "pointer" }}>
              Actualizar Datos
            </button>
            <button style={{ flex: 1, padding: "0.625rem", background: "var(--bg-tertiary)", border: "1px solid var(--border-color)", borderRadius: "0.5rem", color: "var(--text-primary)", cursor: "pointer" }}>
              Limpiar Cache
            </button>
          </div>
          
          <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>
            <div>Última actualización: {new Date().toLocaleString()}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default SettingsView;
