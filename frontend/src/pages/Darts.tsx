import Placeholder from "../components/Placeholder";

export default function Darts() {
  return (
    <Placeholder
      title="飞镖"
      items={[
        "飞镖编队视图：编号 / 电量 / 固件版本 / 链路质量",
        "编号分配（SET_ID 写入 flash）",
        "控制参数调参：固件 catalog 动态生成表单 + 三层生命周期（默认/已存/会话）",
        "遥测示波：订阅制变量选择 + 触发记录",
        "飞行 CSV 日志读回（文件分块传输）",
      ]}
    />
  );
}
