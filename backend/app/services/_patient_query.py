"""患者查询/搜索 mixin（services/_patient_query.py）

从 patient_service 拆出（Round: 超标文件拆分）。含查重（find_existing）、
分页模糊搜索（search）、按 UUID 单查（get_by_id）三个读接口。
由 PatientService 组合，依赖宿主类提供 self.db 及共享辅助
_to_response / _fetch_inpatient_state（PatientCommonMixin）。
"""
from datetime import date

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.models.patient import Patient
from app.services.patient_cache import _BASIC_KEY, _BASIC_TTL
from app.services.redis_cache import redis_cache
from app.utils.pinyin import is_ascii_alpha


class PatientQueryMixin:
    """患者查重 / 搜索 / 单查（依赖宿主类提供 self.db）。"""

    async def find_existing(
        self,
        *,
        id_card: str | None = None,
        phone: str | None = None,
        name: str | None = None,
        birth_date: date | None = None,
    ) -> dict | None:
        """查找系统中已存在的患者档案，用于防止重复建档。

        查找顺序（找到即返回，不继续后续匹配）：
          1. id_card 非空 → 按身份证号精确匹配
          2. phone + name 非空 → 按手机号+姓名精确匹配
          3. name + birth_date 非空 → 按姓名+出生日期精确匹配

        Returns:
            找到则返回患者响应字典；未找到则返回 None。
        """
        patient = None

        # 全部三种查重路径都要排除已软删患者：上次接诊取消时连档案一起清掉了，
        # 这里再把人查出来等于把"已删"档案带回业务流，导致医生在新接诊里继续
        # 用一个底层已经标记删除的患者档案——不是预期。

        # 优先用身份证号（精度最高，18位唯一标识）
        if id_card:
            result = await self.db.execute(
                select(Patient).where(
                    Patient.id_card == id_card,
                    Patient.is_deleted.is_(False),
                )
            )
            patient = result.scalar_one_or_none()

        # 其次用手机号+姓名（适合没有身份证的场景）
        if not patient and phone and name:
            result = await self.db.execute(
                select(Patient).where(
                    Patient.phone == phone,
                    Patient.name == name,
                    Patient.is_deleted.is_(False),
                )
            )
            patient = result.scalar_one_or_none()

        # 最后用姓名+出生日期（精度较低，同名同日出生有碰撞风险，仅作兜底）
        if not patient and name and birth_date:
            result = await self.db.execute(
                select(Patient).where(
                    Patient.name == name,
                    Patient.birth_date == birth_date,
                    Patient.is_deleted.is_(False),
                )
            )
            patient = result.scalar_one_or_none()

        return self._to_response(patient) if patient else None

    async def search(
        self,
        keyword: str,
        page: int,
        page_size: int,
        require_completed: bool = False,
    ):
        """按姓名或患者编号搜索患者，支持分页（带 Redis 缓存）。

        缓存 30 秒；create / update 时清整个 patient:search:* 前缀。
        新建/复诊弹窗在用户输入时高频触发，命中缓存可显著降低 DB 负载。
        每条响应附带 has_active_inpatient（是否有进行中的住院接诊），
        前端 PatientHistoryDrawer 据此显示"在院中 / 已出院"状态标签。

        Args:
            require_completed: True 时只返回"至少有 1 个 status=completed 接诊"
              的患者。复诊弹窗专用，避免医生把"从未真正完成过接诊"的患者当复诊接。
              False（默认）= 普通患者列表 / 初诊查重场景。
        """
        # 缓存 key 带上 require_completed，两种语义不能互相污染
        cache_key = f"patient:search:{keyword}:{page}:{page_size}:rc{int(require_completed)}"
        cached = await redis_cache.get_json(cache_key)
        if cached is not None:
            return cached

        offset = (page - 1) * page_size
        # 子查询：每个患者最近一次接诊时间（用于"按最近就诊时间倒序"排序）
        # 比"按建档时间排序"更贴医生工作流——昨天来过的患者大概率今天也想找
        from app.models.encounter import Encounter as _Enc
        last_visit_subq = (
            select(
                _Enc.patient_id.label("pid"),
                func.max(_Enc.visited_at).label("last_visit_at"),
            )
            .group_by(_Enc.patient_id)
            .subquery()
        )
        query = select(Patient).outerjoin(
            last_visit_subq, Patient.id == last_visit_subq.c.pid
        )
        # 软删患者一律不出现在搜索结果（取消接诊联动删除的孤儿档案）
        query = query.where(Patient.is_deleted.is_(False))
        # 复诊场景：再叠加"至少有 1 个 completed 接诊"过滤。
        # 这层独立于 is_deleted——是为了挡住"档案在但从没正常完成过"的边界态
        # （HIS 同步过来 + 全部接诊都被取消 / 老档案改名复用但所有 encounter 都失败）。
        if require_completed:
            completed_subq = (
                select(_Enc.patient_id)
                .where(_Enc.status == "completed")
                .distinct()
                .subquery()
            )
            query = query.where(
                Patient.id.in_(select(completed_subq.c.patient_id))
            )
        if keyword:
            conditions = [
                Patient.name.ilike(f"%{keyword}%"),
                Patient.patient_no.ilike(f"%{keyword}%"),
            ]
            # 关键词为纯 ASCII 字母时同时打拼音列：覆盖 "zhang" / "zs" / "zhangs" / "zsan"
            # 等市面常见输入。汉字/数字/混合关键词跳过拼音列——拼音存的是英文，
            # 加进 OR 也不会命中，反而浪费 SQL。
            if is_ascii_alpha(keyword):
                kw_lower = keyword.lower()
                conditions.append(Patient.name_pinyin.ilike(f"%{kw_lower}%"))
                conditions.append(Patient.name_pinyin_initials.ilike(f"%{kw_lower}%"))
            query = query.where(or_(*conditions))
        # 先查总数（用于分页计算），再查当前页数据
        count_result = await self.db.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar()
        # 排序：最近就诊时间倒序为主；从未接诊（last_visit_at IS NULL）的回落到建档时间倒序
        query = query.order_by(
            last_visit_subq.c.last_visit_at.desc().nullslast(),
            Patient.created_at.desc(),
        )
        result = await self.db.execute(query.offset(offset).limit(page_size))
        items = result.scalars().all()
        # 一次性查这批患者的住院状态（active + 历史，一次 SQL 拿两个集合）
        active_set, ever_set = await self._fetch_inpatient_state([p.id for p in items])
        data = {
            "total": total,
            "items": [
                self._to_response(
                    p,
                    has_active_inpatient=p.id in active_set,
                    has_any_inpatient_history=p.id in ever_set,
                )
                for p in items
            ],
        }
        await redis_cache.set_json(cache_key, data, ttl=30)
        return data

    async def get_by_id(self, patient_id: str) -> dict:
        """按 UUID 查询单个患者（带 Redis 缓存）。

        缓存 5 分钟；update / update_profile 写时主动失效。
        软删患者按"不存在"处理：取消接诊联动软删后，前端任何路径再拿这个 ID
        请求详情都直接 404，避免把已删档案带回界面继续编辑。
        """
        cache_key = _BASIC_KEY.format(pid=patient_id)
        cached = await redis_cache.get_json(cache_key)
        if cached is not None:
            return cached

        result = await self.db.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.is_deleted.is_(False),
            )
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")
        active_set, ever_set = await self._fetch_inpatient_state([patient_id])
        data = self._to_response(
            patient,
            has_active_inpatient=patient_id in active_set,
            has_any_inpatient_history=patient_id in ever_set,
        )
        await redis_cache.set_json(cache_key, data, ttl=_BASIC_TTL)
        return data
