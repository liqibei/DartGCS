/** 占位页：展示该页面在路线图中的规划功能，后端接口已预留。 */
export default function Placeholder({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="page">
      <h2>{title}</h2>
      <p className="muted">框架占位页 —— 功能按路线图逐批实现，数据接口已在后端预留。</p>
      <ul className="plan">
        {items.map((it) => (
          <li key={it}>{it}</li>
        ))}
      </ul>
    </div>
  );
}
