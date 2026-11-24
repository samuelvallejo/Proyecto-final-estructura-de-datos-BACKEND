"""Geographic helpers shared by the repository, the graph and the pass tracker."""
import math


class GeoMath:
    EARTH_DIAMETER_M = 12_742_000
    METERS_PER_DEGREE_LAT = 110_000

    @staticmethod
    def distance(a: dict, b: dict) -> float:
        """Haversine great-circle distance in meters between two ``{'lat', 'lng'}`` points."""
        lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
        delta = math.radians(b['lng'] - a['lng'])
        h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta / 2) ** 2
        return GeoMath.EARTH_DIAMETER_M * math.asin(min(1, math.sqrt(h)))

    @staticmethod
    def latitude_span(radius_m: float) -> float:
        """Degrees of latitude covering ``radius_m`` meters (for indexed pre-filters)."""
        return radius_m / GeoMath.METERS_PER_DEGREE_LAT

    @staticmethod
    def longitude_span(radius_m: float, latitude: float) -> float:
        """Degrees of longitude covering ``radius_m`` meters at ``latitude``."""
        return radius_m / (111_320 * max(.01, math.cos(math.radians(latitude))))
