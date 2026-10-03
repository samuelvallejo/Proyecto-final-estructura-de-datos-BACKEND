import asyncio
import random
from collections import deque
import pytest
from app.structures import SinglyLinkedList, DoublyLinkedList, CircularSinglyLinkedList, CircularDoublyLinkedList, Stack, Queue, Deque
from app.pipeline import ScanPipeline


@pytest.mark.parametrize('kind', [SinglyLinkedList, DoublyLinkedList])
def test_linked_lists(kind):
    linked = kind()
    with pytest.raises(IndexError):
        linked.popleft()
    for n in range(20):
        linked.append(n)
    assert list(linked) == list(range(20))
    if kind is DoublyLinkedList:
        assert list(linked.reverse()) == list(reversed(range(20)))
        assert linked.pop() == 19
    while linked.size:
        linked.popleft()
    assert linked.head is linked.tail is None
    linked.append(99)
    assert linked.popleft() == 99


@pytest.mark.parametrize('kind', [CircularSinglyLinkedList, CircularDoublyLinkedList])
def test_ring_wrap_and_links(kind):
    ring = kind()
    with pytest.raises(IndexError):
        ring.advance()
    for n in range(3):
        ring.append(n)
    assert list(ring) == [0, 1, 2]
    assert [ring.advance() for _ in range(7)] == [0, 1, 2, 0, 1, 2, 0]
    assert ring.tail.next.value == 0
    if kind is CircularDoublyLinkedList:
        assert ring.retreat() == 0
        assert ring.retreat() == 2
        node = ring.tail
        for _ in range(3):
            assert node.next.prev is node
            assert node.prev.next is node
            node = node.next


def test_stack_and_fifo():
    stack, queue = Stack(), Queue()
    for n in range(100):
        stack.push(n)
        queue.enqueue(n)
    assert [stack.pop() for _ in range(100)] == list(reversed(range(100)))
    assert [queue.dequeue() for _ in range(100)] == list(range(100))
    assert stack.size == queue.size == 0
    with pytest.raises(IndexError):
        stack.pop()
    with pytest.raises(IndexError):
        queue.dequeue()


def test_deque_random_operations_and_node_consistency():
    actual, expected, rng = Deque(), deque(), random.Random(7)
    for _ in range(1000):
        operation = rng.choice(['append', 'appendleft', 'pop', 'popleft'])
        if operation in ('pop', 'popleft') and not expected:
            continue
        if operation.startswith('append'):
            value = rng.randrange(100)
            getattr(actual, operation)(value)
            getattr(expected, operation)(value)
        else:
            assert getattr(actual, operation)() == getattr(expected, operation)()
        assert list(actual.items) == list(expected)
        assert list(actual.items.reverse()) == list(reversed(expected))
        assert actual.size == len(expected)


def test_pipeline_limit_failure_recovery_and_fifo_per_worker():
    async def run():
        pipeline = ScanPipeline(3)
        pipeline.start()
        gate = asyncio.Event()
        finished = []
        async def op(n):
            await gate.wait()
            finished.append(n)
            return n
        tasks = [asyncio.create_task(pipeline.submit(lambda n=n: op(n))) for n in range(3)]
        await asyncio.sleep(.01)
        with pytest.raises(OverflowError):
            await pipeline.submit(lambda: op(4))
        gate.set()
        assert await asyncio.gather(*tasks) == [0, 1, 2]
        assert finished.index(0) < finished.index(2)
        async def failure():
            raise ValueError('expected')
        with pytest.raises(ValueError):
            await pipeline.submit(failure)
        assert await pipeline.submit(lambda: op(5)) == 5
        assert pipeline.pending == 0
        for n in range(120):
            pipeline.remember({'id': n}, n)
        assert pipeline.history.size == pipeline.timeline.size == pipeline.latencies.size == 100
        assert list(pipeline.history.reverse())[0]['id'] == 119
        await pipeline.close()
    asyncio.run(run())
