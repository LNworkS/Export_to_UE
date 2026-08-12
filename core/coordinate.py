import bpy
import mathutils
from mathutils import Vector, Matrix, Euler

# Coordinate system conversion constants
# Blender: Z-up, right-handed (X-right, Y-forward, Z-up)
# UE: Z-up, left-handed (X-forward, Y-right, Z-up) - after FBX import
#
# The conversion:
#   UE_X = Blender_Y
#   UE_Y = Blender_X (negated for handedness)
#   UE_Z = Blender_Z
#
# Or equivalently: swap X↔Y, negate the new Y

def get_blender_to_ue_matrix():
    """Get the 4x4 transformation matrix from Blender basis to UE basis.

    Blender (X-right, Y-forward, Z-up, right-handed)
    UE (X-forward, Y-right, Z-up, left-handed after FBX import)

    The conversion is:
      UE.x = Blender.y
      UE.y = Blender.x  (negated for left-handed)
      UE.z = Blender.z

    Or in matrix form (applied as C4 * M_bl * C4^{-1}):
    """
    C = Matrix((
        (0, 1, 0, 0),
        (-1, 0, 0, 0),
        (0, 0, 1, 0),
        (0, 0, 0, 1),
    ))
    return C


def convert_transform_to_ue(location, rotation, scale):
    """Convert a Blender transform to UE coordinate system.

    Uses unified matrix approach: M_ue = C4 * M_bl * C4^{-1}

    Args:
        location: Vector (3-tuple) - Blender location
        rotation: Euler or Quaternion - Blender rotation
        scale: Vector (3-tuple) - Blender scale

    Returns:
        (location_ue, rotation_ue, scale_ue) as tuple of (Vector, Euler('XYZ'), Vector)
    """
    C = get_blender_to_ue_matrix()
    C_inv = C.inverted()

    # Build Blender transform matrix
    M_bl = Matrix.Translation(location)

    if isinstance(rotation, Euler):
        M_bl = M_bl @ rotation.to_matrix().to_4x4()
    elif isinstance(rotation, mathutils.Quaternion):
        M_bl = M_bl @ rotation.to_matrix().to_4x4()
    else:
        M_bl = M_bl @ Matrix.Rotation(rotation, 3).to_4x4()

    M_bl = M_bl @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))

    # Apply basis change: M_ue = C * M_bl * C^{-1}
    M_ue = C @ M_bl @ C_inv

    # Decompose UE transform
    loc_ue, rot_ue, scale_ue = M_ue.decompose()

    # Convert rotation to Euler XYZ (UE uses this convention for import)
    rot_euler_ue = rot_ue.to_euler('XYZ')

    return (loc_ue, rot_euler_ue, scale_ue)


def apply_transform_to_ue(obj):
    """Get UE-space transform for a Blender object.

    Returns the object's matrix_world converted to UE space.
    This does NOT modify the original object.

    Returns:
        (location, rotation_euler_xyz, scale)
    """
    world_matrix = obj.matrix_world
    C = get_blender_to_ue_matrix()
    C_inv = C.inverted()

    M_ue = C @ world_matrix @ C_inv

    loc_ue, rot_ue, scale_ue = M_ue.decompose()
    rot_euler_ue = rot_ue.to_euler('XYZ')

    return (loc_ue, rot_euler_ue, scale_ue)


def sanitize_vector(vec):
    """Clean up tiny floating-point values (round to zero)."""
    threshold = 1e-6
    return Vector((
        round(vec.x, 6) if abs(vec.x) < threshold * 10 else vec.x,
        round(vec.y, 6) if abs(vec.y) < threshold * 10 else vec.y,
        round(vec.z, 6) if abs(vec.z) < threshold * 10 else vec.z,
    ))
