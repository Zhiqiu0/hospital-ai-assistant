/**
 * PACS 工作台类型定义（pages/pacs/types.ts）
 */

/** R1 后端返回的帧描述：SOPInstanceUID + 所属 series + DICOM InstanceNumber */
export interface Frame {
  instance_uid: string
  series_uid: string
  instance_number: number
}

/** PACS 影像研究主记录（影像列表项） */
export interface Study {
  study_id: string
  patient_id: string
  modality: string
  body_part: string
  series_description: string
  total_frames: number
  status: string
  created_at: string
}

/** 工作台 4 阶段状态机 */
export type Stage = 'list' | 'select_frames' | 'analyzing' | 'report'
