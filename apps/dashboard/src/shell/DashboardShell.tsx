import React, { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import elephantLogo from "../assets/brand/elephant-logo.png";
import { cx } from "../lib/classNames";
import {
  navigationGroups,
  resolveNavigation,
  resolveNavigationGroup,
} from "../lib/dashboardNavigation";
import { buildDashboardRouteTarget } from "../lib/dashboardRouting";
import { isDesktopRuntime } from "../lib/desktopBridge";
import { DitherBackground } from "./DitherBackground";
import styles from "./DashboardShell.module.css";

export function DashboardShell(): React.JSX.Element {
  const location = useLocation();
  const currentItem = resolveNavigation(location.pathname);
  const currentGroup = resolveNavigationGroup(location.pathname);
  const desktop = isDesktopRuntime();

  useEffect(() => {
    document.title = `${currentItem.label} | Elephant Agent Dashboard`;
  }, [currentItem.label]);

  return (
    <>
      <DitherBackground />
      <div className={styles.shell}>
        <header className={styles.header}>
          <div className={styles.headerInner}>
            <NavLink className={styles.brand} to={buildDashboardRouteTarget("/")} end>
              <img src={elephantLogo} alt="" />
              <div className={styles.brandCopy}>
                <strong>Elephant Agent</strong>
                <span>{desktop ? "desktop" : "dashboard"} · {currentItem.label.toLowerCase()}</span>
              </div>
            </NavLink>

            <div className={styles.navWrap}>
              <nav className={styles.nav} aria-label="Primary dashboard">
                {navigationGroups.map((group) => {
                  const groupActive = currentGroup?.label === group.label;
                  return (
                    <div key={group.label} className={cx(styles.navGroup, groupActive && styles.navGroupActive)}>
                      <span className={styles.navGroupLabel}>{group.label}</span>
                      <div className={styles.navGroupLinks}>
                        {group.items.map((item) => (
                          <NavLink
                            key={item.to}
                            className={({ isActive }) =>
                              cx(
                                styles.navTopLink,
                                item.advanced && styles.navTopLinkAdvanced,
                                (isActive || (item.to === "/" && location.pathname === "/")) && styles.navTopLinkActive,
                              )
                            }
                            to={buildDashboardRouteTarget(item.to)}
                            end={item.to === "/"}
                            title={item.advanced ? `${item.label} · advanced` : undefined}
                          >
                            {item.label}
                          </NavLink>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </nav>
            </div>

            <div className={styles.mobileNavWrap}>
              <nav className={styles.mobileNav} aria-label="Compact dashboard sections">
                {navigationGroups.map((group) => {
                  const groupActive = currentGroup?.label === group.label;
                  return (
                    <div key={group.label} className={cx(styles.mobileNavGroup, groupActive && styles.mobileNavGroupActive)}>
                      <span className={styles.mobileNavGroupLabel}>{group.label}</span>
                      <div className={styles.mobileNavLinks}>
                        {group.items.map((item) => (
                          <NavLink
                            key={item.to}
                            className={({ isActive }) =>
                              cx(
                                styles.mobileNavLink,
                                item.advanced && styles.mobileNavLinkAdvanced,
                                (isActive || (item.to === "/" && location.pathname === "/")) && styles.mobileNavLinkActive,
                              )
                            }
                            to={buildDashboardRouteTarget(item.to)}
                            end={item.to === "/"}
                          >
                            {item.label}
                          </NavLink>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </nav>
            </div>
          </div>
        </header>

        <main className={styles.main}>
          <Outlet />
        </main>
      </div>
    </>
  );
}
