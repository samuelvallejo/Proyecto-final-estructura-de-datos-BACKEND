"""Scan pipeline: one FIFO queue per worker and round-robin assignment through a circular list."""
import asyncio

from .structures import (CircularSinglyLinkedList, Deque, DoublyLinkedList, DynamicArray, Queue,
                         SinglyLinkedList, Sorter)


class LatencyWindow:
    """Sliding window of the last ``capacity`` latencies (ms) kept in a deque."""

    def __init__(self, capacity: int = 100):
        self.capacity = capacity
        self.values = Deque[int]()

    def add(self, milliseconds: int) -> None:
        self.values.append(milliseconds)
        if self.values.size > self.capacity:
            self.values.popleft()

    @property
    def size(self) -> int:
        return self.values.size

    def summary(self) -> dict:
        """Median (p50) and 95th percentile computed over a sorted copy of the window."""
        ordered = DynamicArray(Sorter.merge_sort(self.values))
        if not ordered.size:
            return {'samples': 0, 'p50': None, 'p95': None}
        count = ordered.size
        return {'samples': count, 'p50': ordered[(count - 1) // 2],
                'p95': ordered[max(0, (95 * count + 99) // 100 - 1)]}


class ScanPipeline:
    WORKERS = 2
    HISTORY_LIMIT = 100

    def __init__(self, maximum: int = 8):
        self.maximum = maximum
        self.pending = 0
        self.queues = DynamicArray(Queue() for _ in range(self.WORKERS))
        self.events = DynamicArray(asyncio.Event() for _ in range(self.WORKERS))
        self.workers = CircularSinglyLinkedList[int]()
        for index in range(self.WORKERS):
            self.workers.append(index)
        self.tasks = DynamicArray[asyncio.Task]()
        self.timeline = SinglyLinkedList[dict]()
        self.history = DoublyLinkedList[dict]()
        self.latency_window = LatencyWindow(self.HISTORY_LIMIT)

    @property
    def latencies(self) -> Deque[int]:
        return self.latency_window.values

    def start(self) -> None:
        for index in range(self.WORKERS):
            self.tasks.append(asyncio.create_task(self.run(index)))

    async def submit(self, operation):
        """Queue ``operation`` on the next worker (round robin) and wait for its result."""
        if self.pending >= self.maximum:
            raise OverflowError('La cola de análisis está llena. Reintenta en unos segundos.')
        self.pending += 1
        future = asyncio.get_running_loop().create_future()
        index = self.workers.advance()
        self.queues[index].enqueue((future, operation))
        self.events[index].set()
        return await future

    async def run(self, index: int) -> None:
        while True:
            await self.events[index].wait()
            while self.queues[index].size:
                future, operation = self.queues[index].dequeue()
                try:
                    if not future.cancelled():
                        result = await operation()
                        if not future.done():
                            future.set_result(result)
                except Exception as exc:
                    if not future.done():
                        future.set_exception(exc)
                finally:
                    self.pending -= 1
            self.events[index].clear()

    def remember(self, event: dict, duration: int) -> None:
        self.timeline.append(event)
        self.history.append(event)
        self.latency_window.add(duration)
        if self.timeline.size > self.HISTORY_LIMIT:
            self.timeline.popleft()
        if self.history.size > self.HISTORY_LIMIT:
            self.history.popleft()

    def stats(self) -> dict:
        return {
            'singlyLinkedList': {'size': self.timeline.size, 'use': 'Eventos de escaneo en orden de llegada'},
            'doublyLinkedList': {'size': self.history.size, 'use': 'Historial de resultados en ambos sentidos'},
            'circularSinglyLinkedList': {'size': self.workers.size, 'use': 'Asignación round robin de trabajadores'},
            'queue': {'size': sum(queue.size for queue in self.queues), 'runningAndQueued': self.pending,
                      'use': 'Trabajos de análisis FIFO por trabajador'},
            'deque': {'size': self.latency_window.size, 'use': 'Ventana de latencias de los últimos 100 análisis'},
            'totalLatencyMs': self.latency_window.summary(),
        }

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
