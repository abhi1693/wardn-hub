"""Exercise final images offline with disposable configuration and no real services.

The shared workflow runs this on the matching native CPU after its strict scan.
Never bind a real CODEX_HOME, database, registry, or credentials into these tests.
"""

import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

POLICY = json.loads(Path(__file__).with_name("runtime-policy.json").read_text())
PYTHON_RUNTIME = r"""
import bz2, ctypes, curses, dbm.gnu, dbm.ndbm, hashlib, importlib.util, json
import lzma, pathlib, readline, sqlite3, ssl, subprocess, sys, tempfile, uuid, venv
p = json.loads(sys.argv[1])
assert sys.version.split()[0] == p['python'], 'Python version mismatch'
roots = ssl.create_default_context().get_ca_certs(binary_form=True)
assert roots, 'Empty Python trust store'
if importlib.util.find_spec('certifi') is not None:
    import certifi
    extra = ssl.create_default_context(cafile=certifi.where()).get_ca_certs(binary_form=True)
    assert extra, 'Empty HTTP client trust store'
    roots += extra
assert not set(p['distrusted_ca_sha256']) & {hashlib.sha256(x).hexdigest() for x in roots}
assert bz2.decompress(bz2.compress(b'native-smoke')) == b'native-smoke'
assert lzma.decompress(lzma.compress(b'native-smoke')) == b'native-smoke'
assert sqlite3.connect(':memory:').execute('select 1').fetchone() == (1,)
assert ctypes.CDLL(None) and uuid.uuid4()
for name in ('pip', 'ensurepip', 'tkinter', 'idlelib', 'turtle', '_tkinter'):
    assert importlib.util.find_spec(name) is None, 'Unexpected installer/GUI module'
with tempfile.TemporaryDirectory() as path:
    venv.EnvBuilder(with_pip=False).create(path)
    subprocess.run([path + '/bin/python', '-c', 'import ssl,bz2,sqlite3,ctypes'], check=True)
loaders = {path.resolve() for root in ('/lib', '/lib64')
           for path in pathlib.Path(root).glob('ld-linux-*.so.*')}
loaders.update(path.resolve() for path in pathlib.Path('/lib').glob('*-linux-gnu/ld-linux-*.so.*'))
loader, = loaders
files = {pathlib.Path('/usr/local/bin/python3.13'), pathlib.Path('/usr/local/lib/libpython3.13.so.1.0')}
files.update(pathlib.Path('/usr/local/lib/python3.13/lib-dynload').glob('*.so'))
for root in (pathlib.Path(sys.prefix) / 'lib', pathlib.Path('/opt/codex')):
    files.update(path for path in root.rglob('*.so*') if path.is_file())
for path in files:
    with path.open('rb') as stream:
        magic = stream.read(4)
    if magic != b'\x7fELF':
        continue
    result = subprocess.run([str(loader), '--list', str(path)], capture_output=True, text=True)
    assert result.returncode == 0 and 'not found' not in result.stdout + result.stderr, \
        'Unresolved native dependencies: ' + str(path)
"""

NODE_TRUST = r"""
const { X509Certificate } = require('node:crypto');
const fs = require('node:fs');
const tls = require('node:tls');
const policy = JSON.parse(process.argv[1]);
if (process.versions.node !== policy.node) throw Error('Node version mismatch');
const bundled = tls.getCACertificates('bundled');
const system = fs.readFileSync('/etc/ssl/certs/ca-certificates.crt', 'utf8')
  .match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g);
if (!system?.length || !bundled.length) throw Error('Empty certificate store');
for (const pem of [...system, ...bundled]) {
  const hash = new X509Certificate(pem).fingerprint256.replaceAll(':', '').toLowerCase();
  if (policy.distrusted_ca_sha256.includes(hash)) throw Error('Distrusted root');
}
for (const path of ['/usr/local/bin/npm', '/usr/bin/npm',
                    '/usr/local/lib/node_modules/npm', '/usr/lib/node_modules/npm']) {
  if (fs.existsSync(path)) throw Error('Unused global npm remains');
}
"""

