import math
import tempfile
import unittest
from pathlib import Path

from pontos_autocad.core import Point, azimuth, compare, export_files, make_script, number, parse_cells, parse_memorial, parse_table_text, points_csv, validate


class Numbers(unittest.TestCase):
    def test_locales(self):
        for source, expected in [("456.202,76",456202.76), ("7.539.158,48",7539158.48), ("456202.76",456202.76), ("-12,25",-12.25), ("1,234.56",1234.56), ("1.234.567",1234567)]:
            self.assertEqual(number(source), expected)

    def test_refuse_ambiguous_and_bad_digits(self):
        for source in ["123.456", "123,45,67", "45O.123,45", "nan", "inf", "1e6", "1\n_.LINE", "1.23.456,78", "1,2.345.67"]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                number(source)

    def test_dms(self):
        self.assertAlmostEqual(azimuth("122°39'"),122.65)
        self.assertAlmostEqual(azimuth('12°30\'30"'),12.5083333333)
        self.assertEqual(azimuth("0°00'"),0)
        for text in ["361", "90°60'", "12921"]:
            with self.assertRaises(ValueError):
                azimuth(text)


class Parse(unittest.TestCase):
    def test_photo_row_and_header(self):
        text = "Tabela de Coordenadas - Azimutes - Distâncias\nFSO-P-4092  456.202,76  7.539.158,48  903,259  FSO-P-4093  122°39'  9,56  ARTIFICIAL"
        result = parse_table_text(text)
        self.assertEqual(len(result.points),1)
        p = result.points[0]
        self.assertEqual((p.code,p.x,p.y,p.destination,p.distance),("FSO-P-4092",456202.76,7539158.48,"FSO-P-4093",9.56))
        self.assertAlmostEqual(p.bearing,122.65)

    def test_missing_degree_symbol_is_pending_not_guessed(self):
        p = parse_table_text("FSO-P-4102  456.439,19  7.538.926,16  897,986  FSO-P-4103  12921  28,68  ARTIFICIAL").points[0]
        self.assertIsNone(p.bearing)
        self.assertEqual(p.distance,28.68)
        self.assertTrue(p.notes)
        self.assertIn("12921",p.raw)

    def test_broken_row_survives(self):
        p = parse_cells(["FSO-P-4092","456.2O2,76","7.539.158,48"])
        self.assertIsNone(p.x)
        self.assertTrue(validate([p]))

    def test_ocr_letter_inside_number_is_not_split_into_two_coordinates(self):
        p=parse_table_text("FSO-P-1  456.2O2,76  7.539.158,48  900,0  FSO-P-2  l29°21'  2O,68").points[0]
        self.assertIsNone(p.x)
        self.assertEqual(p.y,7539158.48)
        self.assertIsNone(p.bearing)
        self.assertIsNone(p.distance)

    def test_csv_roundtrip(self):
        points = [Point("P-1",500000.123456,7500000.234567,"P-2",123.456,359.95)]
        parsed = parse_table_text(points_csv(points)).points
        self.assertEqual(len(parsed),1)
        self.assertEqual((parsed[0].x,parsed[0].y,parsed[0].distance,parsed[0].bearing),(points[0].x,points[0].y,points[0].distance,points[0].bearing))

    def test_extensionless_reference_format(self):
        p = parse_table_text("FSO-P-4092,456202.76,7539158.48\n").points[0]
        self.assertEqual(p.x,456202.76)

    def test_example_memorial(self):
        base=Path(__file__).resolve().parents[1]/"exemplos"
        table=parse_table_text((base/"tabela.csv").read_text(encoding="utf8")).points
        memorial=parse_memorial((base/"memorial.txt").read_text(encoding="utf8"))
        self.assertEqual(len(memorial.points),4)
        self.assertEqual(memorial.warnings,[])
        checks=compare(table,memorial.points)
        self.assertEqual(len(checks),20)
        self.assertTrue(all(c.status=="CONFERE" for c in checks))

    def test_no_coordinate_guess_from_conjunction(self):
        p=parse_memorial("vértice P-1, N 7.500.000,00 m, segue 12 m e 100 m, distância de 10,00 m até o vértice P-2").points[0]
        self.assertIsNone(p.x)

    def test_memorial_bad_ocr_digit_not_truncated(self):
        p=parse_memorial("vértice P-1, E 500.0O0,00 m, N 7.500.000,00 m, distância de 2O,68 m até o vértice P-2").points[0]
        self.assertIsNone(p.x)
        self.assertIsNone(p.distance)
        self.assertTrue(p.notes)


