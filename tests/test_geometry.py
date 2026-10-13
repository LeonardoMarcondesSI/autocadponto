import math
import unittest

from pontos_autocad.core import Point
from pontos_autocad.geometry import contour_measures


def points(xy):
    return [Point(f"P-{i}", x, y) for i, (x, y) in enumerate(xy)]


class Measures(unittest.TestCase):
    def test_rectangle_in_large_coordinates_and_reverse_order(self):
        rectangle = points([(456000, 7539000), (456100, 7539000), (456100, 7539200), (456000, 7539200)])
        for rows in (rectangle, rectangle[::-1], rectangle + [rectangle[0]]):
            result = contour_measures(rows)
            self.assertEqual(result.area_m2, 20000)
            self.assertEqual(result.perimeter_m, 600)

    def test_small_area_with_utm_offset(self):
        result = contour_measures(points([(456000, 7539000), (456000.01, 7539000), (456000.01, 7539000.01), (456000, 7539000.01)]))
        self.assertAlmostEqual(result.area_m2, .0001, places=10)
        self.assertAlmostEqual(result.perimeter_m, .04, places=8)

    def test_concave_polygon_and_collinear_edge_vertices(self):
        result = contour_measures(points([(0, 0), (2, 0), (4, 0), (4, 4), (2, 2), (0, 4)]))
        self.assertEqual(result.area_m2, 12)
        self.assertAlmostEqual(result.perimeter_m, 12 + 2 * math.sqrt(8))

    def test_open_line_has_length_without_area_or_perimeter(self):
        result = contour_measures(points([(0, 0), (3, 0), (3, 4)]), close=False)
        self.assertEqual(result.length_m, 7)
        self.assertIsNone(result.area_m2)
        self.assertIsNone(result.perimeter_m)

    def test_no_partial_totals_when_coordinate_is_missing_or_invalid(self):
        for bad in (None, math.inf, math.nan):
            result = contour_measures(points([(0, 0), (bad, 0), (3, 4), (0, 4)]))
            self.assertIsNone(result.area_m2)
            self.assertIsNone(result.perimeter_m)
            self.assertIsNone(result.length_m)

    def test_crossed_polygon_has_no_area_even_with_nonzero_signed_area(self):
        result = contour_measures(points([(0, 0), (6, 4), (0, 4), (4, 0)]))
        self.assertIsNone(result.area_m2)
        self.assertIsNone(result.perimeter_m)
        self.assertIn("cruzado", result.note)

    def test_degenerate_overlapping_and_repeated_points(self):
        for xy in ([], [(0, 0)], [(0, 0), (1, 0)], [(0, 0), (1, 0), (2, 0)],
                   [(0, 0), (4, 0), (2, 0), (2, 2), (0, 2)],
                   [(0, 0), (4, 0), (4, 4), (4, 0), (0, 4)],
                   [(0, 0), (4, 0), (4, 4), (2, 0), (0, 4)]):
            with self.subTest(xy=xy):
                result = contour_measures(points(xy))
                self.assertIsNone(result.area_m2)
                self.assertIsNone(result.perimeter_m)


if __name__ == "__main__":
    unittest.main()
