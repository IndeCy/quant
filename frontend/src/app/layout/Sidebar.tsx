import { NavLink } from "react-router-dom";

import { navigationItems } from "../navigation";

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <strong>Quant</strong>
        <span>Local Console</span>
      </div>
      <nav className="nav">
        {navigationItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink key={item.path} to={item.path} end={item.path === "/"} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <Icon size={18} />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}
