/**
 * 检查单气泡卡片（components/workbench/LabOrderPopover.tsx）
 *
 * RecordEditor 工具栏中的「检查单」气泡菜单，管理当前接诊的检查项目：
 *   - 展示 ExamSuggestionTab 中「加入检查单」的所有检查项
 *   - 支持手动添加自定义检查项（Input + 确认）
 *   - Checkbox 可取消勾选不需要的检查项
 *   - 点击「写入病历」将勾选项格式化写入辅助检查字段
 *
 * 无独立 API 调用：
 *   检查单数据只在 workbenchStore.examOrders 中维护，
 *   通过 writeSectionToRecord 写入病历后才持久化到服务端。
 */
import { useState } from 'react'
import { Button, Checkbox, Popover, Input } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

interface Props {
  onInsert: (text: string) => void
}

const LAB_CATEGORIES: { label: string; color: string; items: string[] }[] = [
  {
    label: '血液类',
    color: '#fee2e2',
    items: [
      '血常规',
      '凝血四项',
      '血型鉴定+交叉配血',
      'ESR血沉',
      'CRP',
      '降钙素原(PCT)',
      'D-二聚体',
    ],
  },
  {
    label: '生化类',
    color: '#fef9c3',
    items: [
      '生化全套',
      '肝功能',
      '肾功能',
      '血脂全套',
      '空腹血糖',
      '电解质',
      '心肌酶谱',
      'BNP/NT-proBNP',
      '淀粉酶+脂肪酶',
    ],
  },
  {
    label: '肿瘤标志物',
    color: '#fce7f3',
    items: ['AFP', 'CEA', 'CA199', 'CA125', 'CA153', 'PSA', 'NSE', 'CYFRA21-1', 'SCC'],
  },
  {
    label: '免疫/感染',
    color: '#ede9fe',
    items: [
      '乙肝五项',
      '丙肝抗体',
      'HIV抗体',
      '梅毒螺旋体抗体',
      'ANA+ANCA',
      '补体C3/C4',
      '结核T-SPOT',
    ],
  },
  {
    label: '尿/便',
    color: '#d1fae5',
    items: ['尿常规', '尿培养+药敏', '大便常规+潜血'],
  },
  {
    label: '影像/功能',
    color: '#dbeafe',
    items: [
      '心电图',
      '胸部X光',
      '腹部超声',
      '心脏超声',
      '胸部CT',
      '腹部CT',
      '头颅CT',
      'MRI(部位待定)',
    ],
  },
]

export default function LabOrderPopover({ onInsert }: Props) {
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [open, setOpen] = useState(false)
  const [customItem, setCustomItem] = useState('')

  const toggle = (item: string) => {
    setSelected(prev => ({ ...prev, [item]: !prev[item] }))
  }

  const selectedItems = Object.entries(selected)
    .filter(([, v]) => v)
    .map(([k]) => k)

  const handleInsert = () => {
    const all = [...selectedItems]
    if (customItem.trim()) all.push(customItem.trim())
    if (all.length === 0) return

    // Group by category for formatted output
    const grouped: Record<string, string[]> = {}
    for (const item of all) {
      let cat = '其他'
      for (const c of LAB_CATEGORIES) {
        if (c.items.includes(item)) {
          cat = c.label
          break
        }
      }
      if (!grouped[cat]) grouped[cat] = []
      grouped[cat].push(item)
    }

    const lines = ['【拟行检查】']
    for (const [cat, items] of Object.entries(grouped)) {
      lines.push(`${cat}：${items.join('、')}`)
    }

    onInsert(lines.join('\n'))
    setSelected({})
    setCustomItem('')
    setOpen(false)
  }

  const content = (
    <div style={{ width: 360, maxHeight: 480, overflowY: 'auto' }}>
      {LAB_CATEGORIES.map(cat => (
        <div key={cat.label} style={{ marginBottom: 10 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: '#374151',
              background: cat.color,
              padding: '2px 8px',
              borderRadius: 4,
              marginBottom: 6,
            }}
          >
            {cat.label}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 0' }}>
            {cat.items.map(item => (
              <Checkbox
                key={item}
                checked={!!selected[item]}
                onChange={() => toggle(item)}
                style={{ fontSize: 12, marginLeft: 0, width: '50%' }}
              >
                {item}
              </Checkbox>
            ))}
          </div>
        </div>
      ))}

      {/* Custom item */}
      <div style={{ marginTop: 8, borderTop: '1px solid #f1f5f9', paddingTop: 8 }}>
        <Input
          size="small"
          placeholder="其他检查项目（自定义）"
          value={customItem}
          onChange={e => setCustomItem(e.target.value)}
          style={{ borderRadius: 5, fontSize: 12, marginBottom: 8 }}
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 11, color: '#94a3b8' }}>
          已选 {selectedItems.length + (customItem.trim() ? 1 : 0)} 项
        </span>
        <Button
          type="primary"
          size="small"
          onClick={handleInsert}
          disabled={selectedItems.length === 0 && !customItem.trim()}
          style={{
            background: 'linear-gradient(135deg, #2563eb, #3b82f6)',
            border: 'none',
            borderRadius: 6,
            fontSize: 12,
          }}
        >
          插入辅助检查
        </Button>
      </div>
    </div>
  )

  return (
    <Popover
      content={content}
      title={<span style={{ fontSize: 13, fontWeight: 700 }}>快速开单</span>}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="rightTop"
    >
      <Button
        size="small"
        icon={<PlusOutlined />}
        style={{
          fontSize: 11,
          borderRadius: 6,
          color: '#2563eb',
          borderColor: '#bfdbfe',
          background: '#eff6ff',
        }}
      >
        快速开单
      </Button>
    </Popover>
  )
}
