"""Bitmap index for categorical filters (risk level, damage type, status).

Every document gets a position. For each value of a field, one integer is used
as a bitset: bit i is 1 when document i has that value. Filters become bitwise
operations on whole sets at once:

* several values of one field (risk HIGH or CRITICAL) -> OR of their bitsets;
* several fields (risk and damage)                    -> AND of the results;
* counting matches (facet counts)                     -> popcount (int.bit_count).

Databases use the same idea for columns with few distinct values. Python
integers have arbitrary size, so no fixed width is needed.
"""
from collections.abc import Iterable, Iterator


class BitmapIndex:
    def __init__(self):
        self.ids: list[str] = []
        self.positions: dict[str, int] = {}
        self.bitmaps: dict[str, dict[str, int]] = {}

    def __len__(self) -> int:
        return len(self.ids)

    @property
    def all(self) -> int:
        """Bitset with every document."""
        return (1 << len(self.ids)) - 1

    def add(self, document: str, values: dict[str, str | None]) -> None:
        if document in self.positions:
            raise KeyError('Document already indexed')
        position = len(self.ids)
        self.ids.append(document)
        self.positions[document] = position
        for field, value in values.items():
            if value is not None:
                field_maps = self.bitmaps.setdefault(field, {})
                field_maps[value] = field_maps.get(value, 0) | (1 << position)

    def any_of(self, field: str, values: Iterable[str] | None) -> int:
        """Documents whose ``field`` is any of ``values``; every document when no value is given."""
        values = list(values or [])
        if not values:
            return self.all
        result = 0
        for value in values:
            result |= self.bitmaps.get(field, {}).get(value, 0)
        return result

    def of(self, documents: Iterable[str]) -> int:
        """Bitset of a set of document ids (unknown ids are ignored)."""
        result = 0
        for document in documents:
            position = self.positions.get(document)
            if position is not None:
                result |= 1 << position
        return result

    def documents(self, bits: int) -> Iterator[str]:
        """Ids of the set bits, lowest position first: isolate the lowest bit and clear it."""
        while bits:
            lowest = bits & -bits
            yield self.ids[lowest.bit_length() - 1]
            bits ^= lowest

    @staticmethod
    def count(bits: int) -> int:
        return bits.bit_count()

    def counts(self, field: str, within: int) -> dict[str, int]:
        """Facet counts: how many documents of ``within`` have each value of ``field`` (zeros omitted)."""
        counts = {value: (bits & within).bit_count() for value, bits in sorted(self.bitmaps.get(field, {}).items())}
        return {value: count for value, count in counts.items() if count}
