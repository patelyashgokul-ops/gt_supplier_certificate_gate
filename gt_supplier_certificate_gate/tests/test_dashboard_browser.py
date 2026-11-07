import base64
import json
from pathlib import Path
from unittest.mock import patch
from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tests.common import ChromeBrowser
from .test_lifecycle import pdf_content


@tagged('post_install', '-at_install', 'gt_phase5_browser')
class TestDashboardBrowser(HttpCase):
    browser_size = '1440,1100'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'Browser private company'})
        def user(login, groups):
            return cls.env['res.users'].create({'name': login, 'login': login, 'password': login, 'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)], 'group_ids': [Command.set([cls.env.ref(g).id for g in groups])]})
        cls.buyer = user('gt_dashboard_buyer', ['purchase.group_purchase_user'])
        cls.submitter = user('gt_dashboard_submitter', ['gt_supplier_certificate_gate.group_user'])
        cls.reviewer = user('gt_dashboard_reviewer', ['gt_supplier_certificate_gate.group_reviewer'])
        cls.vendor = cls.env['res.partner'].create({'name': 'Shree Packaging - Browser QA'})
        cls.kind = cls.env['gt.certificate.type'].create({'name': 'Food Safety Browser', 'code': 'BROWSER_FOOD'})
        cls.other = cls.env['gt.certificate.type'].create({'name': 'ISO 9001 Browser', 'code': 'BROWSER_ISO'})
        cls.category = cls.env['product.category'].create({'name': 'Food Packaging - Browser QA'})
        for kind in (cls.kind, cls.other):
            cls.env['gt.certificate.requirement'].create({'company_id': cls.company.id, 'category_id': cls.category.id, 'type_id': kind.id})
        cls.product = cls.env['product.product'].create({'name': 'Food Grade Pouch - Browser QA', 'categ_id': cls.category.id})
        today = cls.company._gt_today()
        from datetime import timedelta
        cls.cert = cls.env['gt.supplier.certificate'].with_user(cls.submitter).create({'company_id': cls.company.id, 'supplier_id': cls.vendor.id, 'type_id': cls.kind.id, 'reference': 'BROWSER-RESTRICTED', 'valid_from': str(today), 'valid_until': str(today + timedelta(days=365))})
        cls.env['gt.certificate.upload'].with_user(cls.submitter).create({'certificate_id': cls.cert.id, 'data': pdf_content()})
        cls.cert.with_user(cls.reviewer).action_approve()
        cls.order = cls.env['purchase.order'].with_user(cls.buyer).create({'partner_id': cls.vendor.id, 'order_line': [Command.create({'product_id': cls.product.id, 'product_qty': 1, 'name': cls.product.name}), Command.create({'product_id': cls.product.id, 'product_qty': 2, 'name': cls.product.name})]})
        cls.pending = cls.env['gt.supplier.certificate'].with_user(cls.submitter).create({'company_id': cls.company.id, 'supplier_id': cls.vendor.id, 'type_id': cls.other.id, 'reference': 'BROWSER-PENDING', 'valid_from': str(today), 'valid_until': str(today + timedelta(days=365))})
        cls.env['gt.certificate.upload'].with_user(cls.submitter).create({'certificate_id': cls.pending.id, 'data': pdf_content()})

    def test_buyer_dashboard_real_data_drilldown_filters_and_responsive(self):
        original = ChromeBrowser._wait_code_ok
        evidence = []
        def run_and_capture(browser, code, timeout, **kwargs):
            result = original(browser, code, timeout, **kwargs)
            folder = Path('.development/phase5-qa')
            folder.mkdir(exist_ok=True)
            for label, width, height in [('desktop', 1440, 1100), ('tablet', 900, 1100), ('mobile', 390, 844)]:
                browser._websocket_request('Emulation.setDeviceMetricsOverride', params={'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': label == 'mobile'})
                metrics = browser._websocket_request('Runtime.evaluate', params={'expression': "new Promise(resolve => setTimeout(() => { const root = document.querySelector('.gt-dashboard'); const grid = root.querySelector('.gt-kpis'); resolve({width: innerWidth, dashboardWidth: root.clientWidth, scrollWidth: root.scrollWidth, columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length, cards: grid.children.length}); }, 300))", 'awaitPromise': True, 'returnByValue': True})['result']['value']
                self.assertLessEqual(metrics['scrollWidth'], metrics['dashboardWidth'] + 2)
                self.assertEqual(metrics['cards'], 5)
                self.assertEqual(metrics['columns'], 1 if label == 'mobile' else 3 if label == 'tablet' else 5)
                image = browser._websocket_request('Page.captureScreenshot', params={'format': 'png'})
                (folder / ('dashboard-' + label + '.png')).write_bytes(base64.b64decode(image['data']))
                evidence.append({'viewport': label, **metrics})
            browser._websocket_request('Runtime.evaluate', params={'expression': "document.querySelector('.gt-refresh').focus()"})
            browser._websocket_request('Input.dispatchKeyEvent', params={'type': 'keyDown', 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9})
            browser._websocket_request('Input.dispatchKeyEvent', params={'type': 'keyUp', 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9})
            focused = browser._websocket_request('Runtime.evaluate', params={'expression': "document.activeElement.classList.contains('gt-filter-toggle')", 'returnByValue': True})['result']['value']
            self.assertTrue(focused)
            for kind in ('keyDown', 'keyUp'):
                browser._websocket_request('Input.dispatchKeyEvent', params={'type': kind, 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13, 'text': '\r' if kind == 'keyDown' else ''})
            browser._websocket_request('Runtime.evaluate', params={'expression': 'new Promise(r => setTimeout(r, 100))', 'awaitPromise': True})
            for kind in ('keyDown', 'keyUp'):
                browser._websocket_request('Input.dispatchKeyEvent', params={'type': kind, 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9})
            keyboard = browser._websocket_request('Runtime.evaluate', params={'expression': "({name:document.activeElement.name, element:document.activeElement.outerHTML, expanded:document.querySelector('.gt-filter-toggle').getAttribute('aria-expanded'), filters:document.querySelector('.gt-filters').className})", 'returnByValue': True})['result']['value']
            (folder / 'keyboard-results.json').write_text(json.dumps(keyboard, indent=2), encoding='utf-8')
            self.assertEqual(keyboard['name'], 'company_id', str(keyboard))
            (folder / 'responsive-results.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
            return result
        code = r'''(async () => {
            const wait = async (selector, predicate = () => true) => {
                for (let i = 0; i < 150; i++) {
                    const node = document.querySelector(selector);
                    if (node && predicate(node)) return node;
                    await new Promise(r => setTimeout(r, 100));
                }
                throw new Error('Timed out waiting for ' + selector);
            };
            const assert = (ok, text) => { if (!ok) throw new Error(text); };
            await wait('.gt-kpi strong', el => el.textContent.trim() === '1');
            assert(document.querySelectorAll('.gt-kpi').length === 5, 'Five real KPI cards required');
            assert(document.querySelector('.gt-kpi:nth-child(4) strong').textContent.trim() === '1', 'One actual pending submission expected');
            document.querySelector('.gt-kpi').click();
            const row = await wait('.o_data_row', el => el.textContent.includes(ORDER_NAME));
            row.querySelector('td.o_data_cell').click();
            await wait('.o_form_view');
            const tab = [...document.querySelectorAll('.nav-link')].find(el => el.textContent.includes('Certificate Check'));
            assert(tab, 'Certificate check notebook must exist'); tab.click();
            await wait('[name="gt_current_details"]', el => el.textContent.includes('ISO 9001 Browser'));
            assert(!document.querySelector('button[name="action_evidence"]'), 'Buyer PO must not expose evidence download');
            const denied = await fetch(EVIDENCE_URL);
            assert([403,404].includes(denied.status), 'Buyer evidence content route must be denied');
            const rpc = await fetch('/web/dataset/call_kw', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({jsonrpc:'2.0',id:1,method:'call',params:{model:'gt.certificate.dashboard',method:'get_data',args:[{company_id:FOREIGN_COMPANY}],kwargs:{}}})});
            assert((await rpc.json()).error, 'Unauthorized company dashboard RPC must fail');
            window.history.back(); await wait('.o_list_view');
            window.history.back(); await wait('.gt-dashboard .gt-kpi strong', el => el.textContent.trim() === '1');
            const company = document.querySelector('select[name="company_id"]');
            company.value = String(OWN_COMPANY); company.dispatchEvent(new Event('change', {bubbles:true}));
            await new Promise(r => setTimeout(r, 500));
            await wait('.gt-dashboard .gt-kpi strong', el => el.textContent.trim() === '1');
            assert(document.querySelector('select[name="company_id"]').value === String(OWN_COMPANY), 'Authorized company filter must persist');
            console.log('test successful');
        })();'''
        code = code.replace('ORDER_NAME', json.dumps(self.order.name)).replace('EVIDENCE_URL', json.dumps('/web/content/gt.certificate.evidence/%s/data?download=true' % self.cert.evidence_id.id)).replace('FOREIGN_COMPANY', str(self.other_company.id)).replace('OWN_COMPANY', str(self.company.id))
        with patch.object(ChromeBrowser, '_wait_code_ok', run_and_capture):
            self.browser_js('/odoo/action-' + str(self.env.ref('gt_supplier_certificate_gate.action_dashboard').id), code, login=self.buyer.login, timeout=120)

    def test_reviewer_queue_and_secure_existing_review_workflow(self):
        code = r'''(async () => {
            const wait = async (selector, predicate = () => true) => { for(let i=0;i<150;i++){const n=document.querySelector(selector);if(n && predicate(n))return n;await new Promise(r=>setTimeout(r,100));}throw new Error('Missing '+selector); };
            await wait('.gt-review-button', n => n.textContent.includes('Open reviewer queue'));
            document.querySelector('.gt-review-button').click();
            const row = await wait('.o_data_row', n => n.textContent.includes('BROWSER-PENDING'));
            row.querySelector('td.o_data_cell').click();
            await wait('button[name="action_approve"]');
            if (!document.querySelector('button[name="action_evidence"]')) throw new Error('Reviewer download action absent');
            const response = await fetch(EVIDENCE_URL);
            if(response.status !== 200 || !(await response.text()).startsWith('%PDF-')) throw new Error('Authorized reviewer download failed');
            console.log('test successful');
        })();'''.replace('EVIDENCE_URL', json.dumps('/web/content/gt.certificate.evidence/%s/data?download=true' % self.pending.evidence_id.id))
        self.browser_js('/odoo/action-' + str(self.env.ref('gt_supplier_certificate_gate.action_dashboard').id), code, login=self.reviewer.login, timeout=120)

    def test_native_dark_theme_remains_readable(self):
        original = ChromeBrowser._wait_code_ok
        def capture(browser, code, timeout, **kwargs):
            result = original(browser, code, timeout, **kwargs)
            metrics = browser._websocket_request('Runtime.evaluate', params={'expression': """(() => {
                const color = (element, prop) => getComputedStyle(element)[prop];
                const luminance = css => css.match(/[\d.]+/g).slice(0,3).map(Number).map(v => {v/=255; return v<=0.04045 ? v/12.92 : ((v+0.055)/1.055)**2.4;}).reduce((sum,v,i)=>sum+v*[0.2126,0.7152,0.0722][i],0);
                const card=document.querySelector('.gt-kpi'); const guide=document.querySelector('.gt-guide');
                const ratio=(fg,bg)=>{const a=luminance(fg), b=luminance(bg);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);};
                return {cookie:document.cookie.includes('color_scheme=dark'), cardForeground:color(card,'color'),cardBackground:color(card,'backgroundColor'),cardContrast:ratio(color(card,'color'),color(card,'backgroundColor')),guideContrast:ratio(color(guide.querySelector('h2'),'color'),color(guide,'backgroundColor'))};
            })()""", 'returnByValue': True})['result']['value']
            self.assertTrue(metrics['cookie'])
            self.assertNotEqual(metrics['cardBackground'], 'rgb(255, 255, 255)')
            self.assertGreaterEqual(metrics['cardContrast'], 4.5)
            self.assertGreaterEqual(metrics['guideContrast'], 4.5)
            folder=Path('.development/phase5-qa');folder.mkdir(exist_ok=True)
            (folder/'dark-theme-results.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
            screen=browser._websocket_request('Page.captureScreenshot',params={'format':'png'})
            (folder/'dashboard-dark.png').write_bytes(base64.b64decode(screen['data']))
            return result
        code="""(async()=>{for(let i=0;i<150;i++){if(document.querySelectorAll('.gt-kpi').length===5){console.log('test successful');return;}await new Promise(r=>setTimeout(r,100));}throw new Error('Dark dashboard did not load');})();"""
        with patch.object(ChromeBrowser, '_wait_code_ok', capture):
            self.browser_js('/odoo/action-'+str(self.env.ref('gt_supplier_certificate_gate.action_dashboard').id),code,login=self.buyer.login,cookies={'color_scheme':'dark'},timeout=120)
