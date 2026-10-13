"""Conversão opcional e explícita das coordenadas do memorial para a planta."""
from dataclasses import dataclass, replace

from .core import Point


@dataclass
class GeoReference:
    source_crs: str = ''
    target_crs: str = ''

    def transformer(self):
        from pyproj import CRS, Transformer, network
        network.set_network_enabled(False)
        if not self.source_crs or not self.target_crs:
            raise ValueError('Informe o sistema do memorial e da planta para comparar latitude/longitude com E/N.')
        source, target = CRS.from_user_input(self.source_crs), CRS.from_user_input(self.target_crs)
        if not source.is_geographic or not target.is_projected or len(source.axis_info) != 2 or len(target.axis_info) != 2:
            raise ValueError('Use um sistema geográfico 2D para o memorial e um sistema projetado 2D para a planta.')
        if any(abs(a.unit_conversion_factor-1) > 1e-12 for a in target.axis_info):
            raise ValueError('O sistema da planta precisa usar metros.')
        transform = Transformer.from_crs(source, target, always_xy=True, allow_ballpark=False, only_best=True)
        return transform

    def project(self, points: list[Point]):
        transform = self.transformer()
        result = []
        for p in points:
            if p.latitude is None or p.longitude is None:
                result.append(replace(p))
                continue
            x,y = transform.transform(p.longitude,p.latitude,errcheck=True)
            result.append(replace(p,x=x,y=y))
        return result, transform.accuracy


def utm_reference(datum: str, zone: str, hemisphere: str) -> str:
    from pyproj import CRS
    from pyproj.database import query_utm_crs_info
    names = {'SIRGAS 2000':'SIRGAS 2000','SAD69':'South American Datum 1969','WGS 84':'World Geodetic System 1984'}
    if datum not in names or not zone.isdigit() or not 1 <= int(zone) <= 60 or hemisphere not in ('Sul','Norte'):
        raise ValueError('Escolha o datum, o fuso (1 a 60) e o hemisfério da planta.')
    suffix = f' / UTM zone {int(zone)}{"S" if hemisphere == "Sul" else "N"}'
    for item in query_utm_crs_info():
        if item.name == datum + suffix or datum == 'SAD69' and item.name == 'SAD69' + suffix:
            return f'EPSG:{item.code}'
    raise ValueError('Essa combinação de datum/fuso não está disponível. Confira a informação na planta.')
