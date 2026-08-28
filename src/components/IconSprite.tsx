// SVG icon defs, adapted from the Figma mockups' icon set — trimmed to icons
// this build's six screens actually use. Rendered once near the root; usages
// elsewhere reference `<svg className="icon"><use href="#i-name" /></svg>`.
export default function IconSprite() {
  return (
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
      <defs>
        <symbol id="i-home" viewBox="0 0 24 24">
          <path d="M3 11.5 12 4l9 7.5" />
          <path d="M5.5 10v9.5A1 1 0 0 0 6.5 20.5h11a1 1 0 0 0 1-1V10" />
          <path d="M9.5 20.5V14h5v6.5" />
        </symbol>
        <symbol id="i-upload" viewBox="0 0 24 24">
          <path d="M12 15V4" />
          <path d="M8 8l4-4 4 4" />
          <path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" />
        </symbol>
        <symbol id="i-alert" viewBox="0 0 24 24">
          <path d="M12 3.5 21 19.5H3z" />
          <path d="M12 10v4" />
          <circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />
        </symbol>
        <symbol id="i-file" viewBox="0 0 24 24">
          <path d="M7 3.5h7l4 4v13h-11z" />
          <path d="M14 3.5v4h4" />
          <path d="M9.5 12.5h5M9.5 15.5h5M9.5 18h3" />
        </symbol>
        <symbol id="i-users" viewBox="0 0 24 24">
          <circle cx="9" cy="8.5" r="3" />
          <path d="M3.5 19.5c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
          <path d="M15.5 5.8a3 3 0 0 1 0 5.6" />
          <path d="M17 14.7c2.6.4 4.5 2.2 4.5 4.8" />
        </symbol>
        <symbol id="i-settings" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3.5v2.3M12 18.2v2.3M4.9 6.4l1.9 1.4M17.2 16.2l1.9 1.4M3.5 12h2.3M18.2 12h2.3M4.9 17.6l1.9-1.4M17.2 7.8l1.9-1.4" />
        </symbol>
        <symbol id="i-check-circle" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" />
          <path d="M8 12.3l2.6 2.6L16 9.3" />
        </symbol>
        <symbol id="i-key" viewBox="0 0 24 24">
          <circle cx="8.5" cy="15.5" r="3.2" />
          <path d="M10.6 13.3 18 6l1.6 1.6M15.4 9.2l1.9 1.9" />
        </symbol>
        <symbol id="i-folder" viewBox="0 0 24 24">
          <path d="M3.5 7.5h5l2 2.2h9.5v9.3a1 1 0 0 1-1 1h-14.5a1 1 0 0 1-1-1z" />
        </symbol>
      </defs>
    </svg>
  );
}
