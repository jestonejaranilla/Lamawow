/* ATLAS PSU - assets/js/config.js
   Public browser configuration. The anon (publishable) key is public by design: it only lets the browser
   talk to Supabase as the signed-in user, and Row Level Security decides what each user may read.
   NEVER put the service_role / secret key here. It belongs only in the server's environment (.env, Render). */
window.ATLAS_CONFIG = {
  SUPABASE_URL: 'https://jijwmczbmpeuorzngakr.supabase.co',
  SUPABASE_ANON_KEY: 'sb_publishable_sumVOtOLMn9Vu8X1dsowDg_Qsr6vQY4',        // paste the anon / publishable key (starts with eyJ... or sb_publishable_...)
  API_BASE: '',                 // empty = automatic (display.js: same host on :5000 locally, the Render backend atlas-drsg for the static site). Set only to force one address.
  GOOGLE_ENABLED: false         // set to true after the Google provider is enabled in Supabase Auth
};