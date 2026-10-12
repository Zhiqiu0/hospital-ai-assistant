"""AI 批次草稿保存；由原草稿 mixin 机械拆分，保留版本留痕及住院续建语义。"""
from typing import Optional
from sqlalchemy import func
from app.models.medical_record import MedicalRecord, RecordVersion
from app.services._record_draft_selection import load_writable_draft


class MedicalRecordAIDraftMixin:
    """依赖宿主提供 db、类型校验与住院同类型序号方法。"""

    async def save_ai_draft(
        self,
        encounter_id: str,
        record_type: str,
        content: str,
        user_id: str,
        record_id: Optional[str] = None,
    ) -> dict:
        """AI 生成完毕保存草稿（不签发，不动接诊状态）。

        与 save_content 的差异：
          - save_content 要求 record_id 已知（医生编辑场景）
          - save_ai_draft 用 (encounter_id, record_type) upsert：
            * 该接诊该类型 record 不存在 → 创建一条 + 新版本
            * 已存在且非 submitted → 在原 record 上加新版本，状态保持 editing
            * 已签发（submitted）→ 跳过保存，返回原 record（不让 AI 覆盖签发病历）

        为什么必要：解决"AI 生成的病历只在前端 zustand store，logout 后清空 →
        DB 没数据可恢复 → 医生开心写一半的草稿全丢"的合规事故。

        Returns:
            {"record_id": ..., "version_no": ..., "saved": bool}
            saved=False 表示已签发跳过保存。
        """
        # 文书类型必须与就诊类型相容（2026-09-01 住院支线实测补）。
        # 这是第三条写入路径——auto_save_draft 与 quick_save 都拦了，唯独 AI
        # 生成这条当时漏了，于是住院接诊里照样落进了一份 record_type='outpatient'
        # 的病历。三条写入路径必须同口径，漏一条守卫就等于没有。
        await self._assert_type_ok(encounter_id, record_type)

        # NUL 剥离（2026-08-28 极端字符审计）：PG JSONB 拒收 \u0000，
        # PDF 复制粘贴偶带 NUL → 每次保存都 DataError 500。剥掉无信息损失。
        content = content.replace("\x00", "")
        # 首行并发防重（2026-08-28 完整性审计）：该 (enc,type) 还没有行时
        # record 级行锁锁不到东西，AI 落库与 auto-save 并发会各插一行同号文书。
        # 与 quick_save 同口径先锁 encounter 行，把首行插入串行化；
        # 三元组唯一约束（k20260828recuniq）作最后兜底。
        record = await load_writable_draft(self.db, encounter_id, record_type, record_id)

        if record is not None and record.status == "submitted":
            # 住院例外（2026-08-14 第八轮审计修复）：住院一次接诊有多份同类型
            # 文书，"上一份已签发"不等于"这一份不能写"。原先无条件 saved=False，
            # 而 record_gen_v2_service 不检查返回值也不报错 → AI 生成的第 2 份
            # 病程只活在浏览器 store 里，刷新即丢，医生毫不知情。
            if await self._is_inpatient(encounter_id):
                record = None
            else:
                return {
                    "record_id": record.id,
                    "version_no": record.current_version,
                    "saved": False,
                }

        if record is None:
            record = MedicalRecord(
                encounter_id=encounter_id,
                record_type=record_type,
                status="editing",
                current_version=0,
                record_no=await self._next_record_no(encounter_id, record_type),
                # 记录时间兜底（2026-09-02 住院支线实测补）：缺省取当下。
                # 此前四个建记录点里只有 auto_save_draft 一处传 recorded_at，
                # 而前端新建病程时明确「不发 recorded_at：留服务器取 now」——
                # 服务器却从来没取。结果生产库 46 份病历 recorded_at **全为 NULL**，
                # 而 is_late_entry() 遇 None 直接 return False，整条补记判定链路
                # （record_time.py 声称的「一定把它标出来」）从未激活过一次。
                # 缺省取 now 后：正常书写 recorded_at≈created_at 不判补记；
                # 医生把它改成更早的诊疗时点，差值超阈值才标补记——机制才真正活。
                # 记录时间兜底用 func.now()，与 created_at **同一个时钟源**（2026-09-02）：
                # created_at 由 TimestampMixin 的 func.now() 在数据库端生成，若这里改用
                # 应用进程的 datetime.now()，两个值就来自两台机器的两个时钟，而
                # is_late_entry() 恰恰是拿它们相减——生产上靠「PG 连接设了
                # timezone=Asia/Shanghai、应用容器也是北京时间」才勉强对齐，任一侧
                # 配置漂了就是 8 小时系统性偏移（SQLite 测试库正是如此）。同源则恒等。
                recorded_at=func.now(),
            )
            self.db.add(record)
            await self.db.flush()  # 拿到 record.id

        new_version_no = record.current_version + 1
        version = RecordVersion(
            medical_record_id=record.id,
            version_no=new_version_no,
            content={"text": content},  # 与 quick_save 保持同一存储格式
            source="ai_generated",
            triggered_by=user_id,
        )
        self.db.add(version)
        record.current_version = new_version_no
        record.status = "editing"
        await self.db.commit()
        # commit 后 ORM 属性过期，异步访问会炸（MissingGreenlet）——refresh 后再读
        await self.db.refresh(record)

        from app.services.encounter_service import invalidate_encounter_snapshot
        await invalidate_encounter_snapshot(encounter_id)
        return {
            "record_id": record.id,
            "version_no": new_version_no,
            "saved": True,
            # 前端 auto-save 乐观锁基线同步用（2026-08-21 第四轮走查：生成落库后
            # 前端基线不知道这次写入，下一次 auto-save 必假 409）
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }
