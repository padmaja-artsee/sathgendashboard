// ── Confirm Delete ─────────────────────────────────────────────────────────
document.addEventListener('submit', function (e) {
  const form = e.target;
  const msg = form.getAttribute('data-confirm');
  if (msg && !confirm(msg)) {
    e.preventDefault();
  }
});

// ── Follow-up date field show/hide ─────────────────────────────────────────
const followUpCheckbox = document.getElementById('follow-up-checkbox');
const followUpFields = document.getElementById('followup-fields');
if (followUpCheckbox && followUpFields) {
  followUpCheckbox.addEventListener('change', function () {
    if (this.checked) {
      followUpFields.classList.remove('hidden');
    } else {
      followUpFields.classList.add('hidden');
    }
  });
}

// ── Contact dropdown filtered by company ───────────────────────────────────
function setupCompanyContactFilter(companySelectId, contactSelectId) {
  const companySelect = document.getElementById(companySelectId);
  const contactSelect = document.getElementById(contactSelectId);
  if (!companySelect || !contactSelect) return;

  const originalOptions = Array.from(contactSelect.options).map(o => ({
    value: o.value,
    text: o.text,
  }));

  companySelect.addEventListener('change', function () {
    const companyId = this.value;
    if (!companyId) {
      // restore all contacts
      contactSelect.innerHTML = '';
      originalOptions.forEach(o => {
        const opt = document.createElement('option');
        opt.value = o.value;
        opt.text = o.text;
        contactSelect.appendChild(opt);
      });
      return;
    }
    // Fetch filtered contacts via API
    fetch('/api/contacts-for-company?company_id=' + encodeURIComponent(companyId))
      .then(r => r.json())
      .then(contacts => {
        contactSelect.innerHTML = '<option value="">— Select Contact —</option>';
        contacts.forEach(c => {
          const opt = document.createElement('option');
          opt.value = c.id;
          opt.text = c.name;
          contactSelect.appendChild(opt);
        });
      })
      .catch(() => {});
  });
}

setupCompanyContactFilter('opp-company-select', 'opp-contact-select');
setupCompanyContactFilter('act-company-select', 'act-contact-select');

// ── Tab Switching ───────────────────────────────────────────────────────────
function setupTabs(tabsContainerId) {
  const container = document.getElementById(tabsContainerId);
  if (!container) return;

  const buttons = container.querySelectorAll('.tab-btn');
  buttons.forEach(btn => {
    btn.addEventListener('click', function () {
      const target = this.getAttribute('data-tab');
      // deactivate all
      buttons.forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
      // activate
      this.classList.add('active');
      const panel = document.getElementById(target);
      if (panel) panel.classList.remove('hidden');
    });
  });
}

setupTabs('company-tabs');

// ── Pipeline / Table view toggle ────────────────────────────────────────────
const toggleViewBtn = document.getElementById('toggle-view-btn');
const tableView = document.getElementById('table-view');
const pipelineView = document.getElementById('pipeline-view');

if (toggleViewBtn && tableView && pipelineView) {
  const updateToggle = () => {
    const isPipeline = !tableView.classList.contains('hidden');
    toggleViewBtn.textContent = isPipeline ? 'Switch to Pipeline View' : 'Switch to Table View';
  };

  toggleViewBtn.addEventListener('click', function () {
    tableView.classList.toggle('hidden');
    pipelineView.classList.toggle('hidden');
    updateToggle();
  });

  updateToggle();
}
