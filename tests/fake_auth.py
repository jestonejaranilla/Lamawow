"""Fake Supabase for the Playwright tests. The real client needs a real project; this stand-in answers the same
calls (getSession, profiles and faculty lookups) from localStorage['__testProfile'], so the dashboards can be
opened in a test browser with the Part 15 session check switched on."""

FAKE_AUTH = """
(() => {
  const prof = () => JSON.parse(localStorage.getItem('__testProfile') || 'null');
  const chain = table => {
    const c = { select() { return c; }, eq() { return c; },
      maybeSingle: async () => { const p = prof();
        return { data: !p ? null : (table === 'profiles' ? p : { name: p.faculty_name }), error: null }; } };
    return c;
  };
  window.atlasSupabase = {
    auth: {
      getSession: async () => { const p = prof();
        return { data: { session: p ? { access_token: 'test', user: { id: 'u1', email: p.email } } : null } }; },
      refreshSession: async () => ({ data: { session: null } }),
      signOut: async () => { localStorage.removeItem('__testProfile'); },
      onAuthStateChange() {}
    },
    from: chain
  };
})();
"""


def chair_profile_js(dept_expr):
    """JS statement that makes the fake project return a chairperson of the given department."""
    return ("localStorage.setItem('__testProfile', JSON.stringify({role:'chairperson', dept:%s, "
            "full_name:'Tester', email:'t@psu.palawan.edu.ph'}));" % dept_expr)


FACULTY_PROFILE_JS = ("localStorage.setItem('__testProfile', JSON.stringify({role:'faculty', dept:'IT', faculty_id:'f1', "
                      "full_name:'Prof. Maria Santos', faculty_name:'Prof. Maria Santos', email:'t@psu.palawan.edu.ph'}));")


def switch_dept_js(code):
    return ("() => { sessionStorage.setItem('atlasDept','%s'); const p = JSON.parse(localStorage.getItem('__testProfile'));"
            " p.dept = '%s'; localStorage.setItem('__testProfile', JSON.stringify(p)); }" % (code, code))