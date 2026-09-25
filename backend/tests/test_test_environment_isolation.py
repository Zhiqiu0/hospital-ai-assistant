"""以独立进程验证测试入口不会继承业务数据库或向远端发起建库。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest


def _run(code: str, **overrides):
    """只用合成连接串；替换PG驱动连接函数，测试本身绝不访问网络。"""
    env = {**os.environ, 'SECRET_KEY': 'test-isolation', 'ORTHANC_PASSWORD': 'test-isolation', **overrides}
    result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).parents[1],
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_sqlite_suite_forces_in_memory_database():
    """即使启动shell携带业务连接串，导入测试入口后也只能使用SQLite内存。"""
    result = _run("""
import json, runpy
runpy.run_path('tests/conftest.py')
from app.config import settings
print(json.dumps({'database': settings.database_url}))
""", DATABASE_URL='postgresql+asyncpg://fake:fake@example.invalid/never_connect')
    assert result['database'] == 'sqlite+aiosqlite:///:memory:'


def test_pg_suite_rejects_remote_before_connecting():
    """远端目标应在任何连接/建库前拒绝，错误信息不含连接凭据。"""
    result = _run("""
import json, runpy, asyncpg
calls = []
async def blocked_connect(*args, **kwargs):
    calls.append(True)
    raise RuntimeError('synthetic connection blocked')
asyncpg.connect = blocked_connect
error = ''
try:
    runpy.run_path('tests_pg/conftest.py')
except BaseException as exc:
    error = str(exc)
print(json.dumps({'calls':len(calls), 'rejected':bool(error), 'leaked':'fake-password' in error}))
""", DATABASE_URL='postgresql+asyncpg://fake:fake-password@example.invalid/never_connect',
        PG_TEST_DATABASE_URL='postgresql+asyncpg://fake:fake-password@example.invalid/never_connect')
    assert result == {'calls': 0, 'rejected': True, 'leaked': False}


def test_pg_cleanup_failure_cannot_report_success():
    """随机测试库清理失败必须使本轮失败，并报告库名而非连接凭据。"""
    result = _run("""
import json, runpy, asyncpg
from types import SimpleNamespace
from unittest.mock import AsyncMock
class Connection:
    execute = AsyncMock()
    close = AsyncMock()
asyncpg.connect = AsyncMock(return_value=Connection())
scope = runpy.run_path('tests_pg/conftest.py')
hook = scope['pytest_sessionfinish']
scope['_ensure_test_database'].__wrapped__()
hook.__globals__['_test_engine'] = SimpleNamespace(dispose=AsyncMock())
hook.__globals__['_drop_test_db'] = AsyncMock(side_effect=RuntimeError('fake-password'))
messages = []
reporter = SimpleNamespace(write_sep=lambda *args, **kw: messages.append(str(args)))
session = SimpleNamespace(exitstatus=0, config=SimpleNamespace(
    pluginmanager=SimpleNamespace(getplugin=lambda name: reporter)))
hook(session, 0)
message = ' '.join(messages)
print(json.dumps({'failed': session.exitstatus != 0,
                  'named':scope['TEST_DB_NAME'] in message, 'leaked':'fake-password' in message}))
""", PG_TEST_DATABASE_URL='postgresql+asyncpg://fake:fake-password@localhost/postgres')
    assert result == {'failed': True, 'named': True, 'leaked': False}


@pytest.mark.parametrize('suite', ['tests', 'tests_pg'])
def test_test_suites_ignore_dotenv_and_external_shell_configuration(suite):
    """合成.env和shell也不能开启HIS或携带外部云凭据，且不读取.env文件。"""
    result = _run("""
import json, os, sys, runpy, asyncpg, tempfile
from pathlib import Path
from unittest.mock import AsyncMock
from pydantic_settings.sources import DotEnvSettingsSource
root = Path.cwd()
sys.path.insert(0, str(root))
reads = []
original = DotEnvSettingsSource._read_env_file
def track(*args, **kwargs):
    reads.append(True)
    return original(*args, **kwargs)
DotEnvSettingsSource._read_env_file = track
asyncpg.connect = AsyncMock(side_effect=RuntimeError('blocked'))
with tempfile.TemporaryDirectory() as tmp:
    Path(tmp, '.env').write_text('HIS_WRITEBACK_REFRESH_URL=https://synthetic.invalid/refresh\\n', encoding='utf-8')
    os.chdir(tmp)
    try:
        runpy.run_path(str(root / os.environ['REVIEW_SUITE'] / 'conftest.py'))
        from app.config import settings
        print(json.dumps({'reads':len(reads), 'his':settings.his_adapter_enabled,
            'external':settings.his_writeback_refresh_url.startswith('https://synthetic.invalid'),
            'cloud_secret':bool(settings.alibaba_access_key_secret),
            'real_secret':settings.secret_key == 'synthetic-shell-secret'}))
    finally:
        os.chdir(root)
""", REVIEW_SUITE=suite, PG_TEST_DATABASE_URL='postgresql+asyncpg://fake:fake@localhost/postgres',
        CI='', HIS_ADAPTER_ENABLED='true', HIS_INBOUND_APP_ID='fake', HIS_INBOUND_APP_SECRET='fake',
        ALIBABA_ACCESS_KEY_SECRET='synthetic-shell-secret', SECRET_KEY='synthetic-shell-secret')
    assert result == {'reads': 0, 'his': False, 'external': False, 'cloud_secret': False, 'real_secret': False}


def test_pg_import_never_creates_database():
    """导入测试配置时尚未注册清理钩子，必须保持零网络/零建库副作用。"""
    result = _run("""
