/* ATLAS PSU - assets/js/login-script.js
   Email + password sign in with Supabase Auth. There is no role or department picker: after sign in the
   page reads the user's row from the profiles table (role, dept) and routes to the matching dashboard.
   sessionStorage atlasRole / atlasDept / atlasUser / atlasEmail / atlasFaculty is only a display cache
   filled from that profile. "Sign in with Google" stays hidden until config.js sets GOOGLE_ENABLED. */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const cfg = window.ATLAS_CONFIG || {};
  const auth = window.atlasAuth;
  const client = window.atlasSupabase;
  const PSU_EMAIL = /^[a-zA-Z0-9._%+-]+@psu\.palawan\.edu\.ph$/i;

  const MESSAGES = {
    config: 'Sign in is not set up yet. Add the Supabase URL and anon key to assets/js/config.js.',
    offline: 'Could not reach the server. Check your connection and try again.',
    expired: 'Your session ended. Please log in again.',
    signedout: 'You were signed out.',
    noprofile: 'Your account has no ATLAS profile yet. Ask your administrator to set it up.',
    nodept: 'Your account has no department assigned. Ask your administrator to set it.',
    nofaculty: 'Your account is not linked to a faculty record yet. Ask your chairperson or administrator.',
    admin: 'Administrator accounts have no dashboard here. Use a chairperson or faculty account.',
    role: 'That page is not available for your role.'
  };
  const NEUTRAL = ['signedout', 'expired'];

  function showAlert(text, neutral) {
    const box = $('alertBox');
    box.textContent = text;
    box.classList.toggle('info', Boolean(neutral));
    box.hidden = false;
  }
  function hideAlert() { $('alertBox').hidden = true; }

  function setBusy(busy) {
    const btn = $('siSubmit');
    btn.disabled = busy;
    btn.textContent = busy ? 'Signing in...' : 'Log in';
  }

  function fieldError(id, text) {
    $(id).textContent = text || '';
    const input = $(id.replace(/Err$/, ''));
    if (input) input.setAttribute('aria-invalid', text ? 'true' : 'false');
  }

  /* Profile problems sign the user out again, so no half-valid session is left behind. */
  async function rejectProfile(code) {
    if (code !== 'offline' && code !== 'config' && client) {
      try { await client.auth.signOut(); } catch { /* already signed out */ }
      auth.clearLocalAuth();
    }
    showAlert(MESSAGES[code] || MESSAGES.offline);
  }

  async function routeSignedIn(announce) {
    const result = await auth.loadUser();
    if (result.error) {
      if (result.error === 'nosession') return false;
      await rejectProfile(result.error);
      return false;
    }
    auth.applyCache(result.user);
    if (announce) {                       // audit the login, best effort, never blocks the sign in
      try {
        await Promise.race([
          auth.fetch(auth.apiBase() + '/auth/session', { method: 'POST' }),
          new Promise(resolve => setTimeout(resolve, 2500))
        ]);
      } catch { /* the audit row is best effort */ }
    }
    window.location.replace(auth.DASH[result.user.role]);
    return true;
  }

  function signInMessage(error) {
    const text = String(error && error.message || '');
    if (error && error.status === 429) return 'Too many attempts. Wait a minute and try again.';
    if (/confirm/i.test(text)) return 'Please confirm your email address first, then log in.';
    if (/invalid|credential/i.test(text) || (error && error.status === 400)) return 'Wrong email or password.';
    return MESSAGES.offline;
  }

  async function onSubmit(event) {
    event.preventDefault();
    hideAlert();
    const email = $('siEmail').value.trim();
    const password = $('siPassword').value;
    fieldError('siEmailErr', !email ? 'Enter your PSU email.' : (PSU_EMAIL.test(email) ? '' : 'Use your PSU email (name@psu.palawan.edu.ph).'));
    fieldError('siPasswordErr', password ? '' : 'Enter your password.');
    if (!email || !password || !PSU_EMAIL.test(email)) return;
    if (!client) { showAlert(MESSAGES.config); return; }

    setBusy(true);
    try {
      const { error } = await client.auth.signInWithPassword({ email, password });
      if (error) { showAlert(signInMessage(error)); return; }
      await routeSignedIn(true);
    } catch {
      showAlert(MESSAGES.offline);
    } finally {
      setBusy(false);
    }
  }

  function initGoogle() {
    const button = document.querySelector('[data-google]');
    if (!button || cfg.GOOGLE_ENABLED !== true || !client) return;   // stays hidden until Google is set up
    button.hidden = false;
    $('googleDivider').hidden = false;
    button.addEventListener('click', async () => {
      hideAlert();
      const { error } = await client.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: window.location.origin + window.location.pathname, queryParams: { hd: 'psu.palawan.edu.ph' } }
      });
      if (error) showAlert(MESSAGES.offline);
    });
  }

  function initPasswordToggles() {
    document.querySelectorAll('.pw-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const input = $(btn.dataset.target);
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        btn.setAttribute('aria-pressed', String(show));
        btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      });
    });
  }

  document.addEventListener('DOMContentLoaded', async () => {
    initPasswordToggles();
    initGoogle();
    $('signinForm').addEventListener('submit', onSubmit);

    const reason = new URLSearchParams(window.location.search).get('reason');
    if (reason && MESSAGES[reason]) showAlert(MESSAGES[reason], NEUTRAL.includes(reason));
    if (!client) { if (!reason) showAlert(MESSAGES.config); return; }
    if (!reason) {                                        // already signed in (or back from Google): go straight in
      try { await routeSignedIn(true); } catch { /* stay on the form */ }
    }
  });
})();