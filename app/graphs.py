"""Grafo simple no dirigido con listas de adyacencia y pesos no negativos.

Referencias y adaptación a BacheScan: docs/GRAFOS.md.
"""
from heapq import heappop, heappush
from math import isfinite
from .structures import Queue, Stack


class WeightedGraph:
    def __init__(self):
        self.adjacency: dict[str, dict[str, float]] = {}

    def add_vertex(self, vertex: str):
        if not isinstance(vertex, str) or not vertex:
            raise ValueError('Identificador de vértice inválido')
        self.adjacency.setdefault(vertex, {})

    def add_edge(self, source: str, target: str, weight: float):
        if source not in self.adjacency or target not in self.adjacency or source == target:
            raise ValueError('Los extremos deben existir y ser diferentes')
        if isinstance(weight, bool) or not isinstance(weight, (float, int)) or not isfinite(weight) or weight < 0:
            raise ValueError('El peso debe ser finito y no negativo')
        self.adjacency[source][target] = float(weight)
        self.adjacency[target][source] = float(weight)

    def remove_vertex(self, vertex: str):
        for neighbor in self.adjacency.pop(vertex, {}):
            del self.adjacency[neighbor][vertex]

    def remove_edge(self, source: str, target: str):
        self.adjacency.get(source, {}).pop(target, None)
        self.adjacency.get(target, {}).pop(source, None)

    def _require(self, vertex: str):
        if vertex not in self.adjacency:
            raise ValueError('Vértice desconocido')

    def traverse(self, start: str, order: str = 'bfs') -> list[str]:
        self._require(start)
        if order not in ('bfs', 'dfs'):
            raise ValueError('Recorrido desconocido')
        pending = Queue[str]() if order == 'bfs' else Stack[str]()
        put = pending.enqueue if order == 'bfs' else pending.push
        take = pending.dequeue if order == 'bfs' else pending.pop
        put(start)
        discovered, visited, result = {start}, set(), []
        while pending.size:
            vertex = take()
            if vertex in visited:
                continue
            visited.add(vertex)
            result.append(vertex)
            neighbors = sorted(self.adjacency[vertex], reverse=order == 'dfs')
            for neighbor in neighbors:
                if order == 'bfs':
                    if neighbor not in discovered:
                        discovered.add(neighbor)
                        put(neighbor)
                elif neighbor not in visited:
                    put(neighbor)
        return result

    def components(self) -> list[list[str]]:
        remaining, result = set(self.adjacency), []
        for vertex in sorted(self.adjacency):
            if vertex in remaining:
                group = self.traverse(vertex)
                result.append(group)
                remaining.difference_update(group)
        return result

    def shortest_path(self, start: str, end: str) -> dict:
        """Dijkstra; heap mínimo, distancias acumuladas y padres del camino."""
        self._require(start)
        self._require(end)
        distances, parents, heap = {start: 0.0}, {}, [(0.0, start)]
        settled = []
        while heap:
            cost, vertex = heappop(heap)
            if cost != distances[vertex]:
                continue
            settled.append(vertex)
            if vertex == end:
                path = [end]
                while path[-1] != start:
                    path.append(parents[path[-1]])
                return {'reachable': True, 'reportIds': path[::-1], 'distanceMeters': cost,
                        'settledIds': settled}
            for neighbor, weight in sorted(self.adjacency[vertex].items()):
                candidate = cost + weight
                if candidate < distances.get(neighbor, float('inf')):
                    distances[neighbor] = candidate
                    parents[neighbor] = vertex
                    heappush(heap, (candidate, neighbor))
        return {'reachable': False, 'reportIds': [], 'distanceMeters': None, 'settledIds': settled}

    def edges(self) -> list[dict]:
        return [{'source': source, 'target': target, 'distanceMeters': weight}
                for source in sorted(self.adjacency)
                for target, weight in sorted(self.adjacency[source].items()) if source < target]
