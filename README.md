# Export_to_UE

Blender 5.x 扩展：将模型导出到 Unreal Engine（FBX），通过 3dsmaxbatch.exe 转存 .max（项目归档），并支持导入 .max 时自动换算单位。

## 功能

### 1. Export to UE (FBX)
- 将选中模型按 M2 规范导出为 FBX
- `Check`：导出前运行规范检查（命名 / 几何 / 材质 / 碰撞 / LOD 等 16 项，可在齿轮图标中配置）
- `Selected Objects`：仅导出选中模型
- `Independent LOD`：单独处理 LOD 组
- `+90° on Z`：适配 Unreal Engine 坐标系（Y-forward）

### 2. Save as .Max（项目归档）
- 通过 `3dsmaxbatch.exe` 将 FBX 转为 .max 文件
- 需在设置中配置 `3dsmaxbatch.exe` 路径（3ds Max 版本按项目要求显式指定）
- 转换在后台队列执行，可连续点击多个任务
- `Use Blender File Name`：勾选时 .max 文件名跟随当前 .blend 文件名
- 已在 3ds Max 2019 上端到端验证（FBX 导入 → XForm 复位 → 材质名规范化 → 保存为 2019 格式 .max）
- ⚠️ 已知限制：3ds Max 2024 的 `3dsmaxbatch.exe` 批量保存会失败并崩溃（`saveMaxFile` 返回 false，进程退出码 0xC0000005），请为 Save as .Max 配置 2019–2023 任一版本；2024 仍可用于 Import Max 单位读取

### 3. Import Max with Units（导入 .max 并换算单位）
- 入口：`File > Import > Autodesk MAX (.max) with Units`
- 自动读取 .max 文件的系统单位（通过 3dsmaxbatch.exe + MaxScript `loadMaxFile ... useFileUnits:true`，可靠且跳过单位弹窗）
- 导入前先二进制解析 .max 文件版本（毫秒级，无需启动 3ds Max），自动匹配本机 ≥ 文件版本的最接近 3ds Max 安装来读取单位（旧版 3ds Max 无法打开新版 .max 文件）；无匹配时重扫安装列表重试
- 与 Blender 场景单位（`Scene > Units`）比较后自动计算缩放系数，导入时应用
- 导入前弹出确认对话框：显示检测到的文件版本、Max 文件单位、Blender 场景单位与缩放系数，可手动覆盖
- 未安装 3ds Max、文件版本高于本机所有安装或读取失败时，可在对话框中手动选择单位
- 例：Max 中 100 cm 的模型，导入 1 unit = 1 m 的 Blender 场景后正确显示为 1 m

### 4. Plugin Update
- 从 GitHub 检查并安装新版本

### 5. Help（帮助）
- 独立 `Help` 面板（Export_To_UE 侧栏），点击 `Open Help` 查看完整文档

## 安装

1. Blender 4.2+ 偏好设置 → 扩展 → 安装，选择本扩展 zip
2. 启用 `Export To UE`

## 3ds Max 配置

- `Save as .Max` 面板 → 齿轮图标 → 配置 `3dsmaxbatch.exe` 路径（如 `G:\Program Files\Autodesk\3ds Max 2019\3dsmaxbatch.exe`；避免使用 2024，见上文已知限制）
- Import Max 单位读取优先使用该配置；未配置时自动探测常见安装路径，多版本时按"文件版本匹配 → 最近更高版本"选择，无版本信息时选用最新安装

## 单位换算原理

- 3ds Max 文件内部记录 File Unit Scale；通过 `loadMaxFile <file> quiet:true useFileUnits:true` 采用文件单位后读取 `units.SystemType` / `units.SystemScale`
- Blender 侧：1 Blender unit = `Scene.Unit Settings.Scale Length` 米
- 缩放系数 = Max 每单位米数 ÷ Blender 每单位米数，传给内置导入器的 `scale_objects` 参数（应用变换到网格数据）

## 开发

- Blender exe：`G:\Program Files\Blender Foundation\Blender 5.2\blender.exe`
- Headless 测试：`blender.exe --background --python <test>.py`
- 测试脚本禁用 `read_factory_settings()`（会禁用扩展），用手动删除场景对象代替