# Only read-only synthetic responses. The entire container has --network none.
FRONTEND_FIXTURE = r"""
const http = require('node:http');
http.createServer((req, res) => {
  if (req.method !== 'GET') { res.writeHead(405); res.end(); return; }
  const path = new URL(req.url, 'http://localhost').pathname;
  let body;
  if (path.endsWith('/categories')) body = { categories: [] };
  else if (path.endsWith('/stats')) body = { categoryCount: 0, publishedServerCount: 0,
    generatedAt: new Date().toISOString(), lastRegistryUpdate: null };
  else if (path === '/api/v1/skills') body = { data: [], auditEnabled: false,
    pagination: { total: 0, page: 0, per_page: 20, total_pages: 0 } };
  else if (path.startsWith('/api/v1/mcp/')) body = { servers: [],
    metadata: { count: 0, total: 0, nextCursor: '' } };
  else { res.writeHead(404); res.end('{}'); return; }
  res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body));
}).listen(8000, '127.0.0.1');
"""

FRONTEND_CHECK = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const policy = JSON.parse(process.argv[1]);
assert.equal(require('next/package.json').version, policy.next);
assert.equal(process.getuid(), policy.uids.frontend);
const base = 'http://127.0.0.1:3000';
const response = await fetch(base);
assert.equal(response.status, 200);
const html = await response.text();
assert.match(html, /Wardn Hub/);
assert.match(html, /The open agent ecosystem/);
const paths = [...new Set([...html.matchAll(/(?:src|href)="([^"\s]+)"/g)]
  .map(x => x[1].replaceAll('&amp;', '&')).filter(x => x.startsWith('/_next/static/')))];
