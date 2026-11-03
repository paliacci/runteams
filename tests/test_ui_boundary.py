"""Public ownership checks must cover physical source and built payloads."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from runteams_core.devtools.check_ui_boundary import inspect_ui, source_files, check_wheel


class UIBoundaryTests(unittest.TestCase):
    def test_private_code_is_rejected_even_when_it_never_calls_a_paid_api(self):
        for source in ('function subscriptionPlans(){return [];}',
                       'const panel=RunTeamsOfficialUI.settingsPanels;',
                       'const value=state.account.entitlements;',
                       'const route="/wallet";',
                       '<meta name="runteams-edition" content="community">'):
            with self.subTest(source=source):
                self.assertTrue(inspect_ui('web/ui/extra.js', source))

    def test_model_vendor_catalog_and_portable_schemas_are_not_product_policy(self):
        source = "const value={marketplace:'vendor-plugins',schema:'runteams.marketplace-pipeline/v2'};"
        self.assertEqual(inspect_ui('web/ui/runtime.js', source), [])

    def test_unregistered_ui_files_are_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / 'web/not-in-http-manifest.js'
            file.parent.mkdir();file.write_text('function accountLogout(){}')
            files = list(source_files(td))
            self.assertEqual(len(files), 1)
            self.assertTrue(inspect_ui(*files[0]))

    def test_built_payload_is_checked_independently(self):
        with tempfile.TemporaryDirectory() as td:
            wheel = Path(td) / 'core.whl'
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('runteams_core/_resources/web/hidden.js', 'function subscriptionPlans(){}')
            with self.assertRaises(ValueError):
                check_wheel(wheel)

    def test_private_directory_cannot_hide_behind_a_clean_shared_payload(self):
        with tempfile.TemporaryDirectory() as td:
            wheel = Path(td) / 'core.whl'
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('runteams_core/_resources/web/ui/host.js', 'const host={};')
                archive.writestr('runteams_official/ui/extra.js', '')
            with self.assertRaises(ValueError):
                check_wheel(wheel)

    def test_core_wheel_accepts_only_its_own_route_contract(self):
        with tempfile.TemporaryDirectory() as td:
            wheel = Path(td) / 'core.whl'
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('runteams_core/_resources/web/ui/host.js', 'const host={};')
                archive.writestr('runteams_core/_resources/contracts/page-routes.json', json.dumps({'routes':[{'public':'/billing'}]}))
            with self.assertRaises(ValueError):
                check_wheel(wheel)


if __name__ == '__main__':
    unittest.main()
