"""Run with python -m unittest discover -s contrib/testnet/explorer -p 'test_theme*.py'."""
import base64
import hashlib
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("theme_patch", Path(__file__).with_name("patch-theme-switch.py"))
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)

LAYOUT = '''html(lang="en")
\t\tlink(rel="stylesheet", href=assetUrl("./css/b3-theme.css"))
\t\ta(id=`theme-toggler-${themeName}`, onclick=`activateTheme('${themeName}'); return false;`)
'''
SITE = '''function activateTheme(themeName) {
\t$(`#${themeName}-theme-link-tag`).attr("rel", "stylesheet");
\t$(`#theme-toggler-${themeName}`).addClass(activeClass).removeClass(inactiveClass);
}
'''


class ThemePatchTests(unittest.TestCase):
    def test_quote_renders_inline_and_patch_is_idempotent(self):
        layout = '\tfooter\n\t\tiframe(id="quoteIframe", src="./snippet/quote/random", onload="iframeLoaded(\'quoteIframe\');")\n'
        result = patch.patch_quote_layout(layout)
        self.assertNotIn('iframe(', result)
        self.assertIn('+quote(b3Footer.quote, b3Footer.index', result)
        self.assertEqual(result, patch.patch_quote_layout(result))

    def test_clean_install_and_rerun(self):
        layout = patch.patch_layout(LAYOUT)
        site = patch.patch_site(SITE)
        self.assertEqual(patch.patch_layout(layout), layout)
        self.assertEqual(patch.patch_site(site), site)
        self.assertIn('aria-pressed=', layout)
        self.assertIn('data-b3-theme', site)

    def test_upgrade_partial_inline_switch(self):
        old = LAYOUT.replace("onclick=`activateTheme", "onclick=`document.documentElement.setAttribute('data-b3-theme','${themeName}'); activateTheme")
        fixed = patch.patch_layout(old)
        self.assertNotIn("document.documentElement", fixed)
        self.assertIn("onclick=`activateTheme", fixed)

    def test_exact_integrity_and_unrelated_entries_preserved(self):
        manifest = '{"site.js": "sha384-old", "other.js": "sha384-keep"}'
        body = patch.patch_site(SITE).encode("utf-8")
        fixed = patch.patch_integrity(manifest, body)
        expected = base64.b64encode(hashlib.sha384(body).digest()).decode()
        self.assertIn('sha384-' + expected, fixed)
        self.assertIn('"other.js": "sha384-keep"', fixed)
        self.assertEqual(patch.patch_integrity(fixed, body), fixed)

    def test_unknown_install_fails_closed(self):
        for fn, args in ((patch.patch_layout, ("html",)), (patch.patch_site, ("",)), (patch.patch_integrity, ("{}", b""))):
            with self.assertRaises(SystemExit):
                fn(*args)

    def test_changed_script_changes_url_without_removing_integrity(self):
        shared = 'script(src=assetUrl(`./js/site.js`), integrity=assetIntegrity("site.js"), crossorigin="anonymous")'
        updated = patch.patch_shared(shared, b'first')
        self.assertIn('integrity=assetIntegrity("site.js")', updated)
        self.assertEqual(patch.patch_shared(updated, b'first'), updated)
        self.assertNotEqual(patch.patch_shared(updated, b'second'), updated)


if __name__ == "__main__":
    unittest.main()
