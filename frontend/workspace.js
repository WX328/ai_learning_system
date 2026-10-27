// Presentation-only navigation: the existing page routing stays in core.js.
export function initWorkspaceNavigation() {
  const workspace = document.getElementById('workspace-view');
  const toggle = document.getElementById('navigation-toggle');
  const sidebar = document.getElementById('workspace-navigation');
  const close = document.getElementById('navigation-close');
  const backdrop = document.getElementById('navigation-backdrop');
  const content = document.getElementById('workspace-content');
  const compact = window.matchMedia('(max-width: 1100px)');
  let previousFocus;

  function setOpen(open, restoreFocus = false) {
    if (open) previousFocus = document.activeElement;
    workspace.classList.toggle('navigation-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    sidebar.inert = compact.matches && !open;
    content.inert = open;
    if (open) {
      sidebar.setAttribute('role', 'dialog');
      sidebar.setAttribute('aria-modal', 'true');
    } else {
      sidebar.removeAttribute('role');
      sidebar.removeAttribute('aria-modal');
    }
    if (open) close.focus();
    else if (restoreFocus && previousFocus?.isConnected) previousFocus.focus();
  }

  toggle.addEventListener('click', () => setOpen(!workspace.classList.contains('navigation-open'), true));
  close.addEventListener('click', () => setOpen(false, true));
  backdrop.addEventListener('click', () => setOpen(false, true));
  sidebar.addEventListener('click', event => {
    if (compact.matches && event.target.closest('[data-page]')) setOpen(false, true);
  });
  document.addEventListener('keydown', event => {
    if (!workspace.classList.contains('navigation-open')) return;
    if (event.key === 'Escape') { event.preventDefault(); setOpen(false, true); }
    if (event.key !== 'Tab') return;
    const controls = [...sidebar.querySelectorAll('button, a[href], select')]
      .filter(control => !control.disabled && control.getClientRects().length);
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  });
  compact.addEventListener?.('change', () => setOpen(false));
  document.getElementById('logout-button').addEventListener('click', () => setOpen(false));
  setOpen(false);
}
