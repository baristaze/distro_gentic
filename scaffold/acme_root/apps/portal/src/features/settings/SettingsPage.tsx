import { Link } from "react-router-dom";
import { useSlot } from "../../app/slot";
import { sectionAddress, settingsGroups } from "../../app/shell/settingsNavModel";
import { Card, Page } from "../../design/kit";

/** Settings' overview: a card for each group, each section with what it holds.
 * What is set up once lives here, out of the left bar a person scans daily. */
export function SettingsPage() {
  const groups = settingsGroups(useSlot().settings);
  return (
    <Page title="Settings">
      {groups.map((group) => (
        <Card key={group.name} title={group.name}>
          <ul className="acme-settings-sections" aria-label={group.name}>
            {group.entries.map((entry) => {
              const to = sectionAddress(entry);
              return to === null ? null : (
                <li key={entry.id}>
                  <Link to={to} className="acme-settings-section">
                    {entry.icon}
                    <span>{entry.label}</span>
                    <small>{entry.about}</small>
                  </Link>
                </li>
              );
            })}
          </ul>
        </Card>
      ))}
    </Page>
  );
}
