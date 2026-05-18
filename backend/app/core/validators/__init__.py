"""字段级输入校验模块。

业内成熟做法：所有正则、校验码算法集中在此目录，schemas/services 通过
Annotated 类型别名引入，杜绝多个 Pydantic 模型各抄一份正则导致规则漂移。
"""
