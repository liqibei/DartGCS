import Placeholder from "../components/Placeholder";

export default function Launcher() {
  return (
    <Placeholder
      title="发射架"
      items={[
        "双相机实时画面（长焦/广角，WHEP 拉流，mediamtx 部署在 MiniPC）",
        "发射参数：一镖一参 ×4（yaw 偏置、蓄力补偿），参数注册表动态生成表单",
        "相机内录管理：启停 / 清单 / 下载 / 回放",
        "发射联锁自检：触发装置电量 ≥4V、编号确认、储能状态",
      ]}
    />
  );
}
