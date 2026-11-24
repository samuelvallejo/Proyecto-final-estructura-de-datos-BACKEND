"""Spatial hash grid for fixed-radius neighbour queries on latitude/longitude.

The plane is divided into square cells of ``cell_meters`` side. A hash table
maps each cell ``(row, column)`` to the identifiers inside it. A query only
inspects the cells that overlap the circle's bounding box instead of every
point, so finding all close pairs costs O(n + m) expected time (m = candidate
pairs in neighbouring cells) instead of the O(n^2) comparison of every pair.
Candidates are always confirmed with the exact haversine distance.
"""
import math
from typing import Generic, Hashable, Iterator, TypeVar
from .geo import GeoMath

T = TypeVar('T', bound=Hashable)
METERS_PER_DEGREE = 111_320.0
MAX_LATITUDE = 89.0


class SpatialHashGrid(Generic[T]):
    def __init__(self, cell_meters: float):
        if not math.isfinite(cell_meters) or cell_meters <= 0:
            raise ValueError('Cell size must be positive')
        self.cell_meters = float(cell_meters)
        self.lat_step = self.cell_meters / METERS_PER_DEGREE
        self.cells: dict[tuple[int, int], list[T]] = {}
        self.points: dict[T, dict] = {}

    def __len__(self) -> int:
        return len(self.points)

    def _row(self, lat: float) -> int:
        return math.floor(lat / self.lat_step)

    def _lng_step(self, row: int) -> float:
        # Longitude degrees shrink with latitude; use the band edge closest to a pole
        # so a cell is never narrower in meters than ``cell_meters``.
        edge = max(abs(row * self.lat_step), abs((row + 1) * self.lat_step))
        return self.cell_meters / (METERS_PER_DEGREE * math.cos(math.radians(min(edge, MAX_LATITUDE))))

    def _cell(self, lat: float, lng: float) -> tuple[int, int]:
        row = self._row(lat)
        return row, math.floor(lng / self._lng_step(row))

    @staticmethod
    def valid(lat: float, lng: float) -> bool:
        return all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                   for value in (lat, lng)) and abs(lat) <= MAX_LATITUDE and -180 <= lng <= 180

    def insert(self, key: T, lat: float, lng: float) -> bool:
        """Add a point; False when the coordinates cannot be indexed (near a pole or invalid)."""
        if key in self.points:
            raise KeyError('Duplicated point key')
        if not self.valid(lat, lng):
            return False
        self.points[key] = {'lat': float(lat), 'lng': float(lng)}
        self.cells.setdefault(self._cell(lat, lng), []).append(key)
        return True

    def candidates(self, lat: float, lng: float, radius: float) -> Iterator[T]:
        """Keys in the cells that overlap the query circle's bounding box (may include far points)."""
        lat_span = radius / METERS_PER_DEGREE
        for row in range(self._row(lat - lat_span), self._row(lat + lat_span) + 1):
            edge = max(abs(row * self.lat_step), abs((row + 1) * self.lat_step))
            lng_span = radius / (METERS_PER_DEGREE * math.cos(math.radians(min(edge, MAX_LATITUDE))))
            step = self._lng_step(row)
            for column in range(math.floor((lng - lng_span) / step), math.floor((lng + lng_span) / step) + 1):
                yield from self.cells.get((row, column), ())

    def within(self, lat: float, lng: float, radius: float) -> list[tuple[T, float]]:
        """Keys at most ``radius`` meters away, closest first."""
        origin = {'lat': lat, 'lng': lng}
        hits = [(key, GeoMath.distance(origin, self.points[key])) for key in self.candidates(lat, lng, radius)]
        return sorted(((key, meters) for key, meters in hits if meters <= radius), key=lambda hit: (hit[1], str(hit[0])))

    def close_pairs(self, radius: float) -> tuple[list[tuple[T, T, float]], int]:
        """Every unordered pair closer than ``radius`` and the number of candidate checks made."""
        pairs, checks = [], 0
        order = {key: index for index, key in enumerate(self.points)}
        for key, point in self.points.items():
            for other in self.candidates(point['lat'], point['lng'], radius):
                if order[other] <= order[key]:
                    continue
                checks += 1
                meters = GeoMath.distance(point, self.points[other])
                if meters <= radius:
                    pairs.append((key, other, meters))
        return pairs, checks