import json, runpy, asyncpg
from unittest.mock import AsyncMock
class Connection:
    execute = AsyncMock()
    close = AsyncMock()
asyncpg.connect = AsyncMock(return_value=Connection())
scope = runpy.run_path('tests_pg/conftest.py')
print(json.dumps({'connections':asyncpg.connect.await_count}))
""", PG_TEST_DATABASE_URL='postgresql+asyncpg://fake:fake@localhost/postgres')
    assert result == {'connections': 0}


def test_pg_collection_has_no_database_side_effects():
    """真实pytest收集现有全部PG用例时不连接服务，CI收集阶段同样安全。"""
    result = _run("""
import json, pytest, asyncpg
from unittest.mock import AsyncMock
asyncpg.connect = AsyncMock(side_effect=AssertionError('collection must not connect'))
status = pytest.main(['tests_pg', '--collect-only', '-q'])
print(json.dumps({'status':int(status), 'connections':asyncpg.connect.await_count}))
""", PG_TEST_DATABASE_URL='postgresql+asyncpg://fake:fake@localhost/postgres', CI='true')
    assert result == {'status': 0, 'connections': 0}


def test_pg_without_explicit_target_skips_cleanly_without_connecting():
    """未指定本地测试服务时正常skip，不能在conftest导入阶段抛出长异常栈。"""
    result = _run("""
import json, pytest, asyncpg
from unittest.mock import AsyncMock
asyncpg.connect = AsyncMock(side_effect=AssertionError('missing target must not connect'))
status = pytest.main(['tests_pg', '-q'])
print(json.dumps({'status':int(status), 'connections':asyncpg.connect.await_count}))
""", PG_TEST_DATABASE_URL='', CI='')
    assert result == {'status': 0, 'connections': 0}


def test_pg_ci_connection_failure_is_not_skipped():
    """CI测试服务不可用时夹具明确失败，不能整批skip造成虚假绿灯。"""
    result = _run("""
import json, runpy, asyncpg, pytest
from unittest.mock import AsyncMock
asyncpg.connect = AsyncMock(side_effect=RuntimeError('synthetic-password'))
scope = runpy.run_path('tests_pg/conftest.py')
try:
    scope['_ensure_test_database'].__wrapped__()
except BaseException as exc:
    print(json.dumps({'failed':isinstance(exc, pytest.fail.Exception),
                      'leaked':'synthetic-password' in str(exc)}))
""", PG_TEST_DATABASE_URL='postgresql+asyncpg://fake:fake@localhost/postgres', CI='true')
    assert result == {'failed': True, 'leaked': False}


def test_pg_ci_missing_driver_is_not_skipped():
    """CI缺少必需PG驱动也必须报错，不能由importorskip隐藏依赖安装问题。"""
    result = _run("""
import builtins, json, runpy, pytest
original = builtins.__import__
def missing_driver(name, *args, **kwargs):
    if name == 'asyncpg': raise ModuleNotFoundError('synthetic missing asyncpg')
    return original(name, *args, **kwargs)
builtins.__import__ = missing_driver
try:
    runpy.run_path('tests_pg/conftest.py')
except BaseException as exc:
    print(json.dumps({'skipped':isinstance(exc, pytest.skip.Exception)}))
""", PG_TEST_DATABASE_URL='postgresql+asyncpg://fake:fake@localhost/postgres', CI='true')
    assert result == {'skipped': False}


@pytest.mark.parametrize('module_mode', [True, False])
def test_pg_child_entrypoint_preserves_arguments_and_isolation(module_mode):
    """迁移模块/guard脚本都在隔离配置下执行，命令行参数不丢失。"""
    result = _run("""
import json, os, subprocess, sys, tempfile
from pathlib import Path
root = Path.cwd()
with tempfile.TemporaryDirectory() as tmp:
    Path(tmp, '.env').write_text('HIS_ADAPTER_ENABLED=true\\n', encoding='utf-8')
    Path(tmp, 'probe.py').write_text('''import json, sys
from pydantic_settings.sources import DotEnvSettingsSource
def forbidden(*args, **kwargs): raise AssertionError('dotenv must not be read')
DotEnvSettingsSource._read_env_file = forbidden
from app.config import settings
print(json.dumps({'his':settings.his_adapter_enabled,'args':sys.argv[1:]}))
''', encoding='utf-8')
    target = ['-m', 'probe'] if os.environ['MODULE_MODE'] == 'true' else ['probe.py']
    env = {**os.environ, 'PYTHONPATH':str(root), 'HIS_ADAPTER_ENABLED':'true'}
    child = subprocess.run([sys.executable, '-m', 'test_support', *target, 'upgrade', 'head'],
                           cwd=tmp, env=env, capture_output=True, text=True, timeout=10)
    assert child.returncode == 0, child.stderr
    print(child.stdout.strip())
""", MODULE_MODE=str(module_mode).lower())
    assert result == {'his': False, 'args': ['upgrade', 'head']}
