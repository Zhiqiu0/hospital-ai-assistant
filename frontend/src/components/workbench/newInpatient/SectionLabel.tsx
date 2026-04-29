/**
 * 住院弹窗内的分组小标签（newInpatient/SectionLabel.tsx）
 */
export default function SectionLabel({ text }: { text: string }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 700,
        color: '#065f46',
        background: '#f0fdf4',
        padding: '3px 8px',
        borderRadius: 4,
        marginBottom: 10,
        marginTop: 4,
      }}
    >
      {text}
    </div>
  )
}
