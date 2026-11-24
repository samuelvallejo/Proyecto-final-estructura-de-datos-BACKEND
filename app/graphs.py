"""Simple undirected graph with non-negative weights, stored as real adjacency lists.

Each vertex maps (through a hand-written HashMap) to an AdjacencyList: a singly linked list of
edges. BFS uses the hand-written Queue, DFS the Stack and Dijkstra the MinHeap.
References and how it applies to BacheScan: docs/GRAFOS.md.
"""
from __future__ import annotations

from math import isfinite
from typing import Iterator

from .structures import HashMap, HashSet, MinHeap, Queue, SinglyLinkedList, Sorter, Stack


class Edge:
    __slots__ = ('target', 'weight')

    def __init__(self, target: str, weight: float):
        self.target = target
        self.weight = weight


class AdjacencyList:
    """Neighbors of one vertex as a linked list of edges; ``len`` is the vertex degree."""

    def __init__(self):
        self._edges = SinglyLinkedList[Edge]()

    def set(self, target: str, weight: float) -> None:
        edge = self._edges.find(lambda item: item.target == target)
        if edge is None:
            self._edges.append(Edge(target, weight))
        else:
            edge.weight = weight

    def remove(self, target: str) -> None:
        self._edges.remove_first(lambda item: item.target == target)

    def sorted_edges(self, reverse: bool = False) -> SinglyLinkedList[Edge]:
        """Edges ordered by neighbor id, so traversals are deterministic."""
        return Sorter.merge_sort(self._edges, key=lambda edge: edge.target, reverse=reverse)

    def __getitem__(self, target: str) -> float:
        edge = self._edges.find(lambda item: item.target == target)
        if edge is None:
            raise KeyError(target)
        return edge.weight

    def __contains__(self, target: str) -> bool:
        return self._edges.find(lambda item: item.target == target) is not None

    def __len__(self) -> int:
        return self._edges.size

    def __iter__(self) -> Iterator[str]:
        return (edge.target for edge in self._edges)


class WeightedGraph:
    def __init__(self):
        self.adjacency = HashMap[str, AdjacencyList]()

    def add_vertex(self, vertex: str) -> None:
        if not isinstance(vertex, str) or not vertex:
            raise ValueError('Invalid vertex id')
        if vertex not in self.adjacency:
            self.adjacency[vertex] = AdjacencyList()

    def add_edge(self, source: str, target: str, weight: float) -> None:
        if source not in self.adjacency or target not in self.adjacency or source == target:
            raise ValueError('Both endpoints must exist and be different')
        if isinstance(weight, bool) or not isinstance(weight, (float, int)) or not isfinite(weight) or weight < 0:
            raise ValueError('The weight must be finite and non-negative')
        self.adjacency[source].set(target, float(weight))
        self.adjacency[target].set(source, float(weight))

    def remove_vertex(self, vertex: str) -> None:
        neighbors = self.adjacency.remove(vertex)
        if neighbors is not None:
            for neighbor in neighbors:
                self.adjacency[neighbor].remove(vertex)

    def remove_edge(self, source: str, target: str) -> None:
        if source in self.adjacency:
            self.adjacency[source].remove(target)
        if target in self.adjacency:
            self.adjacency[target].remove(source)

    def vertices(self) -> SinglyLinkedList[str]:
        """Vertex ids in ascending order."""
        return Sorter.merge_sort(self.adjacency.keys())

    def degree(self, vertex: str) -> int:
        self._require(vertex)
        return len(self.adjacency[vertex])

    def as_dict(self) -> dict:
        """Plain snapshot ``{vertex: {neighbor: weight}}`` for JSON responses and tests."""
        return {vertex: {edge.target: edge.weight for edge in self.adjacency[vertex].sorted_edges()}
                for vertex in self.vertices()}

    def _require(self, vertex: str) -> None:
        if vertex not in self.adjacency:
            raise ValueError('Unknown vertex')

    def traverse(self, start: str, order: str = 'bfs') -> list[str]:
        """Breadth-first (queue) or depth-first (stack) visit order from ``start``."""
        self._require(start)
        if order not in ('bfs', 'dfs'):
            raise ValueError('Unknown traversal')
        breadth = order == 'bfs'
        pending = Queue[str]() if breadth else Stack[str]()
        put = pending.enqueue if breadth else pending.push
        take = pending.dequeue if breadth else pending.pop
        put(start)
        discovered, visited, result = HashSet([start]), HashSet[str](), SinglyLinkedList[str]()
        while not pending.is_empty():
            vertex = take()
            if vertex in visited:
                continue
            visited.add(vertex)
            result.append(vertex)
            # A stack pops in reverse, so DFS pushes neighbors in descending order.
            for edge in self.adjacency[vertex].sorted_edges(reverse=not breadth):
                if breadth:
                    if edge.target not in discovered:
                        discovered.add(edge.target)
                        put(edge.target)
                elif edge.target not in visited:
                    put(edge.target)
        return list(result)

    def components(self) -> list[list[str]]:
        """Connected components, each listed in BFS order from its smallest vertex."""
        remaining, groups = HashSet(self.adjacency.keys()), SinglyLinkedList[list]()
        for vertex in self.vertices():
            if vertex in remaining:
                group = self.traverse(vertex)
                groups.append(group)
                for member in group:
                    remaining.remove(member)
        return list(groups)

    def shortest_path(self, start: str, end: str) -> dict:
        """Dijkstra with a min-heap: accumulated distances and parent links of the best path."""
        self._require(start)
        self._require(end)
        distances, parents = HashMap[str, float]([(start, 0.0)]), HashMap[str, str]()
        heap = MinHeap[str]()
        heap.push((0.0, start), start)
        settled = SinglyLinkedList[str]()
        while heap.size:
            (cost, _), vertex = heap.pop()
            if cost != distances[vertex]:
                continue  # Stale entry: a shorter distance was already found.
            settled.append(vertex)
            if vertex == end:
                path = Stack[str]()
                path.push(end)
                while path.peek() != start:
                    path.push(parents[path.peek()])
                return {'reachable': True, 'reportIds': list(path), 'distanceMeters': cost,
                        'settledIds': list(settled)}
            for edge in self.adjacency[vertex].sorted_edges():
                candidate = cost + edge.weight
                if candidate < distances.get(edge.target, float('inf')):
                    distances[edge.target] = candidate
                    parents[edge.target] = vertex
                    heap.push((candidate, edge.target), edge.target)
        return {'reachable': False, 'reportIds': [], 'distanceMeters': None, 'settledIds': list(settled)}

    def edges(self) -> list[dict]:
        """Each undirected edge once, ordered by source then target id."""
        result = SinglyLinkedList[dict]()
        for source in self.vertices():
            for edge in self.adjacency[source].sorted_edges():
                if source < edge.target:
                    result.append({'source': source, 'target': edge.target, 'distanceMeters': edge.weight})
        return list(result)
