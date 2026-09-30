import Placeholder from "../components/Placeholder";

export default function Base() {
  return (
    <Placeholder
      title="基地（目标运动模拟）"
      items={[
        "四档运动模式：固定 / 随机固定 / 随机移动 / 末端移动（1.2s 延迟）",
        "目标滑块手动点动（±280mm 行程，600ms 内到位）",
        "运动状态实时曲线与位置回读",
      ]}
    />
  );
}
