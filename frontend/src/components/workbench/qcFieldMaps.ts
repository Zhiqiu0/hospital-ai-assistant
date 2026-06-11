/**
 * QC 字段映射常量 + 记录内容写入工具（桶文件）
 *
 * 2026-06-11 拆分：原 858 行超标文件按职责拆为 4 个模块，
 * 这里统一 re-export 保持既有 import 路径全部兼容：
 *   - qcFieldConstants.ts    字段→章节/子行 映射表
 *   - qcFieldMeta.ts         问诊键/中文标签/不可写字段
 *   - recordSectionWriter.ts 章节与子行写入核心（含复合段合并保护）
 *   - recordFieldState.ts    写入前快照/撤销/光标定位
 */
export * from './qcFieldConstants'
export * from './qcFieldMeta'
export * from './recordSectionWriter'
export * from './recordFieldState'
