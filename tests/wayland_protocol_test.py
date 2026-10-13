import unittest

from run_darling_wayland_render import parent_resize_evidence


class WaylandParentResizeTest(unittest.TestCase):
    def test_child_resize_cannot_commit_parent_geometry(self):
        trace = """
 -> xdg_wm_base#1.get_xdg_surface(new id xdg_surface#2, wl_surface#3)
 -> wl_shm_pool#4.create_buffer(new id wl_buffer#5, 0, 320, 240, 1280, 0)
 -> wl_surface#3.attach(wl_buffer#5, 0, 0)
 -> wl_surface#3.commit()
 -> wl_shm_pool#4.create_buffer(new id wl_buffer#6, 0, 1920, 1080, 7680, 1)
 -> wl_surface#7.attach(wl_buffer#6, 0, 0)
 -> wl_surface#7.commit()
RESIZE_EXPECT 1 1920 1080
"""
        self.assertFalse(parent_resize_evidence(trace)[0]["parent_committed"])

    def test_attach_requires_parent_commit(self):
        trace = """
 -> xdg_wm_base@1.get_xdg_surface(new id xdg_surface@2, wl_surface@3)
 -> wl_shm_pool@4.create_buffer(new id wl_buffer@5, 0, 1920, 1080, 7680, 1)
 -> wl_surface@3.attach(wl_buffer@5, 0, 0)
RESIZE_EXPECT 1 1920 1080
 -> wl_surface@3.commit()
RESIZE_EXPECT 1 1920 1080
"""
        self.assertEqual([False, True], [check["parent_committed"]
                                         for check in parent_resize_evidence(trace)])

    def test_resize_and_restore_can_reuse_released_buffer_ids(self):
        trace = """
 -> xdg_wm_base#1.get_xdg_surface(new id xdg_surface#2, wl_surface#3)
 -> wl_shm_pool#4.create_buffer(new id wl_buffer#5, 0, 1920, 1080, 7680, 1)
 -> wl_surface#3.attach(wl_buffer#5, 0, 0)
 -> wl_surface#3.commit()
RESIZE_EXPECT 1 1920 1080
wl_buffer#5.release()
 -> wl_buffer#5.destroy()
 -> wl_shm_pool#4.create_buffer(new id wl_buffer#5, 0, 640, 360, 2560, 1)
 -> wl_surface#3.attach(wl_buffer#5, 0, 0)
 -> wl_surface#3.commit()
RESIZE_EXPECT 0 640 360
"""
        self.assertEqual([True, True], [check["parent_committed"]
                                       for check in parent_resize_evidence(trace)])


if __name__ == "__main__":
    unittest.main()
