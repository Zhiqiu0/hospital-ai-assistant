"""
一次性脚本：在已有数据库中添加 audit_logs 表
如果是全新部署直接运行 init_db.py 即可，无需运行此脚本
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.schema_compat import apply_schema_compatibility


async def main():
    await apply_schema_compatibility()
    print("[OK] audit_logs 表及兼容字段已创建（若已存在则跳过）")


if __name__ == "__main__":
    asyncio.run(main())
