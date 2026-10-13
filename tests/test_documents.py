import math
import unittest
from dataclasses import replace

from pontos_autocad.core import Point, make_script, parse_memorial, parse_table_text
from pontos_autocad.conference import contour_issues, order_by_destinations, verify_documents, code_suggestions
from pontos_autocad.georef import GeoReference, utm_reference
from pontos_autocad.memorial import geographic
from pontos_autocad.table_ocr import normalize_cell


def square():
    return [Point('P-1',500000,7500000,'P-2',10,90),Point('P-2',500010,7500000,'P-3',10,0),
            Point('P-3',500010,7500010,'P-4',10,270),Point('P-4',500000,7500010,'P-1',10,180)]


class DocumentReading(unittest.TestCase):
    def test_csv_headers_map_n_before_e_and_empty_cell_stays_empty(self):
        rows=parse_table_text('Ponto;N;E\nP-1;7500000,00;500000,00\nP-2;7500001,00;').points
        self.assertEqual((rows[0].x,rows[0].y),(500000,7500000))
        self.assertIsNone(rows[1].x)
        self.assertEqual(rows[1].y,7500001)

    def test_missing_cell_in_unstructured_table_is_not_shifted_to_altitude(self):
        p=parse_table_text("P-1  7.539.158,48  903,259  P-2  122°39'  9,56").points[0]
        self.assertIsNone(p.x)
        self.assertIsNone(p.y)
        self.assertTrue(p.notes)

    def test_ocr_separator_normalization_never_changes_digits(self):
        self.assertEqual(normalize_cell('x','456,123,45'),'456123,45')
        self.assertEqual(normalize_cell('y','7.539.605.65'),'7539605,65')
        self.assertEqual(normalize_cell('x','123.456'),'123.456')
        self.assertEqual(normalize_cell('x','45O.123,45'),'45O.123,45')
        self.assertEqual(normalize_cell('code','FS0·P·0259'),'FS0-P-0259')

    def test_geographic_hemisphere_and_bounds(self):
        self.assertAlmostEqual(geographic('45°25\'47,648" W'),-45.42990222222222)
        self.assertAlmostEqual(geographic('22°14\'54,554" S',True),-22.24848722222222)
        for text,lat in [('22°60\'00" S',True),('91°00\'00" S',True),('45°20\'00" N',False)]:
            with self.assertRaises(ValueError): geographic(text,lat)

    def test_memorial_pages_continue_code_and_coordinates_and_close_once(self):
        text='''Área: 1,2345 ha. Perímetro: 420,50 m.
        Inicia no vértice FSO-P-01, de coordenadas Lon: 45°00'00,000" W, Lat: 22°00'00,000" S;
        seguintes azimutes e distâncias: 90°00' e de 10,00 m até o vértice FSO-

        P-02, de coordenadas

        Lon: 45°00'01,000" W, Lat: 22°00'01,000" S; 270°00' e de 10,00m até o vértice FSO-P-01,
        Lon: 45°00'00,000" W, Lat: 22°00'00,000" S, ponto inicial.'''
        result=parse_memorial(text)
        self.assertEqual(len(result.points),2)
        self.assertEqual(result.area_m2,12345)
        self.assertEqual(result.perimeter_m,420.5)
        self.assertEqual(result.points[0].destination,'FSO-P-02')
        self.assertEqual(result.points[1].destination,'FSO-P-01')
        self.assertTrue(all(p.longitude is not None and p.latitude is not None and p.distance==10 for p in result.points))

    def test_closing_coordinate_mismatch_is_reported(self):
        result=parse_memorial('vértice P-1, E 1,0 N 2,0; 90°00\' e de 2,0m até o vértice P-2, E 3,0 N 2,0; 270°00\' e de 2,0m até o vértice P-1, E 9,0 N 2,0')
        self.assertEqual(len(result.points),2)
        self.assertTrue(any('fechamento' in note for note in result.warnings))

    def test_partial_memorial_keeps_vertices_and_missing_fields(self):
        result=parse_memorial('vértice P-1, E 1,0 N 2,0; segue até o vértice P-2, E 3,0 N 4,0.')
        self.assertEqual(len(result.points),2)
        self.assertIsNone(result.points[0].distance)
        self.assertTrue(result.points[0].notes)


