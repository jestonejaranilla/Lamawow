/* ============================================================
   ATLAS PSU - sign in flow (pages/login.html)

   Steps: role -> signin | signup -> dashboard
          forgot (screen only, not functional yet)
          Google -> dashboard (one extra step the first time)

   Showcase sign in: any email that ends in @psu.palawan.edu.ph with any
   password is accepted. No accounts or passwords are stored. The only thing
   remembered on this device is a name and department per email, so the
   dashboard opens on the right classes next time.
   ============================================================ */
(function () {
  'use strict';

  /* Paste an OAuth "Web application" Client ID here to switch Google sign in
     from the built-in demo chooser to the real Google popup. */
  const GOOGLE_CLIENT_ID = '';

  const DOMAIN = 'psu.palawan.edu.ph';
  const EMAIL_PATTERN = /^[a-zA-Z0-9._%+-]+@psu\.palawan\.edu\.ph$/i;
  const OTHER = '__other';
  const DESTINATION = { chairperson: 'dashboard.html', faculty: '../faculty/dashboard.html' };
  const ROLE_LABEL = { chairperson: 'Chairperson', faculty: 'Faculty member' };
  const DEPARTMENTS = [
    ['IT', 'Information Technology'], ['CS', 'Computer Science'], ['MB', 'Marine Biology'],
    ['ES', 'Environmental Science'], ['MedB', 'Medical Biology']
  ];
  const STEPS = ['role', 'signin', 'signup', 'forgot', 'complete'];

  const $ = id => document.getElementById(id);
  const state = { role: null, step: 'role', pending: null };
  let depth = 0;
  let googleClient = null;

  /* ---------- Storage ---------- */
  function readJSON(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(key));
      return value == null ? fallback : value;
    } catch { return fallback; }
  }
  function writeJSON(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
  }

  /* name and department remembered per email and role (no password) */
  const profileKey = email => state.role + ':' + email.toLowerCase();
  const getProfile = email => readJSON('atlasProfiles', {})[profileKey(email)] || null;
  function saveProfile(email, name, dept) {
    const profiles = readJSON('atlasProfiles', {});
    profiles[profileKey(email)] = { name, dept };
    writeJSON('atlasProfiles', profiles);
  }

  function facultyNames() {
    const names = readJSON('facultyData', []).map(f => f && f.name).filter(Boolean);
    return Array.from(new Set(names)).sort();
  }

  const prettyName = email => email.split('@')[0].replace(/[._-]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  /* ---------- Messages ---------- */
  function showAlert(message, kind) {
    const box = $('alertBox');
    box.textContent = message || '';
    box.classList.toggle('info', kind === 'info');
    box.hidden = !message;
  }

  function setError(id, message) {
    const input = $(id);
    const field = input.closest('.auth-field');
    field.querySelector('.auth-error').textContent = message || '';
    field.classList.toggle('invalid', Boolean(message));
    input.setAttribute('aria-invalid', message ? 'true' : 'false');
  }

  function clearErrors(root) {
    root.querySelectorAll('.auth-field').forEach(field => {
      field.classList.remove('invalid');
      const span = field.querySelector('.auth-error');
      if (span) span.textContent = '';
      field.querySelectorAll('[aria-invalid]').forEach(el => el.setAttribute('aria-invalid', 'false'));
    });
  }

  /* apply [id, message] pairs; returns true when everything is fine */
  function applyErrors(pairs) {
    let first = null;
    pairs.forEach(([id, message]) => {
      setError(id, message);
      if (message && !first) first = id;
    });
    if (first) $(first).focus();
    return !first;
  }

  /* ---------- Steps and history ---------- */
  function render(step) {
    if (!STEPS.includes(step)) step = 'role';
    if (step !== 'role' && !state.role) step = 'role';
    if (step === 'complete' && !state.pending) step = 'signin';
    state.step = step;
    document.body.dataset.role = state.role || '';
    document.querySelectorAll('.auth-step').forEach(section => { section.hidden = section.dataset.step !== step; });
    document.querySelectorAll('.js-role-label').forEach(el => { el.textContent = state.role ? ROLE_LABEL[state.role] : ''; });
    showAlert('');
    document.querySelectorAll('.auth-step:not([hidden])').forEach(clearErrors);
    document.title = { role: 'Welcome', signin: 'Log in', signup: 'Create account', forgot: 'Forgot password', complete: 'One last step' }[step] + ' | ATLAS PSU';
    const heading = document.querySelector('.auth-step[data-step="' + step + '"] h1');
    if (heading) heading.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }

  function go(step) {
    depth += 1;
    try { history.pushState({ step, depth }, '', '#' + step); } catch { /* history unavailable */ }
    render(step);
  }

  window.addEventListener('popstate', event => {
    depth = (event.state && event.state.depth) || 0;
    render((event.state && event.state.step) || 'role');
  });

  $('backBtn').addEventListener('click', () => {
    if (depth > 0) history.back();
    else window.location.href = '../index.html';
  });

  document.addEventListener('click', event => {
    const pick = event.target.closest('[data-pick-role]');
    if (pick) { state.role = pick.dataset.pickRole; go('signin'); return; }
    const link = event.target.closest('[data-go]');
    if (link) go(link.dataset.go);
  });

  /* ---------- Form pieces ---------- */
  document.querySelectorAll('.js-dept').forEach(select => {
    select.innerHTML = '<option value="" disabled selected>Select your department</option>' +
      DEPARTMENTS.map(([value, label]) => `<option value="${value}">${label}</option>`).join('');
  });

  document.querySelectorAll('.js-faculty').forEach(select => {
    const names = facultyNames();
    const add = (value, text, extra) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      Object.assign(option, extra);
      select.appendChild(option);
    };
    add('', 'Select your name', { disabled: true, selected: true });
    names.forEach(name => add(name, name));
    add(OTHER, 'My name is not listed');
    const manualWrap = select.closest('.auth-field').querySelector('.auth-manual');
    select.addEventListener('change', () => {
      const other = select.value === OTHER;
      manualWrap.hidden = !other;
      if (other) manualWrap.querySelector('input').focus();
    });
    if (!names.length) { select.value = OTHER; manualWrap.hidden = false; }
  });

  document.querySelectorAll('.pw-toggle').forEach(button =>
    button.addEventListener('click', () => {
      const input = $(button.dataset.target);
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.setAttribute('aria-pressed', show ? 'true' : 'false');
      button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    }));

  /* ---------- Validation ---------- */
  function emailMessage(value) {
    if (!value) return 'Enter your PSU email address.';
    if (!EMAIL_PATTERN.test(value)) return 'Use your PSU email address (name@' + DOMAIN + ').';
    return '';
  }

  function nameCheck(prefix) {
    if (state.role === 'faculty') {
      const select = $(prefix + 'Faculty');
      const name = select.value === OTHER ? $(prefix + 'FacultyManual').value.trim() : select.value;
      return [prefix + 'Faculty', name ? '' : (select.value === OTHER ? 'Enter your full name.' : 'Select your name.')];
    }
    return [prefix + 'Name', $(prefix + 'Name').value.trim() ? '' : 'Enter your full name.'];
  }

  function nameValue(prefix) {
    if (state.role === 'faculty') {
      const select = $(prefix + 'Faculty');
      return select.value === OTHER ? $(prefix + 'FacultyManual').value.trim() : select.value;
    }
    return $(prefix + 'Name').value.trim();
  }

  /* ---------- Session ---------- */
  function startSession(email, name, dept) {
    saveProfile(email, name, dept);
    if (window.atlasLogout) window.atlasLogout(); else sessionStorage.clear();
    sessionStorage.setItem('atlasRole', state.role);
    sessionStorage.setItem('atlasDept', dept);
    sessionStorage.setItem('atlasUser', name);
    sessionStorage.setItem('atlasEmail', email);
    if (state.role === 'faculty') {
      const profiles = readJSON('facultyProfiles', {});
      profiles[name] = { email, dept };
      writeJSON('facultyProfiles', profiles);
      sessionStorage.setItem('atlasFaculty', name);
    }
    window.location.href = DESTINATION[state.role];
  }

  /* signed in with a valid PSU email: open the dashboard, or ask who they are once */
  function signedIn(email, suggestedName) {
    const profile = getProfile(email);
    if (profile) { startSession(email, profile.name, profile.dept); return; }
    state.pending = { email, name: suggestedName || prettyName(email) };
    $('cpEmailChip').textContent = email;
    if (state.role === 'chairperson') $('cpName').value = state.pending.name;
    else {
      const select = $('cpFaculty');
      const match = Array.from(select.options).find(o => o.value && o.value !== OTHER && o.value.toLowerCase() === state.pending.name.toLowerCase());
      if (match) select.value = match.value;
    }
    go('complete');
  }

  /* ---------- Log in ---------- */
  $('signinForm').addEventListener('submit', event => {
    event.preventDefault();
    showAlert('');
    const email = $('siEmail').value.trim().toLowerCase();
    const ok = applyErrors([
      ['siEmail', emailMessage(email)],
      ['siPassword', $('siPassword').value ? '' : 'Enter your password.']
    ]);
    if (!ok) return;
    try {
      if ($('siRemember').checked) localStorage.setItem('atlasRememberedEmail', email);
      else localStorage.removeItem('atlasRememberedEmail');
    } catch { /* storage unavailable */ }
    signedIn(email);
  });

  /* ---------- Create account ---------- */
  $('signupForm').addEventListener('submit', event => {
    event.preventDefault();
    showAlert('');
    const email = $('suEmail').value.trim().toLowerCase();
    const password = $('suPassword').value;
    const [nameId, nameMsg] = nameCheck('su');
    const ok = applyErrors([
      [nameId, nameMsg],
      ['suDept', $('suDept').value ? '' : 'Select your department.'],
      ['suEmail', emailMessage(email)],
      ['suPassword', password ? '' : 'Create a password.'],
      ['suConfirm', !$('suConfirm').value ? 'Re-enter your password.' : ($('suConfirm').value !== password ? 'Passwords do not match.' : '')]
    ]);
    if (!ok) return;
    startSession(email, nameValue('su'), $('suDept').value);
  });

  /* ---------- One last step (name and department) ---------- */
  $('completeForm').addEventListener('submit', event => {
    event.preventDefault();
    if (!state.pending) { go('signin'); return; }
    const [nameId, nameMsg] = nameCheck('cp');
    const ok = applyErrors([[nameId, nameMsg], ['cpDept', $('cpDept').value ? '' : 'Select your department.']]);
    if (!ok) return;
    startSession(state.pending.email, nameValue('cp'), $('cpDept').value);
  });

  /* ---------- Forgot password (screen only, not functional yet) ---------- */
  $('forgotForm').addEventListener('submit', event => {
    event.preventDefault();
    const email = $('fpEmail').value.trim().toLowerCase();
    if (!applyErrors([['fpEmail', emailMessage(email)]])) { showAlert(''); return; }
    showAlert('Password reset by email is not available yet. Please contact your system administrator to reset your password.', 'info');
  });

  /* ---------- Google ---------- */
  function handleGoogle(profile) {
    const email = String(profile.email || '').trim().toLowerCase();
    if (profile.verified === false) { showAlert('Your Google email is not verified.'); return; }
    if (!EMAIL_PATTERN.test(email)) { showAlert('Use your PSU Google account (name@' + DOMAIN + ').'); return; }
    signedIn(email, profile.name);
  }

  function setupGoogle() {
    if (!GOOGLE_CLIENT_ID) return;
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.onload = () => {
      googleClient = google.accounts.oauth2.initTokenClient({
        client_id: GOOGLE_CLIENT_ID,
        scope: 'openid email profile',
        hd: DOMAIN,
        prompt: 'select_account',
        callback: async response => {
          if (response.error) { showAlert('Google sign in was not completed.'); return; }
          try {
            const reply = await fetch('https://www.googleapis.com/oauth2/v3/userinfo', { headers: { Authorization: 'Bearer ' + response.access_token } });
            const info = await reply.json();
            handleGoogle({ email: info.email, name: info.name || '', verified: info.email_verified !== false });
          } catch { showAlert('Could not read your Google account. Check your connection and try again.'); }
        },
        error_callback: () => showAlert('Google sign in was cancelled.', 'info')
      });
    };
    document.head.appendChild(script);
  }

  document.querySelectorAll('[data-google]').forEach(button => button.addEventListener('click', () => {
    showAlert('');
    if (!GOOGLE_CLIENT_ID) { openChooser(); return; }
    if (!googleClient) { showAlert('Google sign in could not load. Check your connection and try again.'); return; }
    googleClient.requestAccessToken();
  }));

  /* demo chooser, used only while GOOGLE_CLIENT_ID is empty */
  const modal = $('gModal');
  function openChooser() {
    setError('gEmail', '');
    $('gEmail').value = '';
    modal.hidden = false;
    $('gEmail').focus();
  }
  function closeChooser() { modal.hidden = true; }
  $('gCancel').addEventListener('click', closeChooser);
  modal.addEventListener('click', event => { if (event.target === modal) closeChooser(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !modal.hidden) closeChooser(); });
  $('gForm').addEventListener('submit', event => {
    event.preventDefault();
    const email = $('gEmail').value.trim().toLowerCase();
    if (!applyErrors([['gEmail', emailMessage(email)]])) return;
    closeChooser();
    handleGoogle({ email, name: prettyName(email), verified: true });
  });

  /* ---------- Start ---------- */
  try {
    const remembered = localStorage.getItem('atlasRememberedEmail');
    if (remembered) { $('siEmail').value = remembered; $('siRemember').checked = true; }
  } catch { /* storage unavailable */ }
  setupGoogle();

  const params = new URLSearchParams(window.location.search);
  const roleParam = params.get('role');
  if (roleParam === 'faculty' || roleParam === 'chairperson') state.role = roleParam;
  const startStep = state.role ? (params.get('mode') === 'signup' ? 'signup' : 'signin') : 'role';
  try { history.replaceState({ step: startStep, depth: 0 }, '', window.location.pathname + window.location.search + '#' + startStep); } catch { /* history unavailable */ }
  render(startStep);
})();