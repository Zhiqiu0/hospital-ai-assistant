"""患者查询/搜索 mixin（services/_patient_query.py）

从 patient_service 拆出（Round: 超标文件拆分）。含查重（find_existing）、
分页模糊搜索（search）、按 UUID 单查（get_by_id）三个读接口。
由 PatientService 组合，依赖宿主类提供 self.db 及共享辅助
_to_response / _fetch_inpatient_state（PatientCommonMixin）。
"""
from datetime import date

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.core.validators.identity import normalize_id_card, normalize_phone
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
        allow_weak_match: bool = True,
    ) -> dict | None:
        """查找系统中已存在的患者档案，用于防止重复建档。

        查找顺序（找到即返回，不继续后续匹配）：
          1. id_card 非空 → 按身份证号精确匹配（强键）
          2. phone + name 非空 → 按手机号+姓名精确匹配（强键）
          3. name + birth_date 非空 → 按姓名+出生日期精确匹配（弱键，仅兜底）

        allow_weak_match（2026-08-11 审计修复）：
          第 3 级「姓名+生日」有同名同生日碰撞风险。手工建档有医生人眼确认，
          默认放行；HIS 全自动链路必须传 False——宁可产生重复档案（可事后人工
          合并），也绝不能把两个不同患者误合并成一份（会造成跨人病历污染）。

        Returns:
            找到则返回患者响应字典；未找到则返回 None。
        """
        # ── 入参归一化（2026-08-14 第七轮审计修复）───────────────────────────
        #
        # 此前这里拿到什么就逐字节比什么，而**写入侧**的 PatientCreate 走的是
        # IdCardStrict / Phone 类型别名，早就把值归一过了（末位 x→X、去空格
        # 连字符、剥 +86）。两侧口径不一致，HIS 推来一个小写 x 的身份证就会：
        #   ① 查重 miss（库里存的是大写 X）
        #   ② 落到新建分支 → PatientCreate 归一成大写 X
        #   ③ INSERT 撞上 uq_patients_id_card_active 部分唯一索引 → IntegrityError
        #   ④ 接诊 ack 50000 —— **这个患者从此每次复诊都推不进来**，且日志里
        #      只看得到一条唯一键冲突，看不出根因是大小写。
        # 手机号同理（HIS 侧 "+86-138..." / "138 0013 8000" 都见过）。
        # 归一函数本来就有，查重路径接上即可，不新增任何规则。
        id_card = normalize_id_card(id_card)
        phone = normalize_phone(phone)

        patient = None

        # 全部查重路径都要排除已软删患者：上次接诊取消时连档案一起清掉了，
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

        # 最后用姓名+出生日期（弱键，同名同日出生有碰撞风险）：
        # 用 first() 而非 scalar_one_or_none()，多行命中时不抛 MultipleResultsFound。
        if not patient and allow_weak_match and name and birth_date:
            result = await self.db.execute(
                select(Patient).where(
                    Patient.name == name,
                    Patient.birth_date == birth_date,
                    Patient.is_deleted.is_(False),
                ).order_by(Patient.created_at.desc())
            )
            patient = result.scalars().first()

        return self._to_response(patient) if patient else None

    async def find_weak_candidates(
        self,
        *,
        name: str | None,
        birth_date: date | None,
        limit: int = 5,
    ) -> list[dict]:
        """按「姓名+出生日期」找可能是同一人的档案，**只供医生人工确认**。

        2026-08-14 第七轮审计新增。背景：

        find_existing 的第 3 级弱键匹配原本会**静默复用**同名同生日的档案。
        手工初诊里医生只是照着新病人念了姓名和生日，系统就把他挂到了另一个
        同名同生日的人名下——接下来 get_profile 把**那个人的过敏史、既往史
        预填进表单**，医生看到"系统已有资料"往往不会逐条核对。
        按别人的过敏史开药是可能致命的，而且病历也写进了错误的档案。

        碰撞并不罕见：常见姓名 + 中国出生日期本身聚集（同年同月同日），
        县级医院几万份档案里同名同生日是必然出现的。

        改法沿用 find_existing 文档里已经写明、HIS 链路已经在用的那条原则——
        **宁可产生重复档案（可事后人工合并），也绝不能把两个不同患者误合并成
        一份**。所以弱键不再自动复用，改为把候选人交回前端，由医生看着
        「李梅 女 1985-03-12 尾号 6023」这样的信息自己判断是不是同一个人。

        Args:
            name: 患者姓名
            birth_date: 出生日期
            limit: 最多返回几个候选（同名同生日超过几个的极端情况截断）

        Returns:
            候选患者响应字典列表；姓名或生日缺失时返回空列表。
        """
        if not name or not birth_date:
            return []
        result = await self.db.execute(
            select(Patient)
            .where(
                Patient.name == name,
                Patient.birth_date == birth_date,
                Patient.is_deleted.is_(False),
            )
            .order_by(Patient.created_at.desc())
            .limit(limit)
        )
        return [self._to_response(p) for p in result.scalars().all()]

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
                # 用精简项而非完整响应：敏感 PHI 不进列表、不进 Redis 缓存
                # （2026-08-13 第二轮审计修复，详见 _to_list_item 说明）
                self._to_list_item(
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
