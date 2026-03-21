import { useState } from 'react'
import { Button, Input, Tooltip } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'

interface Props {
  onFill: (vitalText: string) => void
}

const inputStyle: React.CSSProperties = {
  borderRadius: 5,
  fontSize: 12,
  textAlign: 'center',
  padding: '2px 4px',
}

export default function VitalSignsInput({ onFill }: Props) {
  const [t, setT] = useState('')
  const [p, setP] = useState('')
  const [r, setR] = useState('')
  const [bpS, setBpS] = useState('')
  const [bpD, setBpD] = useState('')
  const [spo2, setSpo2] = useState('')
  const [h, setH] = useState('')
  const [w, setW] = useState('')

  const handleFill = () => {
    const parts: string[] = []
    if (t) parts.push(`T:${t}℃`)
    if (p) parts.push(`P:${p}次/分`)
    if (r) parts.push(`R:${r}次/分`)
    if (bpS || bpD) parts.push(`BP:${bpS || '__'}/${bpD || '__'}mmHg`)
    if (spo2) parts.push(`SpO₂:${spo2}%`)
    if (h) parts.push(`身高:${h}cm`)
    if (w) parts.push(`体重:${w}kg`)
    if (parts.length === 0) return
    onFill(parts.join('  '))
  }

  return (
    <div style={{
      background: '#f0f9ff',
      border: '1px solid #bae6fd',
      borderRadius: 8,
      padding: '10px 12px',
      marginBottom: 10,
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#0369a1', marginBottom: 8 }}>
        生命体征快速录入
      </div>

      {/* Row 1: T P R BP SpO2 */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
        <Tooltip title="体温 ℃">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: '#475569', whiteSpace: 'nowrap' }}>T</span>
            <Input value={t} onChange={e => setT(e.target.value)} placeholder="36.5"
              style={{ ...inputStyle, width: 52 }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>℃</span>
          </div>
        </Tooltip>

        <Tooltip title="脉搏 次/分">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: '#475569' }}>P</span>
            <Input value={p} onChange={e => setP(e.target.value)} placeholder="72"
              style={{ ...inputStyle, width: 46 }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>次/分</span>
          </div>
        </Tooltip>

        <Tooltip title="呼吸 次/分">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: '#475569' }}>R</span>
            <Input value={r} onChange={e => setR(e.target.value)} placeholder="18"
              style={{ ...inputStyle, width: 40 }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>次/分</span>
          </div>
        </Tooltip>

        <Tooltip title="血压 mmHg">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: '#475569' }}>BP</span>
            <Input value={bpS} onChange={e => setBpS(e.target.value)} placeholder="120"
              style={{ ...inputStyle, width: 44 }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>/</span>
            <Input value={bpD} onChange={e => setBpD(e.target.value)} placeholder="80"
              style={{ ...inputStyle, width: 40 }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>mmHg</span>
          </div>
        </Tooltip>

        <Tooltip title="血氧饱和度 %">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: '#475569' }}>SpO₂</span>
            <Input value={spo2} onChange={e => setSpo2(e.target.value)} placeholder="98"
              style={{ ...inputStyle, width: 40 }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>%</span>
          </div>
        </Tooltip>
      </div>

      {/* Row 2: H W + fill button */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <Tooltip title="身高 cm">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: '#475569' }}>身高</span>
            <Input value={h} onChange={e => setH(e.target.value)} placeholder="170"
              style={{ ...inputStyle, width: 46 }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>cm</span>
          </div>
        </Tooltip>

        <Tooltip title="体重 kg">
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 11, color: '#475569' }}>体重</span>
            <Input value={w} onChange={e => setW(e.target.value)} placeholder="65"
              style={{ ...inputStyle, width: 46 }} />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>kg</span>
          </div>
        </Tooltip>

        <Button
          size="small"
          type="primary"
          icon={<ThunderboltOutlined />}
          onClick={handleFill}
          style={{
            marginLeft: 'auto',
            background: '#0369a1',
            border: 'none',
            borderRadius: 6,
            fontSize: 11,
          }}
        >
          填入体格检查
        </Button>
      </div>
    </div>
  )
}
