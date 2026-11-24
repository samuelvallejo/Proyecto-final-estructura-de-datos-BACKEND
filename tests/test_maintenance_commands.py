"""Command, Chain of Responsibility and Template Method of maintenance writes (no database)."""
import pytest
from fastapi import HTTPException
from app.maintenance_commands import (ChangeStatusCommand, MergeDuplicatesCommand, ReportsExistRule, ValidationContext,
                                      ValidationRule, chain)


def row(identity, status='UNVERIFIED', lat=1.2, lng=-77.29, pothole=None):
    return {'id': identity, 'pothole_id': pothole or 'p-' + identity, 'status': status, 'lat': lat, 'lng': lng}


class FakeRepository:
    """Stands in for MaintenanceRepository and records what the command asks for."""

    def __init__(self):
        self.calls = []

    def change_status(self, pothole, status, actor_id, reason):
        self.calls.append(('status', pothole['pothole_id'], status, reason))

    def move_passes(self, from_pothole, to_pothole):
        self.calls.append(('passes', from_pothole, to_pothole))
        return 2


def validate(command, rows):
    command.rules().handle(ValidationContext(command, rows))


def error_of(command, rows):
    with pytest.raises(HTTPException) as caught:
        validate(command, rows)
    return caught.value.status_code, caught.value.detail


class Recorder(ValidationRule):
    def __init__(self, name, log, fails=False):
        super().__init__()
        self.name, self.log, self.fails, self.message = name, log, fails, name

    def violated(self, context):
        self.log.append(self.name)
        return self.fails


def test_chain_stops_at_the_first_violated_rule():
    log = []
    first = chain(Recorder('a', log), Recorder('b', log, fails=True), Recorder('c', log))
    with pytest.raises(HTTPException) as caught:
        first.handle(ValidationContext(None, {}))
    assert log == ['a', 'b'] and caught.value.detail == 'b' and caught.value.status_code == 409
    log.clear()
    chain(Recorder('a', log), Recorder('c', log)).handle(ValidationContext(None, {}))
    assert log == ['a', 'c']


def test_change_status_rules_and_application():
    command = ChangeStatusCommand('r1', 'CONFIRMED', '  ')
    assert error_of(command, {}) == (404, 'El reporte no existe.')
    assert error_of(ChangeStatusCommand('r1', 'REPAIRED'), {'r1': row('r1')})[0] == 409
    validate(command, {'r1': row('r1')})
    repo = FakeRepository()
    assert command.apply(repo, {'r1': row('r1')}, 'u1') == {'from': 'UNVERIFIED', 'to': 'CONFIRMED'}
    assert repo.calls == [('status', 'p-r1', 'CONFIRMED', 'Cambio registrado por operación')]
    assert (command.action, command.entity_id, command.lock_key) == ('operator.report.status', 'r1', None)


def test_merge_rules_run_in_order():
    rows = {'c': row('c'), 'd': row('d', lat=1.20001)}
    assert MergeDuplicatesCommand('c', ['d']).lock_key is not None
    with pytest.raises(HTTPException) as caught:
        MergeDuplicatesCommand('c', ['c'])
    assert caught.value.status_code == 422
    assert error_of(MergeDuplicatesCommand('c', ['missing']), rows) == (404, 'Algún reporte ya no existe.')
    assert error_of(MergeDuplicatesCommand('c', ['d']), {**rows, 'd': row('d', status='REPAIRED')})[1] == 'Solo se fusionan baches abiertos.'
    assert error_of(MergeDuplicatesCommand('c', ['d']), {**rows, 'd': row('d', pothole='p-c')})[1] == 'Los reportes ya pertenecen al mismo bache.'
    assert error_of(MergeDuplicatesCommand('c', ['d']), {**rows, 'd': row('d', lat=1.21)})[1].startswith('Solo se fusionan reportes a menos de 50 m')
    validate(MergeDuplicatesCommand('c', ['d']), rows)


def test_merge_moves_passes_then_rejects_each_duplicate():
    rows = {'c': row('c'), 'd': row('d'), 'e': row('e')}
    repo = FakeRepository()
    details = MergeDuplicatesCommand('c', ['d', 'e']).apply(repo, rows, 'u1')
    assert details == {'duplicates': 2, 'passesMoved': 4}
    assert repo.calls == [('passes', 'p-d', 'p-c'), ('status', 'p-d', 'REJECTED', 'Duplicado del reporte c'),
                          ('passes', 'p-e', 'p-c'), ('status', 'p-e', 'REJECTED', 'Duplicado del reporte c')]


def test_rules_are_reusable_with_a_custom_message():
    rule = ReportsExistRule('No encontrado.')
    with pytest.raises(HTTPException) as caught:
        rule.handle(ValidationContext(ChangeStatusCommand('x', 'CONFIRMED'), {}))
    assert caught.value.detail == 'No encontrado.'
