"""测试进程专用配置隔离；业务应用不会导入此模块。

SQLite/PG测试及迁移子进程共用同一入口，禁止读取任何业务.env文件。
DATABASE_URL由各套件单独指定；本模块只隔离凭据和外部服务。
"""
import os
import runpy
import sys

from pydantic_settings.sources import DotEnvSettingsSource


def _no_dotenv_files(self) -> dict:
    """在Pydantic尝试打开文件前屏蔽dotenv源，避免仅覆盖已知字段后仍读入新凭据。"""
    return {}


def isolate_external_services() -> None:
    """必须先于任何app模块导入；测试需要启用功能时再显式monkeypatch。"""
    DotEnvSettingsSource._read_env_files = _no_dotenv_files
    os.environ.update(
        SECRET_KEY='test-secret-key-not-for-production',
        ORTHANC_PASSWORD='test-orthanc-password-not-for-production',
        ORTHANC_USERNAME='test-user', APP_ENV='development',
        DEEPSEEK_API_KEY='', DEEPSEEK_BASE_URL='http://127.0.0.1:1',
        ALIYUN_API_KEY='', ALIYUN_BASE_URL='http://127.0.0.1:1',
        ALIBABA_ACCESS_KEY_ID='', ALIBABA_ACCESS_KEY_SECRET='',
        ORTHANC_BASE_URL='http://127.0.0.1:1', REDIS_URL='', SENTRY_DSN='',
        HIS_ADAPTER_ENABLED='false', HIS_INBOUND_APP_ID='', HIS_INBOUND_APP_SECRET='',
        HIS_WS_IP_ALLOWLIST='', HIS_WRITEBACK_URL='http://127.0.0.1:1',
        HIS_WRITEBACK_REFRESH_URL='http://127.0.0.1:1',
        HIS_WRITEBACK_APP_ID='', HIS_WRITEBACK_APP_SECRET='',
    )


def main() -> None:
    """迁移子进程入口：python -m test_support [-m 模块 | 脚本路径] [参数]。"""
    isolate_external_services()
    args = sys.argv[1:]
    if not args:
        raise SystemExit('需要指定测试脚本或模块')
    if args[0] == '-m':
        sys.argv = args[1:]
        runpy.run_module(sys.argv[0], run_name='__main__', alter_sys=True)
    else:
        sys.argv = args
        runpy.run_path(args[0], run_name='__main__')


if __name__ == '__main__':
    main()