assert(paths.some(x => x.includes('.js')), 'No real JS asset');
assert(paths.some(x => x.includes('.css')), 'No real CSS asset');
for (const path of paths) {
  const asset = await fetch(base + path);
  assert.equal(asset.status, 200, 'Asset failed');
  assert((await asset.arrayBuffer()).byteLength > 0);
  if (path.includes('.js')) {
    assert.notEqual((await fetch(base + path + '.map')).status, 200, 'Public source map');
  }
}
const imagePath = '/_next/image?url=%2Fwardn-brand-32x32.png&w=32&q=75';
for (let i = 0; i < 2; i++) {
  const image = await fetch(base + imagePath, { headers: { accept: 'image/webp' } });
  assert.equal(image.status, 200);
  assert.match(image.headers.get('content-type'), /^image\/webp/);
  assert((await image.arrayBuffer()).byteLength > 0);
  if (i) assert.equal(image.headers.get('x-nextjs-cache'), 'HIT');
}
function maps(path) {
  return fs.readdirSync(path, { withFileTypes: true }).flatMap(x =>
    x.isDirectory() ? maps(path + '/' + x.name) : [path + '/' + x.name]).filter(x => x.endsWith('.map'));
}
assert(maps('.next/faro-sourcemaps').length > 0, 'No private Faro source maps');
assert.equal(maps('.next/static').length, 0, 'Public source maps remain');
assert.equal(fs.existsSync('.next/standalone/hub/frontend/server.js'), true);
"""

CODEX_CHECK = r"""
const assert = require('node:assert/strict');
const http = require('node:http');
const { randomBytes } = require('node:crypto');
const token = process.env.WARDN_HUB_CODEX_APP_SERVER_AUTH_TOKEN;
// Validate the native initialize protocol, without any turn/tool request.
await new Promise((resolve, reject) => {
  const req = http.request({ host: '127.0.0.1', port: 41237, path: '/',
    headers: { Connection: 'Upgrade', Upgrade: 'websocket', 'Sec-WebSocket-Version': '13',
      'Sec-WebSocket-Key': randomBytes(16).toString('base64'), Authorization: 'Bearer ' + token } });
  req.on('upgrade', (res, socket) => {
    assert.equal(res.statusCode, 101);
    const payload = Buffer.from(JSON.stringify({ id: 1, method: 'initialize', params: {
      clientInfo: { name: 'wardn-hub-image-smoke', version: '1.0.0' },
      capabilities: { experimentalApi: false } } }));
    const mask = randomBytes(4);
    const header = payload.length < 126 ? Buffer.from([0x81, 0x80 | payload.length]) :
      Buffer.from([0x81, 0x80 | 126, payload.length >> 8, payload.length & 255]);
    const body = Buffer.from(payload.map((v, i) => v ^ mask[i % 4]));
    socket.write(Buffer.concat([header, mask, body]));
    let data = Buffer.alloc(0);
    socket.on('data', chunk => {
      data = Buffer.concat([data, chunk]);
      if (data.length < 2) return;
      const size = data[1] & 127;
      if (size === 127) return reject(Error('Unexpected oversized frame'));
      const offset = size === 126 ? 4 : 2;
      const length = size === 126 ? (data.length < 4 ? Infinity : data.readUInt16BE(2)) : size;
      if (data.length < offset + length) return;
      try {
        const message = JSON.parse(data.subarray(offset, offset + length).toString());
        assert.equal(message.id, 1);
        assert(message.result && !message.error, 'Initialize failed');
        socket.destroy(); resolve();
      } catch (error) { socket.destroy(); reject(error); }
    });
    socket.on('error', reject);
  });
  req.on('response', () => reject(Error('Authenticated upgrade failed')));
  req.on('error', reject); req.end();
  setTimeout(() => { req.destroy(); reject(Error('WebSocket timeout')); }, 10000).unref();
});
const status = await new Promise((resolve, reject) => {
  const req = http.get({ host: '127.0.0.1', port: 41237, path: '/',
    headers: { Connection: 'Upgrade', Upgrade: 'websocket', 'Sec-WebSocket-Version': '13',
      'Sec-WebSocket-Key': randomBytes(16).toString('base64') } },
    res => { res.resume(); resolve(res.statusCode); });
  req.on('upgrade', (_res, socket) => { socket.destroy(); reject(Error('Unauthenticated upgrade')); });
  req.on('error', reject);
});
assert.equal(status, 401, 'Unauthenticated WebSocket accepted');
"""

SCANNER_CEL = r"""
import hashlib, importlib.metadata, importlib.resources, json, pathlib, sys
from skill_scanner.core.cel.go_runtime import CelGoRuntime
from skill_scanner.core.cel.models import CelRule
from skill_scanner.core.semantic import scan_facts_pb2
policy = json.loads(sys.argv[1])
bundle = importlib.resources.files('skill_scanner.core.cel').joinpath('_bin')
manifest = json.loads(bundle.joinpath('manifest.json').read_text())['helper']
assert manifest['go_version'] == manifest['toolchain_version'] == 'go' + policy['scanner_go']
assert manifest['helper_version'] == policy['scanner_version'] and manifest['protocol_version'] == 2
assert importlib.metadata.version('cisco-ai-skill-scanner') == policy['scanner_version']
for name, digest in policy['scanner_public_policy_sha256'].items():
    data = importlib.resources.files('skill_scanner').joinpath('data', name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest, 'Public vendor policy changed; review fixture allowance'
assert not pathlib.Path('/usr/local/go').exists(), 'Build SDK leaked into runtime'
rule = CelRule(rule_id='image-smoke', expression='f.skill.has_description')
with CelGoRuntime([rule]) as runtime:
    facts = scan_facts_pb2.ScanFacts(schema_version='v1')
    facts.candidate.rule_id = rule.rule_id
    facts.projection.complete = True
    for value in (True, False):
        facts.skill.has_description = value
        for _ in range(8):
            size = len(facts.SerializeToString(deterministic=True))
            if facts.projection.serialized_bytes == size:
                break
            facts.projection.serialized_bytes = size
        result = runtime.evaluate(rule.rule_id, facts)
        assert not result.error_code and result.value is value, 'CEL native evaluation failed'
    assert runtime.evaluate('unknown-image-smoke-rule', facts).error_code == 'UNKNOWN_RULE_ID'
    facts.projection.serialized_bytes = 0
    assert runtime.evaluate(rule.rule_id, facts).error_code == 'SERIALIZED_SIZE_MISMATCH'
"""

SCANNER_FIXTURE_POLICY = r"""
import hashlib, importlib.resources, json, re, sys, yaml
policy = json.loads(sys.argv[1])
config = yaml.safe_load(sys.argv[2])
assert set(config) == {'allow-rules'} and len(config['allow-rules']) == 1
rule, = config['allow-rules']
assert set(rule) == {'id', 'description', 'regex'}
assert rule['id'] == 'cisco-skill-scanner-2-3-1-public-fixture'
source = importlib.resources.files('skill_scanner').joinpath('data/default_policy.yaml')
value = yaml.safe_load(source.read_text())['credentials']['known_test_values'][0]
assert hashlib.sha256(value.encode()).hexdigest() == policy['scanner_public_fixture_sha256']
expected_literal = ''.join('\\x' + format(byte, '02x') for byte in value.encode('ascii'))
assert rule['regex'] == '^(?:[^0-9A-Za-z_])?' + expected_literal + '$'
assert re.fullmatch(rule['regex'], value)
for mutated in ('X' + value, value + 'X', value[:-1] + ('B' if value[-1] != 'B' else 'C')):
    assert re.fullmatch(rule['regex'], mutated) is None, 'Fixture allowance broadened'
print(json.dumps({'public_fixture': value}))
"""

BACKEND_HTTP = r"""
import json, sys, urllib.request
from urllib.error import HTTPError
base = 'http://127.0.0.1:8080/api/v1'
get = lambda path: json.load(urllib.request.urlopen(base + path, timeout=3))
assert get('/health/live')['status'] == 'ok'
assert get('/health/ready')['status'] == 'ready'
assert get('/openapi.json')['info']['version'] == sys.argv[1]
try:
    get('/auth/me')
except HTTPError as error:
    assert error.code == 401
else:
    raise AssertionError('Unauthenticated account accepted')
"""


def command(args, *, timeout=30, check=True):
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Runtime command failed ({args[0]})")
    return result


def main():
    if len(sys.argv) != 4:
        raise RuntimeError("Expected image, platform, and app version")
    image, target, version = sys.argv[1:]
    component = os.environ.get("CI_IMAGE_COMPONENT", "")
    native = {"x86_64": "linux/amd64", "aarch64": "linux/arm64"}.get(platform.machine())
    if native != target or component not in POLICY["uids"] or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("Invalid component, native platform, or app version")
    info = json.loads(command(["docker", "image", "inspect", image]).stdout)[0]
    if f"{info['Os']}/{info['Architecture']}" != target:
        raise RuntimeError("Image architecture mismatch")
    if info["Config"].get("Labels", {}).get("org.opencontainers.image.version") != version:
        raise RuntimeError("OCI version mismatch")
    with tempfile.TemporaryDirectory(prefix="wardn-hub-image-smoke-") as directory:
        fixture = Path(directory)
        fixture.chmod(0o755)
        (fixture / "api.cjs").write_text(FRONTEND_FIXTURE)
        (fixture / "api.cjs").chmod(0o644)
        env = {"APP_VERSION": version}
        entrypoint = []
        cmd = []
        if component == "backend":
            env.update({
                "WARDN_HUB_ENVIRONMENT": "test", "WARDN_HUB_API_PREFIX": "/api/v1",
                "WARDN_HUB_LOG_LEVEL": "INFO", "WARDN_HUB_API_TOKEN_SECRET": secrets.token_hex(32),
                "WARDN_HUB_API_TOKEN_PREFIX": "wardn_hub", "WARDN_HUB_SESSION_COOKIE_NAME": "session",
                "WARDN_HUB_SESSION_SECRET": secrets.token_hex(32), "WARDN_HUB_SESSION_TTL_SECONDS": "43200",
                "WARDN_HUB_REGISTRY_PUBLIC_BASE_URL": "http://localhost:3000",
                "WARDN_HUB_DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:5432/smoke",
            })
        elif component == "frontend":
            env.update({"NODE_OPTIONS": "--max-old-space-size=3072", "HOSTNAME": "0.0.0.0",
                        "WARDN_HUB_API_INTERNAL_BASE_URL": "http://127.0.0.1:8000",
                        "NEXT_PUBLIC_SITE_URL": "http://localhost:3000",
                        "WARDN_HUB_REGISTRY_PUBLIC_BASE_URL": "http://localhost:3000"})
            entrypoint = ["--entrypoint", "/bin/sh"]
            cmd = ["-ec", "node /image-smoke/api.cjs & exec ./docker-entrypoint.sh web"]
        else:
            env.update({"CODEX_HOME": "/tmp/image-smoke/auth", "CODEX_PERSISTENT_HOME": "/tmp/image-smoke/persistent",
                        "WARDN_HUB_CODEX_APP_SERVER_AUTH_TOKEN": secrets.token_hex(32)})
            entrypoint = ["--entrypoint", "/bin/sh"]
            cmd = ["-ec", ("mkdir -p \"$CODEX_HOME\" \"$CODEX_PERSISTENT_HOME\"; "
                   "printf '%s' '{\"OPENAI_API_KEY\":\"sk-image-smoke-synthetic-not-a-real-credential\"}' > \"$CODEX_HOME/auth.json\"; "
                   "chmod 600 \"$CODEX_HOME/auth.json\"; "
                   "exec /usr/bin/tini -s -g -- /usr/local/bin/codex-app-server-wrapper")]
        args = ["docker", "run", "-d", "--network", "none", "--memory", "4g", "--cpus", "2",
                "--pids-limit", "512", "--mount", f"type=bind,src={fixture},dst=/image-smoke,readonly"]
        for key, value in env.items():
            args.extend(["--env", f"{key}={value}"])
        container = command([*args, *entrypoint, image, *cmd]).stdout.strip()
        probe_errors = []
        try:
            def execute(*args, timeout=30, check=True):
                result = command(["docker", "exec", container, *args], timeout=timeout, check=False)
                if result.returncode and check:
                    probe_errors.append(result.stderr)
                    raise RuntimeError(f"Runtime {args[0]} check failed")
                return result

            uid = execute("id", "-u").stdout.strip()
            if uid != str(POLICY["uids"][component]):
                raise RuntimeError("Runtime UID mismatch")
            execute("node", "-e", NODE_TRUST, json.dumps(POLICY))
            if component != "frontend":
                if execute("codex", "--version").stdout.strip() != f"codex-cli {POLICY['codex']}":
                    raise RuntimeError("Codex version mismatch")
                execute("python", "-c", PYTHON_RUNTIME, json.dumps(POLICY), timeout=90)
            if component == "backend":
                execute("python", "-c", "import importlib.metadata,sys; "
                        "assert importlib.metadata.version('wardn-hub-api')==sys.argv[1]; "
                        "import onnxruntime,magika,skill_scanner; "
                        "assert onnxruntime.get_available_providers(); "
                        "result=magika.Magika().identify_bytes(b'def native_smoke():\\n    print(42)\\n'*50); "
                        "assert str(result.status)=='ok' and result.prediction is not None", version)
                execute("python", "-c", SCANNER_CEL, json.dumps(POLICY))
                config_path = Path(__file__).resolve().parents[1] / "trivy-secret.yaml"
                validated = execute("python", "-c", SCANNER_FIXTURE_POLICY,
                                    json.dumps(POLICY), config_path.read_text())
                public_fixture = json.loads(validated.stdout)["public_fixture"]
                trivy = os.environ.get("TRIVY_BIN") or shutil.which("trivy")
                if not trivy or "Version: 0.76.0" not in command([trivy, "--version"]).stdout:
                    raise RuntimeError("Trivy 0.76.0 is required for fixture-policy checks")
                secret_fixtures = fixture / "secret-policy-fixtures"
                secret_fixtures.mkdir(mode=0o700)
                other = "sk_live_" + secrets.token_hex(16)
                (secret_fixtures / "default_policy.yaml").write_text(
                    "known_test_value: " + public_fixture + "\nnegative: " + other + "\n")
                (secret_fixtures / "public-fixture.conf").write_text(public_fixture + "\n")
                (secret_fixtures / "other-credentials.conf").write_text(
                    other + "\n" + "ghp_" + secrets.token_hex(18) + "\n")
                report = fixture / "fixture-negative-scan.json"
                result = command([trivy, "fs", "--secret-config", str(config_path),
                                  "--scanners", "secret", "--severity", "HIGH,CRITICAL",
                                  "--exit-code", "1", "--format", "json", "--output", str(report),
                                  str(secret_fixtures)], check=False, timeout=60)
                findings = [(Path(item["Target"]).name, secret["RuleID"])
                            for item in json.loads(report.read_text()).get("Results", [])
                            for secret in item.get("Secrets", [])]
                expected = [("default_policy.yaml", "stripe-secret-token"),
                            ("other-credentials.conf", "stripe-secret-token"),
                            ("other-credentials.conf", "github-pat")]
                if result.returncode != 1 or sorted(findings) != sorted(expected):
                    raise RuntimeError("Secret scanning negative controls failed")
                probe = ["python", "-c", BACKEND_HTTP, version]
            elif component == "frontend":
                probe = ["node", "--input-type=module", "-e", "const r=await fetch('http://127.0.0.1:3000'); if(r.status!==200)process.exit(1)"]
            else:
                probe = ["node", "-e", "require('node:net').connect(41237,'127.0.0.1').on('connect',()=>process.exit(0)).on('error',()=>process.exit(1))"]
            deadline = time.monotonic() + (600 if component == "frontend" else 90)
            while execute(*probe, timeout=10, check=False).returncode:
                running = command(["docker", "inspect", "-f", "{{.State.Running}}", container]).stdout.strip()
                if running != "true" or time.monotonic() > deadline:
                    raise RuntimeError("Application did not become ready")
                time.sleep(2)
            if component == "frontend":
                execute("node", "--input-type=commonjs", "-e",
                        "(async()=>{" + FRONTEND_CHECK + "})().catch(e=>{console.error(e.message);process.exit(1)})", json.dumps(POLICY))
            elif component == "codex-app-server":
                execute("node", "--input-type=commonjs", "-e",
                        "(async()=>{" + CODEX_CHECK + "})().catch(e=>{console.error(e.message);process.exit(1)})")
            print(f"PASS {component}: {target}, app {version}; offline native runtime and HTTP checks")
        except (RuntimeError, subprocess.SubprocessError):
            # This container receives only generated synthetic configuration. Keep
            # its logs in the shared workflow's private reports, never print them.
            reports = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "image-reports"
            reports.mkdir(parents=True, exist_ok=True)
            log = reports / f"runtime-smoke-{component}.log"
            log.touch(mode=0o600, exist_ok=True)
            log.chmod(0o600)
            result = command(["docker", "logs", container], check=False)
            log.write_text(result.stdout + result.stderr + "\n".join(probe_errors))
            print(f"Synthetic runtime logs: {log}", file=sys.stderr)
            raise
        finally:
            command(["docker", "rm", "--force", container], check=False)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, ValueError, OSError) as error:
        print(f"Image smoke failed: {error}", file=sys.stderr)
        sys.exit(1)
