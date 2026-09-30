import Placeholder from "../components/Placeholder";

export default function Replay() {
  return (
    <Placeholder
      title="回放分析"
      items={[
        "发次归档浏览（后端 /api/sessions 已就绪：一发次一目录 + manifest.json）",
        "CSV 导入与字段/频率校验",
        "3D 轨迹重建（three.js：路径 + 姿态模型 + 时间轴拖动）",
        "相机录像与 3D、曲线同轴联动",
        "画面轨迹叠加（需相机标定，二期）",
      ]}
    />
  );
}
