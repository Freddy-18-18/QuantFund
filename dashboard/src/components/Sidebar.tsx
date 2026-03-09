import { 
  LayoutDashboard, 
  LineChart, 
  Target, 
  Building2, 
  Newspaper, 
  Briefcase, 
  Settings,
  ChevronLeft,
  ChevronRight,
  Wallet
} from "lucide-react";
import { useState } from "react";

export type ViewType = 
  | "dashboard" 
  | "backtest" 
  | "trading" 
  | "macro" 
  | "news" 
  | "portfolio" 
  | "settings";

interface NavItem {
  id: ViewType;
  label: string;
  icon: React.ReactNode;
  description: string;
}

const navItems: NavItem[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    icon: <LayoutDashboard size={20} />,
    description: "Vista general"
  },
  {
    id: "backtest",
    label: "Backtest",
    icon: <LineChart size={20} />,
    description: "Estrategias"
  },
  {
    id: "trading",
    label: "Trading",
    icon: <Target size={20} />,
    description: "Señales"
  },
  {
    id: "macro",
    label: "Macro Data",
    icon: <Building2 size={20} />,
    description: "FED, FMI, BM"
  },
  {
    id: "news",
    label: "Noticias",
    icon: <Newspaper size={20} />,
    description: "News + AI"
  },
  {
    id: "portfolio",
    label: "Portafolio",
    icon: <Briefcase size={20} />,
    description: "Cuentas MT5"
  },
  {
    id: "settings",
    label: "Configuración",
    icon: <Settings size={20} />,
    description: "Ajustes"
  }
];

interface SidebarProps {
  activeView: ViewType;
  onViewChange: (view: ViewType) => void;
}

export function Sidebar({ activeView, onViewChange }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside className={`sidebar-nav ${collapsed ? "collapsed" : ""}`}>
      {/* Logo Section */}
      <div className="sidebar-logo">
        <div className="logo-icon">
          <Wallet size={24} />
        </div>
        {!collapsed && (
          <div className="logo-text">
            <span className="logo-title">QuantFund</span>
            <span className="logo-subtitle">Trading Platform</span>
          </div>
        )}
      </div>

      {/* Navigation Items */}
      <nav className="sidebar-nav-items">
        {navItems.map((item) => (
          <button
            key={item.id}
            className={`nav-item ${activeView === item.id ? "active" : ""}`}
            onClick={() => onViewChange(item.id)}
            title={collapsed ? item.label : undefined}
          >
            <span className="nav-icon">{item.icon}</span>
            {!collapsed && (
              <>
                <span className="nav-label">{item.label}</span>
                <span className="nav-description">{item.description}</span>
              </>
            )}
            {activeView === item.id && <span className="nav-indicator" />}
          </button>
        ))}
      </nav>

      {/* Collapse Toggle */}
      <button 
        className="sidebar-toggle"
        onClick={() => setCollapsed(!collapsed)}
        title={collapsed ? "Expandir" : "Colapsar"}
      >
        {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
      </button>

      {/* Version Info */}
      {!collapsed && (
        <div className="sidebar-footer">
          <span className="version">v1.0.0</span>
          <span className="status-indicator">
            <span className="status-dot" />
            Conectado
          </span>
        </div>
      )}
    </aside>
  );
}

export default Sidebar;
