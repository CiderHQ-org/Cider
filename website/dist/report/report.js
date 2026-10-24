'use strict';

const form = document.getElementById('report-form');
const fields = document.getElementById('report-fields');
const fileInput = document.getElementById('diagnostics');
const category = document.getElementById('category');
const submit = document.getElementById('send-report');
const archiveStatus = document.getElementById('archive-status');
const reportStatus = document.getElementById('report-status');
const checks = {crash: document.getElementById('crash-check'), freeze: document.getElementById('freeze-check')};
let validation;
let validatedFile;
let validationController;
let sending = false;
let submissionKey = crypto.randomUUID().replaceAll('-', '');
fields.disabled = false;

function updateChecks(diagnostics) {
  for (const [key, element] of Object.entries(checks)) {
    const label = key === 'crash' ? 'Crash diagnostics' : 'Allow freeze diagnostics';
    element.dataset.state = !diagnostics ? 'pending' : diagnostics[key] ? 'pass' : 'fail';
    element.textContent = `${label} — ${!diagnostics ? 'waiting for archive' : diagnostics[key] ? 'enabled in archive' : 'disabled or missing'}`;
  }
}

function updateSubmit() {
  const launchRequired = category.value && category.value !== 'install';
  const missingLaunch = validation && launchRequired && !validation.has_launch_log;
  submit.disabled = sending || !validation || validatedFile !== fileInput.files[0] || !category.value || missingLaunch;
  if (missingLaunch) archiveStatus.textContent = 'This archive has no launch log. Reproduce the problem, then collect a new archive.';
  else if (validation) archiveStatus.textContent = `Archive verified · Quadra ${validation.version}. Both saved diagnostics settings are enabled.`;
}

fileInput.addEventListener('change', async () => {
  validationController?.abort();
  validationController = new AbortController();
  const controller = validationController;
  const file = fileInput.files[0];
  validation = undefined;
  validatedFile = undefined;
  updateChecks();
  updateSubmit();
  if (!file) { archiveStatus.textContent = ''; return; }
  if (!file.name.toLowerCase().endsWith('.tar.gz') || file.size > 8 * 1024 * 1024) {
    archiveStatus.textContent = 'Choose a diagnostics .tar.gz no larger than 8 MiB.';
    return;
  }
  archiveStatus.textContent = 'Checking archive contents and diagnostics settings…';
  const upload = new FormData();
  upload.append('diagnostics', file);
  try {
    const response = await fetch('/api/reports/validate', {method: 'POST', body: upload, signal: controller.signal});
    const result = await response.json();
    if (controller.signal.aborted || file !== fileInput.files[0]) return;
    updateChecks(result.diagnostics);
    if (!response.ok) { archiveStatus.textContent = result.error || 'The archive could not be validated.'; return; }
    validation = result;
    validatedFile = file;
    updateSubmit();
  } catch (error) {
    if (error.name !== 'AbortError') archiveStatus.textContent = 'Archive checks are temporarily unavailable. Keep your file and try again shortly.';
  }
});
category.addEventListener('change', updateSubmit);

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!form.reportValidity() || submit.disabled) return;
  sending = true;
  updateSubmit();
  submit.textContent = 'Sending…';
  reportStatus.textContent = 'Uploading and saving your report…';
  const upload = new FormData(form);
  upload.append('submission_key', submissionKey);
  try {
    const response = await fetch('/api/reports', {method: 'POST', body: upload});
    const result = await response.json();
    if (!response.ok) {
      reportStatus.textContent = result.error || 'Your report could not be saved. Please try again.';
      return;
    }
    fields.disabled = true;
    reportStatus.textContent = `Report ${result.id} saved on the Quadra server. ${result.status === 'sent' ? 'It has been delivered to Discord.' : 'Discord delivery is queued; the server keeps your files if delivery needs to retry.'} Thank you.`;
    reportStatus.tabIndex = -1;
    reportStatus.focus();
  } catch {
    reportStatus.textContent = 'We could not confirm the response. Your files are still selected; try sending again. Repeating the same submission will not create another report.';
  } finally {
    sending = false;
    submit.textContent = 'Send report';
    updateSubmit();
  }
});
