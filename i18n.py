"""Internationalization module for Export_To_UE addon.

Detects Blender's language setting and provides translation between
English and Simplified Chinese. Both Simplified Chinese (zh_HANS) and
Traditional Chinese (zh_HANT) use Simplified Chinese translations.
All other languages use English.
"""

import bpy


# ============================================================
# Translation dictionary: English -> Simplified Chinese
# ============================================================

_TRANSLATIONS = {
    # ---- Panel & UI labels ----
    "Export to Unreal Engine": "导出到Unreal引擎",
    "FBX Export": "FBX导出",
    "Selected Objects": "选中的物体",
    "Independent LOD": "独立导出LOD",
    "+90° on Z": "Z轴旋转+90°",
    "Check": "导出前检查",
    "Fixed Path": "固定路径",
    "Export to UE": "导出",
    "Export": "导出",
    "Cancel": "取消",

    # ---- Property descriptions (tooltips) ----
    "Export only selected objects": "仅导出选中的物体",
    "Handle LOD groups separately": "单独处理LOD组",
    "Apply +90\u00b0 Z rotation before export, then restore. Matches Unreal Engine coordinate system.": "导出前应用+90°Z轴旋转，导出后恢复。匹配Unreal引擎坐标系。",
    "Run validation checks before export. Show results in a dialog.": "导出前运行验证检查。在对话框中显示结果。",

    # ---- Validation check labels ----
    "Model Naming": "模型命名",
    "Transform Zeroed": "旋转位移缩放归零",
    "Loose Geometry": "孤立的点和线",
    "Overlapping Faces": "重叠的面",
    "Ngons (>4 verts)": "大于4个点的面",
    "Ngons (>N verts)": "大于N个点的面",
    "Vertex Color": "顶点着色",
    "UV Count": "UV数量",
    "Animation Data": "动画信息",
    "Material Count": "材质数量",
    "Material Naming": "材质命名",
    "Unused Materials": "未引用材质",
    "Collision Matching": "碰撞模型匹配",
    "LOD Matching": "LOD模型匹配",

    # ---- Validation detail messages ----
    "Not a mesh object": "非网格对象",
    "None": "无",
    "Model name invalid, cannot verify": "模型名不符合规则,无法校验",
    "No materials": "无材质",
    "does not start with mi_": "非mi_开头",
    "does not start with UCX_": "非UCX_开头",
    "no matching model": "未找到匹配模型",
    "invalid _LODx format": "不符合_LODx格式",
    "missing _XX suffix": "缺少_XX后缀",
    "Has animation Action": "有动画Action",
    "Has NLA tracks": "有NLA轨道",

    # ---- Popup dialog ----
    "Export Check Results": "导出检查结果",
    "Group Checks": "组检查",
    "Mesh": "网格",
    "Collision": "碰撞",

    # ---- Check settings dialog ----
    "Check Settings": "检查设置",
    "Mesh Checks": "模型检查",
    "Material Checks": "材质检查",

    # ---- Summary messages ----
    "error(s) in": "个错误，涉及",
    "group(s) - review before export": "个组 - 请检查后再导出",
    "warning(s) in": "个警告，涉及",
    "group(s)": "个组",
    "group(s) passed checks": "个组通过检查",
    "All": "全部",
    "Found": "发现",

    # ---- Report messages ----
    "Please select an export path or enable Fixed Path.": "请选择导出路径或启用固定路径。",
    "No objects to export.": "没有可导出的物体。",
    "Export cancelled": "导出已取消",
}


def is_chinese():
    """Check if Blender's language is set to Chinese (Simplified or Traditional).

    Returns True for both zh_HANS (Simplified) and zh_HANT (Traditional).
    Returns False for all other languages.
    """
    lang = bpy.context.preferences.view.language
    return lang.startswith('zh')


def t(text):
    """Translate text based on current Blender language setting.

    If language is Chinese (Simplified or Traditional), returns the
    Simplified Chinese translation from the dictionary.
    Otherwise, returns the original English text.

    Args:
        text: English text to translate.

    Returns:
        Translated text if Chinese, original text otherwise.
    """
    if is_chinese():
        return _TRANSLATIONS.get(text, text)
    return text
