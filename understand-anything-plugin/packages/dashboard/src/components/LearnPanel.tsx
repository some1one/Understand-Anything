import ProjectOverview from "./ProjectOverview";

/**
 * Info-tab panel shown in the Learn persona. The guided-walkthrough feature
 * was removed; the learn persona now reuses the standard project-overview
 * summary so the Info tab still renders something sensible.
 */
export default function LearnPanel() {
  return <ProjectOverview />;
}
