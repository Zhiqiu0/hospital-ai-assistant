# -*- coding: utf-8 -*-
"""《门诊接诊至病历生成全流程说明_v2》PDF 过期段落局部替换（2026-08-17 发文前终审）。

这份 PDF 是 2026-07-14 用浏览器打印出来的，源 HTML 已失传、仓库里也没有，
只能直接改 PDF 本体。改 6 处（都是当时「诊室 Agent / 双通道二选一」旧架构口径，
与 v1.4 单通道规范矛盾，厂商两份一起读会看到相反说法）：
  P1  流程总览注：「工作台自动弹出并定位患者」→ 派入医生工作台并叫号提醒；
      「调用 HIS 病历回写接口」→ 沿同一连接下发
  P2  「自动免登录」→ 派入已登录的浏览器工作台
  P5  「工作台自动弹出并完成建档定位」→ 自动建档派入、叫号提醒、医生点击进入
  P21 表格「工作台自动弹出、免登录」→ 叫号提醒口径
  P21 推送内容含「设备 IP」→ 删（v1.4 已改为选填排障留痕）
  P21 「两种通道均支持（HTTPS/WS 二选一）」整段 → 已确认单一 WebSocket
首页/尾页日期 2026 年 7 月 / 2026-07-14 保留不动（截图确实是那时拍的），文件名 v2 不变。

做法：按行几何量出的精确矩形红删原文 → 原矩形内用微软雅黑重排新文字（字号 9.5 同原文）。
矩形是对着 07-14 原版量的，**只能对原版跑一次**；已修补版含标记句时脚本会拒绝再跑。
入库的 docs/ 副本即已修补版；再改请以它为母本另量矩形。

用法：python scripts/patch_flow_doc_pdf_v2.py <原版pdf> <输出pdf>
"""
import sys
import fitz

sys.stdout.reconfigure(encoding="utf-8")

if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(2)
SRC, OUT = sys.argv[1], sys.argv[2]
FONT = r"C:\Windows\Fonts\msyh.ttc"
SIZE = 9.5
ALREADY_MARK = "已双方确认采用"  # 修补后 P21 才有的句子，用作防重跑标记（重排后的空格会被提取成 \xa0，标记里不含空格）

# (页号0基, 红删矩形, 写入矩形, 新文字)  —— 矩形来自 get_text('dict') 实测行框
EDITS = [
    (0, fitz.Rect(50.2, 430.9, 795.0, 460.0), fitz.Rect(50.2, 429.5, 800.0, 465.0),
     "■ 黄色环节为与 HIS 的两个衔接点：①「接诊建档」由 HIS 接诊推送触发替代（推送就诊流水号 + 患者基本信息，"
     "患者自动派入医生工作台并叫号提醒）；⑧「签发归档」后\n沿同一连接下发病历回写（写入 + 刷新，"
     "以就诊流水号对应到当次就诊）。中间 ②-⑦ 全部在 MediScribe 内完成，不依赖 HIS 推送任何病历内容。"),
    (4, fitz.Rect(50.2, 127.2, 795.0, 156.2), fitz.Rect(50.2, 125.8, 800.0, 161.5),
     "与 HIS 对接后：这一步整体由 HIS 接诊推送替代——医生在 HIS 点「接诊」，HIS 将就诊流水号、患者姓名/性别/出生日期、"
     "科室、医生等基本信息推送给我方，我方\n自动建档并派入该医生工作台、叫号提醒，医生点击即进入，无需手工录入。"
     "就诊流水号将贯穿本次就诊，签发后回写时原样带回。"),
    (1, fitz.Rect(50.2, 143.7, 795.0, 156.2), fitz.Rect(50.2, 142.5, 800.0, 160.0),
     "与 HIS 对接后：接诊推送消息中携带医生工号，我方按工号自动把患者派入该医生已登录的浏览器工作台并叫号提醒，"
     "医生无需重复录入患者信息。"),
    (20, fitz.Rect(251.4, 156.4, 606.0, 185.5), fitz.Rect(251.4, 155.2, 606.0, 192.0),
     "就诊流水号、患者姓名/性别/出生日期、科室、医生、机构代码（此刻尚无主诉，不需推送）"),
    (20, fitz.Rect(624.4, 156.4, 795.0, 185.5), fitz.Rect(624.4, 154.5, 800.0, 196.5),
     "替代步骤 3「接诊建档」：患者自动\n派入医生工作台并叫号提醒"),
    (20, fitz.Rect(50.2, 246.4, 795.0, 292.0), fitz.Rect(50.2, 245.2, 795.0, 296.0),
     "关于传输通道：已双方确认采用 WebSocket 长连接（wss）——由 HIS 从院内主动向我方建立一条加密长连接，"
     "接诊消息沿此连接上行、病历回写沿同一连接下行；HIS 无需对外开放任何接口，我方也无需连入院内网、"
     "不在院内部署任何程序。消息字段、签名鉴权与幂等约定以双方接口规范（v1.4 单通道版）为准，与本文流程一一对应。"),
]

doc = fitz.open(SRC)
if ALREADY_MARK in doc[20].get_text():
    print("[跳过] 该 PDF 已是修补版，矩形是对原版量的，不能重复套用")
    sys.exit(0)
ok = True
for pno, kill, box, text in EDITS:
    page = doc[pno]
    page.add_redact_annot(kill)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    left = page.insert_textbox(box, text, fontname="msyh", fontfile=FONT,
                               fontsize=SIZE, lineheight=1.35, align=0)
    print(f"[{'改' if left >= 0 else '败(放不下)'}] 第{pno+1}页 剩余高度={left:.1f}｜{text[:18]}…")
    ok = ok and left >= 0

doc.save(OUT, garbage=3, deflate=True)
print("输出：", OUT, "OK" if ok else "有失败")
sys.exit(0 if ok else 1)
