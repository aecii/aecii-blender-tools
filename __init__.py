bl_info = {
    "name": "aecii's Tools",
    "author": "aecii & claude",
    "version": (1, 4, 0),
    "blender": (4, 5, 0),
    "location": "View3D > N Panel > aecii's tools",
    "category": "Rigging",
}

import bpy
import re
import numpy as np
from concurrent.futures import ThreadPoolExecutor


# =========================================================
# SETTINGS
# =========================================================

class AECII_Settings(bpy.types.PropertyGroup):

    keep_non_deform: bpy.props.BoolProperty(
        name="Keep Non-Deform Bones",
        default=False
    )

    keep_parent_chains: bpy.props.BoolProperty(
        name="Keep Parent Chains",
        default=False
    )

    enable_logging: bpy.props.BoolProperty(
        name="Verbose Logging",
        default=False
    )

    # ── Shape Key Search ──────────────────────────────────
    sk_search_text: bpy.props.StringProperty(
        name="Search",
        description="Filter shape keys by name",
        default="",
        options={"TEXTEDIT_UPDATE"},
    )


# =========================================================
# RESET SETTINGS OPERATOR
# =========================================================

class AECII_OT_ResetDefaults(bpy.types.Operator):
    bl_idname = "aecii.reset_defaults"
    bl_label = "Reset To Defaults"

    def execute(self, context):

        s = context.scene.aecii_tools

        s.keep_non_deform = False
        s.keep_parent_chains = False
        s.enable_logging = False

        self.report({'INFO'}, "aecii Tools reset to defaults")
        return {'FINISHED'}


# =========================================================
# LOGGING
# =========================================================

def log(op, settings, msg):
    if settings.enable_logging:
        print("[aecii tools]:", msg)
        if op:
            op.report({'INFO'}, msg)


# =========================================================
# TARGET INFO
# =========================================================

def get_object_info(context):

    obj = context.active_object

    if not obj:
        return ("Please select a valid object", "ERROR")

    if obj.type == 'ARMATURE':
        return (f"Armature: {obj.name}", "GOOD")

    arm = obj.find_armature()
    if arm:
        return (f"{obj.name} (Armature: {arm.name})", "GOOD")

    if obj.type == 'MESH':
        return (f"{obj.name} (No Armature)", "WARN")

    return (f"{obj.name} (Unsupported Type)", "ERROR")


def status_icon(status):
    return {
        "GOOD": "CHECKMARK",
        "WARN": "ERROR",
        "ERROR": "CANCEL"
    }.get(status, "QUESTION")


# =========================================================
# UNUSED BONES
# =========================================================

def get_armature_meshes(arm_obj):
    return [
        obj for obj in bpy.data.objects
        if obj.type == 'MESH' and obj.find_armature() == arm_obj
    ]


def get_used_bone_names(meshes):
    used = set()
    for mesh in meshes:
        for vg in mesh.vertex_groups:
            used.add(vg.name)
    return used


def expand_with_parents(edit_bones, bone_names):
    expanded = set(bone_names)
    for name in list(bone_names):
        bone = edit_bones.get(name)
        while bone and bone.parent:
            expanded.add(bone.parent.name)
            bone = bone.parent
    return expanded


class AECII_OT_RemoveUnusedBones(bpy.types.Operator):
    bl_idname = "aecii.remove_unused_bones"
    bl_label = "Remove Unused Bones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        settings = context.scene.aecii_tools
        obj = context.active_object

        if not obj:
            return {'CANCELLED'}

        arm = obj if obj.type == 'ARMATURE' else obj.find_armature()
        if not arm:
            return {'CANCELLED'}

        log(self, settings, f"Bone cleanup running on {arm.name}")

        old_active = context.view_layer.objects.active
        old_mode = context.mode

        context.view_layer.objects.active = arm
        arm.select_set(True)

        meshes = get_armature_meshes(arm)
        used_bones = get_used_bone_names(meshes)

        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = arm.data.edit_bones

        if settings.keep_parent_chains:
            used_bones = expand_with_parents(edit_bones, used_bones)

        to_delete = []

        for bone in edit_bones:

            keep = False

            if bone.name in used_bones:
                keep = True

            if settings.keep_non_deform and not bone.use_deform:
                keep = True

            if not keep:
                to_delete.append(bone.name)

        for name in to_delete:
            if name in edit_bones:
                edit_bones.remove(edit_bones[name])

        bpy.ops.object.mode_set(mode='OBJECT')

        context.view_layer.objects.active = old_active
        try:
            bpy.ops.object.mode_set(mode=old_mode.replace('_', ''))
        except:
            pass

        return {'FINISHED'}


