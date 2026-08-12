import bpy
import os
import shutil


def get_ue_parent_material(material):
    """Get the UE parent material name from a Blender material.

    Looks for a custom property 'ue_parent_material' on the material.

    Args:
        material: bpy.types.Material

    Returns:
        str or None - UE parent material path/name
    """
    if not material:
        return None

    # Check for the custom property
    if material.get("ue_parent_material"):
        return material["ue_parent_material"]

    # Also check the material's ID properties
    for prop_name in material.keys():
        if "ue_parent" in prop_name.lower():
            return str(material[prop_name])

    return None


def get_material_mapping_report(objects):
    """Generate a report of material mappings for the given objects.

    Args:
        objects: List of blender objects

    Returns:
        dict: {material_name: ue_parent_material or None}
    """
    mapping = {}
    seen_materials = set()

    for obj in objects:
        if obj.type != 'MESH':
            continue
        for mat_slot in obj.material_slots:
            mat = mat_slot.material
            if mat and mat.name not in seen_materials:
                seen_materials.add(mat.name)
                ue_parent = get_ue_parent_material(mat)
                mapping[mat.name] = ue_parent

    return mapping


def export_textures(objects, export_path, texture_path):
    """Export all textures used by the given objects to the specified path.

    Args:
        objects: List of blender objects
        export_path: Base export directory
        texture_path: Specific texture export directory

    Returns:
        int: Number of textures exported
    """
    if not texture_path:
        texture_path = os.path.join(export_path, "Textures")

    os.makedirs(texture_path, exist_ok=True)

    exported = set()
    count = 0

    for obj in objects:
        if obj.type != 'MESH':
            continue

        # Get all materials on the object
        for mat_slot in obj.material_slots:
            mat = mat_slot.material
            if not mat:
                continue

            # Find all image textures in the material
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and hasattr(node, 'image') and node.image:
                    img = node.image
                    if img.name in exported:
                        continue

                    # Determine source path
                    if img.source == 'FILE' and img.filepath:
                        src_path = bpy.path.abspath(img.filepath)
                        if os.path.exists(src_path):
                            # Copy to texture export directory
                            ext = os.path.splitext(src_path)[1]
                            dst_path = os.path.join(texture_path, img.name + ext)
                            if not os.path.exists(dst_path):
                                shutil.copy2(src_path, dst_path)
                                exported.add(img.name)
                                count += 1
                                print(f"  Exported texture: {img.name}{ext}")
                    elif img.source == 'GENERATED':
                        # Save generated image to disk
                        ext = '.png'
                        dst_path = os.path.join(texture_path, img.name + ext)
                        img.save(filepath=dst_path)
                        exported.add(img.name)
                        count += 1
                        print(f"  Exported generated texture: {img.name}{ext}")

    return count
