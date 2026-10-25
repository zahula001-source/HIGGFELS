"""AlgoData OFF must leave 1ClickVPN available."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import browser, browser_settings
from app.api import video
from app.services import video_gen

class AlgoDataOffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vpn_toggle_', dir=browser.DATA_DIR)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        config = self.root / 'config.json'
        config.write_text(json.dumps({'disable_algodata': True}), encoding='utf-8')
        setting = patch.object(browser_settings, 'CONFIG_PATH', config)
        setting.start()
        self.addCleanup(setting.stop)

    def test_algo_off_uses_direct_connection_unless_sinh_ip_is_checked(self):
        self.assertIsNone(browser_settings.get_algo_proxy('test'))
        for engine in ('chrome', 'cloakbrowser'):
            self.assertIn('--no-proxy-server', browser_settings.get_global_args(engine=engine))
            self.assertNotIn('--no-proxy-server', browser_settings.get_global_args(engine=engine, generate_ip=True))

    def test_create_video_keeps_checked_sinh_ip(self):
        from starlette.datastructures import FormData
        class Request:
            async def form(self):
                return FormData({'prompt':'test', 'profile_id':'vpn-test', 'generate_ip':'true'})
        with patch.object(video, 'list_running', return_value={}), patch.object(video.threading, 'Thread') as thread, patch.dict(video.video_tasks, {}, clear=True):
            result = asyncio.run(video.create_video(Request()))
            self.assertTrue(video.video_tasks[result['task_id']]['params']['generate_ip'])
            self.assertTrue(thread.call_args.kwargs['args'][-1])

    def test_video_network_connects_1clickvpn(self):
        task = {'params': {'generate_ip': True}}
        context = Mock()
        with patch.dict(video_gen.video_tasks, {'vpn-test':task}), patch('app.services.vpn_ip.connect_unique_vpn_ip', return_value={'ip':'1.2.3.4','country':'Japan'}) as connect:
            video_gen._prepare_video_network(context, 'vpn-test', 'p', True)
            connect.assert_called_once_with(context, 'p')
            self.assertTrue(task['vpn_enabled'])

    def test_launcher_allows_only_selected_1clickvpn(self):
        for name in ('1clickvpn', 'hola-vpn', 'urbanvpn'):
            folder = self.root / 'extensions' / name
            folder.mkdir(parents=True)
            (folder / 'manifest.json').write_text(json.dumps({'key':name, 'permissions':['proxy']}), encoding='utf-8')
        profile = SimpleNamespace(id='test', name='Test', user_data_dir=str(self.root / 'profile'), fingerprint={}, extensions='')
        for engine in ('chrome', 'cloakbrowser'):
            pw = Mock()
            with patch.object(video_gen, 'DATA_DIR', self.root), patch('app.browser.prepare_chrome_136_profile', return_value=profile.user_data_dir), patch('app.extensions.resolve_extension_paths', return_value=[]), patch.object(video_gen, 'browser_launch_options', return_value={}), patch.object(video_gen, 'install_vpn_welcome_guard'), patch.object(video_gen, 'install_upgrade_plan_guard'), patch('time.sleep'):
                video_gen._open_browser_with_fp(pw, profile, None, engine=engine, generate_ip=True, reuse_existing=False)
            options = pw.chromium.launch_persistent_context.call_args.kwargs
            self.assertIsNone(options['proxy'])
            self.assertNotIn('--no-proxy-server', options['args'])
            self.assertNotIn('direct_connection', ' '.join(options['args']))
            loaded = next(arg for arg in options['args'] if arg.startswith('--load-extension='))
            self.assertIn(str((self.root / 'extensions' / '1clickvpn').resolve()), loaded)
            self.assertIn(str((self.root / 'extensions' / 'urbanvpn').resolve()), loaded)
            self.assertNotIn(str((self.root / 'extensions' / 'hola-vpn').resolve()), loaded)

    def test_launcher_without_sinh_ip_blocks_other_proxy_extensions(self):
        folder = self.root / 'extensions' / 'old-proxy'
        folder.mkdir(parents=True)
        (folder / 'manifest.json').write_text(json.dumps({'permissions':['proxy']}), encoding='utf-8')
        profile = SimpleNamespace(id='test-direct', name='Test', user_data_dir=str(self.root / 'profile'), fingerprint={}, extensions='')
        pw = Mock()
        with patch.object(video_gen, 'DATA_DIR', self.root), patch('app.browser.prepare_chrome_136_profile', return_value=profile.user_data_dir), patch('app.extensions.resolve_extension_paths', return_value=[str(folder)]), patch.object(video_gen, 'browser_launch_options', return_value={}), patch.object(video_gen, 'install_vpn_welcome_guard'), patch.object(video_gen, 'install_upgrade_plan_guard'), patch('time.sleep'):
            video_gen._open_browser_with_fp(pw, profile, None, engine='chrome', generate_ip=False, reuse_existing=False)
        options = pw.chromium.launch_persistent_context.call_args.kwargs
        self.assertIsNone(options['proxy'])
        self.assertIn('--no-proxy-server', options['args'])
        self.assertNotIn(str(folder), ' '.join(options['args']))

    def test_extension_filter_keeps_normal_extensions_and_copied_1click(self):
        paths = []
        for name, data in (
            ('1clickvpn', {'key':'oneclick-key', 'permissions':['proxy']}),
            ('copied-oneclick', {'key':'oneclick-key', 'permissions':['proxy']}),
            ('normal', {'permissions':['storage']}),
            ('optional-proxy', {'optional_permissions':['proxy']}),
        ):
            folder = self.root / 'extensions' / name
            folder.mkdir(parents=True)
            (folder / 'manifest.json').write_text(json.dumps(data), encoding='utf-8')
            paths.append(str(folder))
        self.assertEqual(browser_settings.filter_proxy_extensions(paths), [paths[0], paths[2]])
        self.assertEqual(browser_settings.filter_proxy_extensions(paths, generate_ip=True), [paths[0], paths[2]])

    def test_sinh_ip_off_keeps_1click_installed_and_pinned(self):
        from app.extensions import ONECLICK_EXTENSION_ID
        folder = self.root / 'extensions' / '1clickvpn'
        folder.mkdir(parents=True)
        (folder / 'manifest.json').write_text(json.dumps({'permissions':['proxy']}), encoding='utf-8')
        runtime = self.root / 'profile'
        profile = SimpleNamespace(id='oneclick-visible', name='Test', user_data_dir=str(runtime), fingerprint={}, extensions='')
        pw = Mock()
        with patch.object(video_gen, 'DATA_DIR', self.root), patch('app.browser.prepare_chrome_136_profile', return_value=str(runtime)), patch('app.extensions.resolve_extension_paths', return_value=[]), patch.object(video_gen, 'browser_launch_options', return_value={}), patch.object(video_gen, 'install_vpn_welcome_guard'), patch.object(video_gen, 'install_upgrade_plan_guard'), patch('time.sleep'):
            video_gen._open_browser_with_fp(pw, profile, None, engine='chrome', generate_ip=False, reuse_existing=False)
        options = pw.chromium.launch_persistent_context.call_args.kwargs
        self.assertIn('--no-proxy-server', options['args'])
        loaded = next(arg for arg in options['args'] if arg.startswith('--load-extension='))
        self.assertIn(str(folder.resolve()), loaded)
        self.assertIn('direct_connection', loaded)
        prefs = json.loads((runtime / 'Default' / 'Preferences').read_text(encoding='utf-8'))
        self.assertIn(ONECLICK_EXTENSION_ID, prefs['extensions']['pinned_extensions'])

    def test_pin_uses_extension_id_and_preserves_existing_preferences(self):
        from app.extensions import ONECLICK_EXTENSION_ID, pin_oneclick_extension
        runtime = self.root / 'pin-profile'
        preferences = runtime / 'Default' / 'Preferences'
        preferences.parent.mkdir(parents=True)
        original = {'profile':{'name':'Existing profile'}, 'extensions':{'pinned_extensions':['other-extension','1clickvpn']}, 'unrelated':True}
        preferences.write_text(json.dumps(original), encoding='utf-8')
        pin_oneclick_extension(runtime)
        pin_oneclick_extension(runtime)
        updated = json.loads(preferences.read_text(encoding='utf-8'))
        self.assertEqual(updated['extensions']['pinned_extensions'], ['other-extension',ONECLICK_EXTENSION_ID])
        self.assertEqual(updated['profile'], original['profile'])
        self.assertTrue(updated['unrelated'])

    def test_existing_runner_with_matching_network_is_reused(self):
        proc = SimpleNamespace(network_mode='direct', pid=123, poll=lambda: None)
        profile = SimpleNamespace(id='owned')
        with patch.dict(browser.running_browsers, {'owned':proc}, clear=True), patch.object(browser, 'close_profile') as close:
            result = browser._launch_profile(profile)
        self.assertEqual(result, {'status':'already_running','pid':123})
        close.assert_not_called()

    def test_existing_runner_with_old_proxy_requires_relaunch_before_signup(self):
        proc = SimpleNamespace(network_mode='algodata', pid=123, poll=lambda: None)
        profile = SimpleNamespace(id='owned')
        with patch.dict(browser.running_browsers, {'owned':proc}, clear=True), patch.object(browser, 'launch_profile_with_fallback', return_value={'status':'launched'}) as launch:
            browser.ensure_profile_network_mode(profile, generate_ip=False, engine='chrome')
        launch.assert_called_once()
        self.assertFalse(launch.call_args.args[1].generate_ip)

    def test_failed_network_relaunch_stops_instead_of_reusing_old_proxy(self):
        proc = SimpleNamespace(network_mode='algodata', pid=123, poll=lambda: None)
        profile = SimpleNamespace(id='owned')
        with patch.dict(browser.running_browsers, {'owned':proc}, clear=True), patch.object(browser, 'launch_profile_with_fallback', return_value={'status':'error','message':'runner cannot stop'}):
            with self.assertRaisesRegex(RuntimeError, 'runner cannot stop'):
                browser.ensure_profile_network_mode(profile)

    def test_launch_rejects_old_runner_if_it_cannot_be_stopped(self):
        proc = SimpleNamespace(network_mode='algodata', pid=123, poll=lambda: None)
        profile = SimpleNamespace(id='owned')
        with patch.dict(browser.running_browsers, {'owned':proc}, clear=True), patch.object(browser, 'close_profile', return_value={'status':'error','message':'cannot stop'}) as close:
            result = browser._launch_profile(profile)
        self.assertEqual(result['status'], 'error')
        close.assert_called_once_with('owned')

    def test_generated_runner_discards_stale_proxy_when_off(self):
        import io
        import os
        from contextlib import redirect_stdout
        root = self.root / 'runner-profile'
        root.mkdir()
        oneclick = self.root / 'extensions' / '1clickvpn'
        oneclick.mkdir(parents=True)
        (oneclick / 'manifest.json').write_text(json.dumps({'permissions':['proxy']}), encoding='utf-8')
        code = browser.get_chromium_runner_simple('test-runner', 'Test', str(root),
            {'server':'http://127.0.0.1:8080','username':'test','password':'test'}, {}, engine='chrome')
        code = code.replace('global_ext_dir = Path(__file__).parent.parent / "data" / "extensions"',
                            f'global_ext_dir = Path({str(self.root / "extensions")!r})')
        prefix = code[:code.index('    log("Launching browser...")')]
        prefix += '\nfinally:\n    if runner_lock: runner_lock.close()\n'
        namespace = {'__file__': str(browser.DATA_DIR / 'runner_test.py')}
        with patch('playwright.sync_api.sync_playwright'), patch.dict(os.environ), redirect_stdout(io.StringIO()):
            exec(compile(prefix, 'isolated-runner-policy', 'exec'), namespace)
        self.assertIsNone(namespace['proxy'])
        self.assertIn('--no-proxy-server', namespace['launch_args']['args'])
        self.assertNotIn('proxy', namespace['launch_args'])
        self.assertTrue(namespace['launch_args']['extension_paths'])
        self.assertIn(str(oneclick.resolve()), namespace['launch_args']['extension_paths'])
        self.assertIn('direct_connection', namespace['launch_args']['extension_paths'][-1])


class ProxyOffBrowserTests(unittest.TestCase):
    setUp = AlgoDataOffTests.setUp

    def test_actual_1click_bundle_loads_when_sinh_ip_is_off(self):
        from playwright.sync_api import sync_playwright
        from app.extensions import ONECLICK_EXTENSION_ID
        real_extension = browser.DATA_DIR / 'extensions' / '1clickvpn'
        manifest = json.loads((real_extension / 'manifest.json').read_text(encoding='utf-8-sig'))
        # Identify the shipped bundle under the isolated test config root.
        fixture = self.root / 'extensions' / '1clickvpn'
        fixture.mkdir(parents=True)
        (fixture / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        runtime = self.root / 'actual-oneclick-profile'
        profile = SimpleNamespace(id='actual-oneclick-visible', name='Test', user_data_dir=str(runtime), fingerprint={}, extensions='')
        with sync_playwright() as pw:
            original_launch = pw.chromium.launch_persistent_context
            def offline_headless_launch(*args, **kwargs):
                kwargs['headless'] = True
                kwargs['args'].append('--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost')
                return original_launch(*args, **kwargs)
            with patch.object(video_gen, 'DATA_DIR', self.root), patch('app.browser.prepare_chrome_136_profile', return_value=str(runtime)), patch('app.extensions.resolve_extension_paths', return_value=[str(real_extension)]), patch.object(pw.chromium, 'launch_persistent_context', side_effect=offline_headless_launch):
                context, _ = video_gen._open_browser_with_fp(pw, profile, None, engine='chrome', generate_ip=False, reuse_existing=False)
            try:
                worker = next((w for w in context.service_workers if ONECLICK_EXTENSION_ID in w.url), None)
                if worker is None:
                    worker = context.wait_for_event('serviceworker', predicate=lambda w: ONECLICK_EXTENSION_ID in w.url, timeout=10000)
                popup = context.new_page()
                popup.goto(f'chrome-extension://{ONECLICK_EXTENSION_ID}/popup/index.html', wait_until='domcontentloaded')
                self.assertEqual(popup.evaluate('chrome.runtime.id'), ONECLICK_EXTENSION_ID)
                self.assertIn('1ClickVPN', popup.evaluate('chrome.runtime.getManifest().name'))
            finally:
                context.close()
        prefs = json.loads((runtime / 'Default' / 'Preferences').read_text(encoding='utf-8'))
        self.assertIn(ONECLICK_EXTENSION_ID, prefs['extensions']['pinned_extensions'])

    def test_restored_auth_proxy_extension_is_not_used_when_off(self):
        from playwright.sync_api import sync_playwright
        proxy_requests = []

        class Origin(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'direct connection works'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass

        class AuthProxy(BaseHTTPRequestHandler):
            def do_GET(self):
                proxy_requests.append(self.path)
                self.send_response(407)
                self.send_header('Proxy-Authenticate', 'Basic realm="proxy regression"')
                self.send_header('Content-Length', '0')
                self.end_headers()
            do_CONNECT = do_GET
            def log_message(self, *args):
                pass

        servers = []
        for handler in (Origin, AuthProxy):
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            servers.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        origin, proxy = servers
        address = f'http://127.0.0.1:{origin.server_port}/'
        extension = self.root / 'extensions' / 'old-auth-proxy'
        extension.mkdir(parents=True)
        (extension / 'manifest.json').write_text(json.dumps({
            'manifest_version':3, 'name':'Old auth proxy regression', 'version':'1.0',
            'permissions':['proxy'], 'background':{'service_worker':'background.js'},
        }), encoding='utf-8')
        proxy_script = 'chrome.proxy.settings.set({value:{mode:"fixed_servers",rules:{singleProxy:{scheme:"http",host:"127.0.0.1",port:' + str(proxy.server_port) + '},bypassList:["<-loopback>"]}},scope:"regular"});'
        (extension / 'background.js').write_text(proxy_script, encoding='utf-8')
        from app.extensions import ONECLICK_PUBLIC_KEY, ONECLICK_EXTENSION_ID
        oneclick = self.root / 'extensions' / '1clickvpn'
        oneclick.mkdir(parents=True)
        (oneclick / 'manifest.json').write_text(json.dumps({
            'manifest_version':3, 'name':'1ClickVPN regression fixture', 'version':'1.0',
            'key':ONECLICK_PUBLIC_KEY, 'permissions':['proxy'], 'background':{'service_worker':'background.js'},
        }), encoding='utf-8')
        (oneclick / 'background.js').write_text(proxy_script, encoding='utf-8')
        runtime = self.root / 'profile'
        with sync_playwright() as pw:
            # Reproduce a saved profile whose proxy would request credentials.
            primed = pw.chromium.launch_persistent_context(str(runtime), headless=True,
                executable_path=str(browser_settings.ensure_chrome_extension_binary()),
                ignore_default_args=['--disable-extensions'],
                args=['--disable-extensions-except='+str(extension), '--load-extension='+str(extension)])
            try:
                page = primed.pages[0]
                worker = primed.service_workers[0] if primed.service_workers else primed.wait_for_event('serviceworker')
                worker.evaluate('() => new Promise(resolve => { ' + proxy_script.replace('});', '}, resolve);') + ' })')
                try:
                    page.goto(address, timeout=2500)
                except Exception:
                    pass
                self.assertTrue(proxy_requests, 'The fixture must first reproduce the auth proxy')
            finally:
                primed.close()
            proxy_requests.clear()
            profile = SimpleNamespace(id='auth-proxy-test', name='Test', user_data_dir=str(runtime), fingerprint={}, extensions='')
            original_launch = pw.chromium.launch_persistent_context
            def headless_launch(*args, **kwargs):
                kwargs['headless'] = True
                return original_launch(*args, **kwargs)
            with patch.object(video_gen, 'DATA_DIR', self.root), patch('app.browser.prepare_chrome_136_profile', return_value=str(runtime)), patch('app.extensions.resolve_extension_paths', return_value=[str(extension)]), patch.object(pw.chromium, 'launch_persistent_context', side_effect=headless_launch):
                context, reused = video_gen._open_browser_with_fp(pw, profile, None, engine='chrome', generate_ip=False, reuse_existing=False)
            try:
                self.assertFalse(reused)
                worker = next((w for w in context.service_workers if ONECLICK_EXTENSION_ID in w.url), None)
                if worker is None:
                    worker = context.wait_for_event('serviceworker', predicate=lambda w: ONECLICK_EXTENSION_ID in w.url)
                self.assertIn(ONECLICK_EXTENSION_ID, worker.url)
                worker.evaluate('() => new Promise(resolve => { ' + proxy_script.replace('});', '}, resolve);') + ' })')
                page = context.new_page()
                page.goto(address, timeout=5000)
                self.assertEqual(page.locator('body').inner_text(), 'direct connection works')
                self.assertEqual(proxy_requests, [])
            finally:
                context.close()
            prefs = json.loads((runtime / 'Default' / 'Preferences').read_text(encoding='utf-8'))
            self.assertIn(ONECLICK_EXTENSION_ID, prefs['extensions']['pinned_extensions'])

class FrontendVpnTests(unittest.TestCase):
    def test_launch_waits_for_proxy_save_and_stops_if_save_fails(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory(prefix='proxy_save_ui_', dir=browser.DATA_DIR) as folder, sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(folder, executable_path=str(browser_settings.ensure_chrome_extension_binary()), headless=True)
            try:
                page = context.pages[0]
                page.route('http://proxy-ui.test/**', lambda route: route.fulfill(status=200, body='<html></html>'))
                page.goto('http://proxy-ui.test/')
                page.set_content('<input id="globalGenerateIp" type="checkbox"><input id="globalDisableAlgoData" type="checkbox" checked>')
                html = (browser.BASE_DIR / 'static' / 'index.html').read_text(encoding='utf-8')
                page.add_script_tag(content=html[html.index('function restoreOneClickVpnToggle()'):html.index('async function loadProfiles(){')])
                page.add_script_tag(content=html[html.index('async function launchProfile('):html.index('async function checkFreeGenProfile(')])
                page.evaluate('''() => {
                    window.requests=[];window.saveFailed=false;
                    window.alert=()=>{};window.loadProfiles=()=>{};
                    window.fetch=async (url, opts) => {
                        window.requests.push(url);
                        if (url === '/api/config') {
                            await new Promise(resolve => window.finishSave=resolve);
                            return {ok:!window.saveFailed,json:async()=>({ok:!window.saveFailed})};
                        }
                        return {ok:true,json:async()=>({ok:true,pid:123})};
                    };
                    updateBackendConfig();window.launch=launchProfile('test');
                }''')
                page.wait_for_timeout(50)
                self.assertEqual(page.evaluate('window.requests'), ['/api/config'])
                page.evaluate('window.finishSave();window.launch')
                self.assertEqual(page.evaluate('window.requests'), ['/api/config','/api/profiles/test/launch-manual'])
                page.evaluate('''() => {
                    window.requests=[];window.saveFailed=true;
                    updateBackendConfig();window.launch=launchProfile('test');
                }''')
                page.wait_for_timeout(50)
                page.evaluate('window.finishSave();window.launch')
                self.assertEqual(page.evaluate('window.requests'), ['/api/config'])
            finally:
                context.close()

    def test_sinh_ip_off_is_preserved_and_can_be_explicitly_enabled(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory(prefix='vpn_ui_', dir=browser.DATA_DIR) as folder, sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(folder, executable_path=str(browser_settings.ensure_chrome_extension_binary()), headless=True)
            try:
                page = context.pages[0]
                page.route('http://vpn-ui.test/**', lambda route: route.fulfill(status=200, body='<html></html>'))
                page.goto('http://vpn-ui.test/')
                page.set_content('''<div><input id="globalGenerateIp" type="checkbox" disabled></div>
                    <input id="globalDisableAlgoData" type="checkbox" checked>
                    <input id="globalLightweightCache" type="checkbox"><input id="globalBlockMedia" type="checkbox">
                    <textarea id="videoPrompt_t">test</textarea><input id="videoProfileId_t" value="test">
                    <input id="videoDuration_t"><input id="videoRatio_t"><input id="videoGenMode_t" value="motion_transfer">
                    <button id="createVideoBtn_t"></button>''')
                page.evaluate('''() => {
                    localStorage.setItem('globalGenerateIp', 'false');
                    localStorage.setItem('antidetect_video_state', JSON.stringify({globalGenerateIp:false,cards:[{prompt:'keep'}]}));
                    window.alert = () => {};
                    window.fetch = async (url, opts) => {
                        if (url === '/api/video/create') {
                            window.sentGenerateIp = opts.body.get('generate_ip');
                            return {ok:false, json:async()=>({detail:'isolated test'})};
                        }
                        return {ok:true, json:async()=>({disable_algodata:true})};
                    };
                }''')
                html = (browser.BASE_DIR / 'static' / 'index.html').read_text(encoding='utf-8')
                page.add_script_tag(content=html[html.index('function restoreOneClickVpnToggle()'):html.index('async function loadProfiles(){')])
                start = html.index('async function startVideoCreationDynamic(')
                page.add_script_tag(content=html[start:html.index('async function pollTaskStatusDynamic(', start)])
                page.evaluate('loadBackendConfig()')
                self.assertFalse(page.locator('#globalGenerateIp').is_disabled())
                self.assertFalse(page.locator('#globalGenerateIp').is_checked())
                self.assertEqual(page.evaluate("localStorage.getItem('globalGenerateIp')"), 'false')
                self.assertEqual(page.evaluate("JSON.parse(localStorage.getItem('antidetect_video_state')).cards[0].prompt"), 'keep')
                page.evaluate("startVideoCreationDynamic('t')")
                self.assertEqual(page.evaluate('window.sentGenerateIp'), 'false')
                page.locator('#globalGenerateIp').check()
                page.evaluate("startVideoCreationDynamic('t')")
                self.assertEqual(page.evaluate('window.sentGenerateIp'), 'true')
                page.locator('#globalGenerateIp').uncheck()
                page.evaluate('loadBackendConfig()')
                self.assertFalse(page.locator('#globalGenerateIp').is_checked())
                print('PASS: AlgoData OFF leaves Sinh IP available; Create Video sends generate_ip=true', flush=True)
            finally:
                context.close()

if __name__ == '__main__':
    unittest.main(verbosity=2)
