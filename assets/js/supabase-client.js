/* ATLAS PSU - assets/js/supabase-client.js
   Creates the one shared Supabase client (window.atlasSupabase) from assets/js/config.js.
   Load order: config.js, ../vendor/supabase.js, supabase-client.js, then app-core.js.
   atlasSupabase is null when the project is not configured; the login page then says so.
   The session (access + refresh token) is kept by supabase-js and refreshed automatically. */
(function () {
  'use strict';
  var cfg = window.ATLAS_CONFIG || {};
  if (!window.atlasSupabase) {
    var ready = /^https:\/\//.test(cfg.SUPABASE_URL || '') && cfg.SUPABASE_ANON_KEY &&
      window.supabase && typeof window.supabase.createClient === 'function';
    window.atlasSupabase = ready
      ? window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, {
          auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }
        })
      : null;
  }
})();