# =========================================================
# EMPTY VERTEX GROUPS
# =========================================================

class AECII_OT_RemoveEmptyVertexGroups(bpy.types.Operator):
    bl_idname = "aecii.remove_empty_vertex_groups"
    bl_label = "Remove Empty Vertex Groups"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        settings = context.scene.aecii_tools
        ob = context.active_object

        if not ob or ob.type != 'MESH':
            return {'CANCELLED'}

        log(self, settings, f"Vertex cleanup running on {ob.name}")

        if context.mode == 'EDIT_MESH':
            ob.update_from_editmode()

        vgroup_used = {i: False for i in range(len(ob.vertex_groups))}

        for v in ob.data.vertices:
            for g in v.groups:
                if g.weight > 0:
                    vgroup_used[g.group] = True

        for i, used in sorted(vgroup_used.items(), reverse=True):
            if not used:
                ob.vertex_groups.remove(ob.vertex_groups[i])

        return {'FINISHED'}


# =========================================================
# BLENDSHAPE CLEANUP
# =========================================================

def compare_shape_chunk(chunk, tolerance):
    results = []
    for name, diff in chunk:
        if (np.abs(diff) < tolerance).all():
            results.append(name)
    return results


class AECII_OT_RemoveEmptyBlendshapes(bpy.types.Operator):
    bl_idname = "aecii.remove_empty_blendshapes"
    bl_label = "Remove Empty Blendshapes"
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: bpy.props.FloatProperty(default=0.001)
    threads: bpy.props.IntProperty(default=4, min=1, max=32)

    def execute(self, context):

        if context.mode != 'OBJECT':
            return {'CANCELLED'}

        for ob in context.selected_objects:

            if ob.type != 'MESH':
                continue
            if not ob.data.shape_keys:
                continue

            kbs = ob.data.shape_keys.key_blocks
            nverts = len(ob.data.vertices)

            cache = {}
            comparisons = []

            for kb in kbs:

                if kb == kb.relative_key:
                    continue

                locs = np.empty(3*nverts, dtype=np.float32)
                kb.data.foreach_get("co", locs)

                if kb.relative_key.name not in cache:
                    rel = np.empty(3*nverts, dtype=np.float32)
                    kb.relative_key.data.foreach_get("co", rel)
                    cache[kb.relative_key.name] = rel

                diff = locs - cache[kb.relative_key.name]
                comparisons.append((kb.name, diff))

            chunk_size = max(1, len(comparisons)//self.threads)
            chunks = [
                comparisons[i:i+chunk_size]
                for i in range(0, len(comparisons), chunk_size)
            ]

            to_delete = []

            with ThreadPoolExecutor(max_workers=self.threads) as exe:
                futures = [
                    exe.submit(compare_shape_chunk, c, self.tolerance)
                    for c in chunks
                ]
                for f in futures:
                    to_delete.extend(f.result())

            for name in to_delete:
                ob.shape_key_remove(
                    ob.data.shape_keys.key_blocks[name]
                )

        return {'FINISHED'}


# =========================================================
# SHAPE KEY SEARCH — OPERATORS
# =========================================================

class AECII_OT_SKSearchSelect(bpy.types.Operator):
    """Set this as the active shape key"""
    bl_idname = "aecii.sk_search_select"
    bl_label = "Select Shape Key"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        obj = context.active_object
        if obj and obj.data and obj.data.shape_keys:
            obj.active_shape_key_index = self.index
        return {'FINISHED'}


class AECII_OT_SKSearchClear(bpy.types.Operator):
    """Clear the shape key search field"""
    bl_idname = "aecii.sk_search_clear"
    bl_label = "Clear Search"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.scene.aecii_tools.sk_search_text = ""
        return {'FINISHED'}


# =========================================================
# UI PANEL
# =========================================================

class AECII_PT_MainPanel(bpy.types.Panel):
    bl_label = "aecii's tools"
    bl_idname = "AECII_PT_MAIN"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "aecii's tools"

    def draw(self, context):

        layout = self.layout
        settings = context.scene.aecii_tools

        # ── Object info ───────────────────────────────────
        text, status = get_object_info(context)

        box = layout.box()
        box.label(text=text, icon=status_icon(status))

        layout.separator()

        # ── Settings ──────────────────────────────────────
        box = layout.box()
        box.prop(settings, "keep_non_deform")
        box.prop(settings, "keep_parent_chains")
        box.prop(settings, "enable_logging")
        box.operator("aecii.reset_defaults", icon="FILE_REFRESH")

        layout.separator()

        # ── Bone / vertex group tools ─────────────────────
        col = layout.column(align=True)
        col.operator("aecii.remove_unused_bones")
        col.operator("aecii.remove_empty_vertex_groups")

        layout.separator()

        # ── Blendshape cleanup ────────────────────────────
        col = layout.column(align=True)
        col.operator("aecii.remove_empty_blendshapes")

        layout.separator()

        # ── Shape Key Search ──────────────────────────────
        self._draw_sk_search(context, layout)

    # ----------------------------------------------------------
    def _draw_sk_search(self, context, layout):

        obj = context.active_object

        header, panel = layout.panel("aecii_sk_search", default_closed=False)
        header.label(text="Shape Key Search", icon="SHAPEKEY_DATA")

        if panel is None:
            return   # collapsed

        # Guard: need a mesh with shape keys selected
        if (
            not obj
            or obj.type != 'MESH'
            or not obj.data
            or not obj.data.shape_keys
            or len(obj.data.shape_keys.key_blocks) == 0
        ):
            panel.label(text="Select a mesh with shape keys.", icon="INFO")
            return

        settings = context.scene.aecii_tools
        key_blocks = obj.data.shape_keys.key_blocks

        # Search bar
        row = panel.row(align=True)
        row.prop(settings, "sk_search_text", icon="VIEWZOOM", text="")
        row.operator("aecii.sk_search_clear", text="", icon="X")

        query = settings.sk_search_text.strip().lower()

        if query == "":
            panel.label(text=f"{len(key_blocks)} shape key(s) on this mesh.", icon="INFO")
            return

        matches = [
            (i, kb)
            for i, kb in enumerate(key_blocks)
            if query in kb.name.lower()
        ]

        if not matches:
            panel.label(text="No matches found.", icon="ERROR")
            return

        active_idx = obj.active_shape_key_index
        box = panel.box()
        col = box.column(align=True)

        for idx, kb in matches:
            is_active = (idx == active_idx)
            row = col.row(align=True)

            op = row.operator(
                "aecii.sk_search_select",
                text=kb.name,
                icon="SHAPEKEY_DATA" if is_active else "NONE",
                depress=is_active,
            )
            op.index = idx

            # Inline value slider
            row.prop(kb, "value", text="", slider=True)

        col.separator()
        col.label(text=f"{len(matches)} of {len(key_blocks)} shown")


# =========================================================
# REGISTER
# =========================================================

classes = (
    AECII_Settings,
    AECII_OT_ResetDefaults,
    AECII_OT_RemoveUnusedBones,
    AECII_OT_RemoveEmptyVertexGroups,
    AECII_OT_RemoveEmptyBlendshapes,
    AECII_OT_SKSearchSelect,
    AECII_OT_SKSearchClear,
    AECII_PT_MainPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.aecii_tools = bpy.props.PointerProperty(
        type=AECII_Settings
    )


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.aecii_tools


if __name__ == "__main__":
    register()
