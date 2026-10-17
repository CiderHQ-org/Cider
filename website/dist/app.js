'use strict';

const tabs = [...document.querySelectorAll('.preview-tab')];
function selectPreview(tab, focus = false) {
  for (const item of tabs) {
    const selected = item === tab;
    item.setAttribute('aria-selected', String(selected));
    item.tabIndex = selected ? 0 : -1;
    document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
  }
  document.getElementById('preview-title').textContent = tab.textContent;
  if (focus) tab.focus();
}
for (const tab of tabs) {
  tab.addEventListener('click', () => selectPreview(tab));
  tab.addEventListener('keydown', event => {
    const index = tabs.indexOf(tab);
    let next;
    if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
    if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
    if (event.key === 'Home') next = tabs[0];
    if (event.key === 'End') next = tabs[tabs.length - 1];
    if (next) { event.preventDefault(); selectPreview(next, true); }
  });
}

const copyButton = document.getElementById('copy-command');
const copyStatus = document.getElementById('copy-status');
if (copyButton && navigator.clipboard && window.isSecureContext) {
  copyButton.hidden = false;
  let resetTimer;
  copyButton.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(document.getElementById('install-command').textContent.trim());
      copyButton.textContent = 'Copied';
      copyStatus.textContent = 'Command copied. Paste it into your terminal to start.';
      clearTimeout(resetTimer);
      resetTimer = setTimeout(() => { copyButton.textContent = 'Copy command'; }, 3000);
    } catch {
      copyStatus.textContent = 'Clipboard unavailable. Select and copy the command above.';
    }
  });
}
