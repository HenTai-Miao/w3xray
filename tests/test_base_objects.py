"""基础对象补全：无名的原版对象(系统内部、游戏没给显示名)不应塞进列表当噪声。"""
import unittest

from w3xtool.api import MapData, _add_base_objects
from w3xtool.base_objects import BASE_OBJECTS
from w3xtool.base_names import BASE_NAMES


class TestAddBaseObjects(unittest.TestCase):
    def test_nameless_base_objects_excluded(self):
        nameless = [c for c in BASE_OBJECTS if c not in BASE_NAMES]
        self.assertTrue(nameless, "前提：BASE_OBJECTS 里确有无名码")
        md = MapData(path="x", name="x")
        _add_base_objects(md)
        for c in nameless:
            self.assertNotIn(c, md.obj_index, f"无名基础对象 {c} 不应被加入")

    def test_named_base_objects_still_added(self):
        named = next(c for c in BASE_OBJECTS if c in BASE_NAMES)
        md = MapData(path="x", name="x")
        _add_base_objects(md)
        self.assertIn(named, md.obj_index)
        self.assertEqual(md.obj_index[named].name, BASE_NAMES[named])

    def test_repeated_base_addition_does_not_duplicate_rawcodes(self):
        # Given: base objects have already been added once.
        md = MapData(path="x", name="x")
        _add_base_objects(md)

        # When: the compatibility wrapper is called again.
        _add_base_objects(md)

        # Then: buckets and index still contain one object per rawcode.
        codes = [obj.obj_id for objects in md.objects.values() for obj in objects]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(set(codes), set(md.obj_index))


if __name__ == "__main__":
    unittest.main()
