/* Signed in already? Opening the site or the installed app goes straight to the dashboard (the login page routes
       by role and replaces itself, so the phone's Back button at Home leaves the app instead of coming back here).
       Coming here with Back never redirects, and nothing here signs the user out. */
    (function () {
      try {
        var nav = performance.getEntriesByType('navigation')[0];
        if (nav && nav.type === 'back_forward') return;
        for (var i = 0; i < localStorage.length; i++) {
          var k = localStorage.key(i);
          if (!/^sb-.+-auth-token$/.test(k)) continue;
          var v = JSON.parse(localStorage.getItem(k) || 'null');
          if (v && (v.refresh_token || v.access_token)) { location.replace('pages/login.html'); return; }
        }
      } catch (e) { /* show the landing page */ }
    })();