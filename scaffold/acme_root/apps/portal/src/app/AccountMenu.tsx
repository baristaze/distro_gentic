// The user chip at the foot of the left bar: the avatar with the live
// channel's dot on its corner, the person's name, and the org. Its menu
// holds Settings, Profile and preferences, the theme, the keyboard
// shortcuts, the documentation, and Sign out. It opens on a click, never on hover.
import type { ReactNode } from "react";
import {
  ChevronIcon,
  DocumentIcon,
  KeyboardIcon,
  LogOutIcon,
  Menu,
  MenuItem,
  MenuItemRadio,
  MenuSeparator,
  MenuText,
  MonitorIcon,
  MoonIcon,
  SettingsIcon,
  SunIcon,
  UserIcon,
} from "../design/kit";
import { ConnectionDot } from "./ConnectionDot";
import type { ThemePreference } from "./themeModel";
import { useAccountMenuVm } from "./useAccountMenuVm";

const THEME_ICONS: Record<ThemePreference, ReactNode> = {
  system: <MonitorIcon />,
  light: <SunIcon />,
  dark: <MoonIcon />,
};

export function AccountMenu() {
  const vm = useAccountMenuVm();
  return (
    <div className="acme-user-chip">
      <Menu
        label="Account"
        triggerLabel={vm.email ? `Account: ${vm.email}` : "Account"}
        triggerClassName="acme-user-trigger"
        placement="above"
        minWidth={248}
        disabled={!vm.ready}
        trigger={
          <>
            <span className="acme-avatar" aria-hidden="true">
              {vm.initial}
            </span>
            <span className="acme-user-lines">
              <span className="acme-user-name">{vm.name}</span>
              <span className="acme-user-org">{vm.orgName}</span>
            </span>
            <ChevronIcon className="acme-user-caret" />
          </>
        }
      >
        <MenuText strong>{vm.email}</MenuText>
        <MenuText>{vm.orgName}</MenuText>
        <MenuSeparator />
        <MenuItem onSelect={vm.openSettings} icon={<SettingsIcon />} shortcut="⌘,">
          Settings
        </MenuItem>
        <MenuItem onSelect={vm.openProfile} icon={<UserIcon />}>
          Profile and preferences
        </MenuItem>
        <MenuSeparator />
        <div role="group" aria-label="Theme">
          <MenuText>Theme</MenuText>
          {vm.themes.map((choice) => (
            <MenuItemRadio
              key={choice.value}
              checked={vm.theme === choice.value}
              onSelect={() => vm.setTheme(choice.value)}
              icon={THEME_ICONS[choice.value]}
            >
              {choice.label}
            </MenuItemRadio>
          ))}
        </div>
        <MenuSeparator />
        <MenuItem onSelect={vm.openShortcuts} icon={<KeyboardIcon />}>
          Keyboard shortcuts
        </MenuItem>
        <MenuItem onSelect={() => window.open(vm.docsUrl, "_blank", "noopener,noreferrer")} icon={<DocumentIcon />}>
          Documentation ↗
        </MenuItem>
        <MenuSeparator />
        <MenuItem onSelect={vm.signOut} disabled={vm.signingOut} icon={<LogOutIcon />}>
          Sign out
        </MenuItem>
      </Menu>
      <ConnectionDot />
    </div>
  );
}