class DocumentConference(unittest.TestCase):
    def test_similar_code_is_suggested_without_changing_the_document(self):
        table=[Point('FSO-P-01',1,2)]
        mem=[Point('FS0-P-01',None,None)]
        self.assertEqual(code_suggestions(table,mem),{'FS0-P-01':'FSO-P-01'})
        self.assertEqual(mem[0].code,'FS0-P-01')
        mem.append(Point('FSOP-01',None,None))
        self.assertEqual(code_suggestions(table,mem),{})

    def test_confusable_destination_is_pending_instead_of_topology_verdict(self):
        table=[Point('P-1',1,2,'FSO-P-01')]
        mem=[Point('P-1',1,2,'FS0-P-01')]
        checks=verify_documents(table,mem)
        self.assertEqual(next(c.status for c in checks if c.field=='Próximo vértice'),'PENDENTE')

    def test_totals_and_direct_measurements_for_equal_documents(self):
        checks=verify_documents(square(),square(),area_m2=100,perimeter_m=40,measurement_mode='Grade da planta')
        self.assertTrue(all(c.status=='CONFERE' for c in checks))

    def test_direct_difference_cannot_hide_inside_two_individual_tolerances(self):
        table,mem=square(),square()
        table[0].distance=10.049
        mem[0].distance=9.951
        checks=verify_documents(table,mem,dist_tol=.05,measurement_mode='Grade da planta')
        direct=[c for c in checks if c.origin=='Memorial × planta' and c.item.startswith('P-1 →') and c.field=='Distância (m)']
        self.assertEqual(direct[0].status,'DIVERGE')

    def test_different_destinations_are_reported_even_with_correct_lengths(self):
        mem=square()
        mem[0]=replace(mem[0],destination='P-3',distance=math.sqrt(200),bearing=45)
        checks=verify_documents(square(),mem,measurement_mode='Grade da planta')
        self.assertTrue(any(c.item=='P-1' and c.field=='Próximo vértice' and c.status=='DIVERGE' for c in checks))

    def test_unknown_measurement_type_does_not_assert_geodetic_equals_grid(self):
        checks=verify_documents(square(),square(),area_m2=100,perimeter_m=40)
        self.assertTrue(all(c.status=='PENDENTE' for c in checks if c.origin=='Memorial × planta' and c.field in ('Distância (m)','Azimute (min)')))
        self.assertTrue(all(c.status=='CONFERE' for c in checks if c.item=='Total'))

    def test_wrong_total_and_missing_total_are_distinct(self):
        checks=verify_documents(square(),[],area_m2=150,perimeter_m=None)
        self.assertEqual([c.status for c in checks if c.item=='Total'],['DIVERGE','PENDENTE'])

    def test_incomplete_coordinates_never_get_partial_total(self):
        table=square()
        table[2].x=None
        checks=verify_documents(table,[],area_m2=100,perimeter_m=40)
        self.assertTrue(all(c.status=='PENDENTE' and not c.calculated for c in checks if c.item=='Total'))

    def test_duplicates_in_memorial_are_pending(self):
        checks=verify_documents(square(),square()+[square()[0]])
        self.assertTrue(any(c.origin=='Memorial' and c.field=='Identificação' and c.status=='PENDENTE' for c in checks))

    def test_export_rejects_crossed_order_and_suggests_full_cycle(self):
        table=square()
        bad=[table[0],table[2],table[1],table[3]]
        self.assertTrue(contour_issues(bad))
        with self.assertRaises(ValueError): make_script(bad,True)
        ordered=order_by_destinations(bad)
        self.assertEqual([p.code for p in ordered],[p.code for p in table])
        self.assertIn('_Close',make_script(ordered,True))

    def test_order_suggestion_rejects_multiple_cycles(self):
        points=square()
        points[1].destination='P-1'
        with self.assertRaises(ValueError): order_by_destinations(points)


class ReferenceConversion(unittest.TestCase):
    def test_unknown_reference_is_pending_without_guessing(self):
        mem=[Point('P-1',None,None,longitude=-45,latitude=-22)]
        checks=verify_documents(square(),mem)
        self.assertTrue(any(c.field=='Conversão' and c.status=='PENDENTE' for c in checks))
        self.assertIsNone(mem[0].x)

    def test_utm_central_meridian_and_preserve_original(self):
        geo=GeoReference('EPSG:4674','EPSG:31983')
        original=Point('P-1',None,None,longitude=-45,latitude=0)
        projected,accuracy=geo.project([original])
        self.assertAlmostEqual(projected[0].x,500000,places=6)
        self.assertAlmostEqual(projected[0].y,10000000,places=6)
        self.assertIsNone(original.x)
        self.assertEqual(utm_reference('SIRGAS 2000','23','Sul'),'EPSG:31983')

    def test_target_in_degrees_is_rejected(self):
        with self.assertRaises(ValueError): GeoReference('EPSG:4674','EPSG:4326').transformer()


if __name__=='__main__': unittest.main()
