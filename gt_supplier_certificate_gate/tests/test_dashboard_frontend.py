from odoo.tests import tagged
from odoo.addons.web.tests.test_js import HootCommon, unit_test_error_checker


@tagged('post_install', '-at_install', 'gt_phase5_frontend')
class TestDashboardHoot(HootCommon):
    def test_dashboard_hoot(self):
        module_filter = self._generate_hash('@gt_supplier_certificate_gate')
        self.browser_js('/web/tests?headless&loglevel=2&preset=desktop&timeout=15000&id=' + module_filter, '', '', login='admin', timeout=180, success_signal='[HOOT] Test suite succeeded', error_checker=unit_test_error_checker)
