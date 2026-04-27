-- 容器首次初始化时自动建 orthanc 数据库（已有数据卷的环境不会跑这个 init 目录）
-- 历史卷需手动执行：psql -U medassist -d medassist -c "CREATE DATABASE orthanc OWNER medassist;"
CREATE DATABASE orthanc OWNER medassist;
