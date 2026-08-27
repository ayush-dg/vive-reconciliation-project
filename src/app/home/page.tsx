// Placeholder only — the real Home (Reports) screen (status badges, summary
// stats, Uploaded Statements panel, Extract/Reconcile actions) is Task 6.1's
// deliverable (Session 6). This exists so Task 1.3's post-login redirect target
// renders instead of 404ing, matching the same reasoning as Task 1.1's root page.
export default function HomePlaceholderPage() {
  return <p data-testid="home-placeholder">Signed in — Home screen placeholder (built in Session 6).</p>;
}
