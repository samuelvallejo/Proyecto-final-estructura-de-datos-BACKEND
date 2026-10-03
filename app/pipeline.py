"""Colas FIFO por trabajador; asignación round robin mediante lista circular."""
import asyncio
from .structures import Queue, CircularSinglyLinkedList, SinglyLinkedList, DoublyLinkedList, Deque


class ScanPipeline:
    def __init__(self, maximum=8):
        self.maximum = maximum
        self.pending = 0
        self.queues = [Queue(), Queue()]
        self.events = [asyncio.Event(), asyncio.Event()]
        self.workers = CircularSinglyLinkedList[int]()
        for index in range(2):
            self.workers.append(index)
        self.tasks = []
        self.timeline = SinglyLinkedList[dict]()
        self.history = DoublyLinkedList[dict]()
        self.latencies = Deque[int]()

    def start(self):
        self.tasks = [asyncio.create_task(self.run(index)) for index in range(2)]

    async def submit(self, operation):
        if self.pending >= self.maximum:
            raise OverflowError('La cola de análisis está llena. Reintenta en unos segundos.')
        self.pending += 1
        future = asyncio.get_running_loop().create_future()
        index = self.workers.advance()
        self.queues[index].enqueue((future, operation))
        self.events[index].set()
        return await future

    async def run(self, index):
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

    def remember(self, event, duration):
        self.timeline.append(event)
        self.history.append(event)
        self.latencies.append(duration)
        if self.timeline.size > 100:
            self.timeline.popleft()
        if self.history.size > 100:
            self.history.popleft()
        if self.latencies.size > 100:
            self.latencies.popleft()

    def stats(self):
        return {
            'singlyLinkedList': {'size': self.timeline.size, 'use': 'Eventos de escaneo en orden de llegada'},
            'doublyLinkedList': {'size': self.history.size, 'use': 'Historial de resultados en ambos sentidos'},
            'circularSinglyLinkedList': {'size': self.workers.size, 'use': 'Asignación round robin de trabajadores'},
            'queue': {'size': sum(q.size for q in self.queues), 'runningAndQueued': self.pending, 'use': 'Trabajos de análisis FIFO por trabajador'},
            'deque': {'size': self.latencies.size, 'use': 'Ventana de latencias de los últimos 100 análisis'},
        }

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