class Comparison(unittest.TestCase):
    def test_position_difference(self):
        checks=compare([Point("P-1",1000,2000)],[Point("P-1",1000.03,2000.04)],coord_tol=.02)
        self.assertEqual(checks[0].status,"DIVERGE")
        self.assertEqual(checks[0].difference,"0.0500")

    def test_circular_azimuth(self):
        angle=math.radians(.001)
        a=Point("P-1",1000,2000,"P-2",100,359.999)
        b=Point("P-2",1000+100*math.sin(angle),2000+100*math.cos(angle))
        checks=compare([a,b],[],az_tol_minutes=.13)
        self.assertTrue(all(c.status=="CONFERE" for c in checks))

    def test_duplicates_and_missing_points(self):
        points=[Point("P-1",1,2),Point("P-1",3,4)]
        self.assertTrue(validate(points))
        checks=compare(points,[Point("P-9",3,4)])
        self.assertTrue(all(c.status=="PENDENTE" for c in checks))

    def test_missing_memorial_coordinate_coverage(self):
        checks=compare([Point("P-1",1000,2000),Point("P-2",1001,2001)],[Point("P-1",1000,None)])
        self.assertEqual(sum(c.status=="PENDENTE" for c in checks),2)

    def test_zero_length_has_no_azimuth(self):
        a=Point("P-1",1,2,"P-2",0,0)
        checks=compare([a,Point("P-2",1,2)],[])
        self.assertEqual([c.status for c in checks],["CONFERE","PENDENTE"])

    def test_invalid_tolerance(self):
        for tol in [-1,float("nan"),float("inf")]:
            with self.assertRaises(ValueError):
                compare([],[],coord_tol=tol)


class Scripts(unittest.TestCase):
    def setUp(self):
        self.points=[Point("P-1",456202.76,7539158.48),Point("P-2",456210.81,7539153.32),Point("P-3",456216.14,7539141.22)]

    def test_points_world_zero_and_precision(self):
        scr=make_script(self.points)
        self.assertEqual(scr.count("_.POINT\n_non\n"),3)
        self.assertIn("456202.760000,7539158.480000,0",scr)
        self.assertIn("_.UCS\n_World",scr)
        self.assertTrue(scr.endswith("\n\n"))

    def test_contour_order_and_close(self):
        scr=make_script(self.points,True)
        self.assertLess(scr.index("456202.760000"),scr.index("456210.810000"))
        self.assertIn("_Close\n",scr)
        self.assertIn("ELEVATION\n0",scr)
        self.assertNotIn("_Close",make_script(self.points,True,False))

    def test_no_partial_export_on_invalid_input(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                export_files(Path(folder),[Point("P-1",None,3)])
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_export_line_endings_and_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=export_files(Path(folder),self.points)
            self.assertEqual(len(paths),3)
            raw=(Path(folder)/"pontos_pontos.scr").read_bytes()
            self.assertIn(b"\r\n",raw)
            self.assertNotIn(b"\r\r\n",raw)
            parsed=parse_table_text((Path(folder)/"pontos.csv").read_text(encoding="utf-8-sig"))
            self.assertEqual(len(parsed.points),3)


if __name__ == "__main__":
    unittest.main()
