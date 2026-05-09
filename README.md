# aecii's Tools — Blender Addon
**Version:** 1.4.0 | Blender 4.5+

A small rigging and mesh cleanup toolkit that lives in the N panel (View3D > aecii's tools).

---

## What's inside

**Remove Unused Bones** — Cleans up any bones in an armature that have no weighted vertices on any skinned mesh.

**Remove Empty Vertex Groups** — Removes vertex groups from a mesh that have zero weights assigned.

**Remove Empty Blendshapes** — Deletes shape keys that contain no actual deformation compared to their relative key.

**Shape Key Search** — Select a mesh and type to instantly filter its shape keys by name. Each result includes an inline value slider so you can tweak it on the spot.

<img width="1504" height="939" alt="image" src="https://github.com/user-attachments/assets/380207a9-9638-41f1-8998-7ec13d4fec10" />
<img width="1670" height="978" alt="image" src="https://github.com/user-attachments/assets/d5619023-d783-442d-820f-9abf42426982" />



Note: 
make a backup of anything you use this on. Just in case. 

Known issues: 
It will remove "Viseme_Sil",  "Sil", or any silence shape key if those blendshapes have 0 / neutral data in them. 
Be aware of that. Empty blend shape means empty blendshape. Maybe later I will find a way to exclude all silence vismemes. 

...I should probably rename "blendshapes" to "shapekeys" for consistency... But you know what I mean. 



## Need help?

Reach out on X: [@aecii_3d](https://x.com/aecii_3d)
