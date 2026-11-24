"""Temporary, token-gated database transfer endpoints. Disabled without secrets."""
import hmac
import os
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update, UniqueConstraint
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import schema as s
from .structures import DynamicArray, HashMap, HashSet, SinglyLinkedList

SKIP_TABLES = HashSet(["auth_attempts"])
PLAIN_FIELDS = HashMap([
    ("users", ("email", "display_name")),
    ("trips", ("encrypted_details",)),
    ("trip_samples", ("encrypted_position",)),
])


class ImportBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str = Field(min_length=1, max_length=80)
    rows: list[dict[str, Any]] = Field(max_length=40)
    mode: str | None = None


class MigrationController:
    """Temporary, token-gated database transfer: /api/migration/import and /api/migration/export."""

    def __init__(self):
        self.router = APIRouter(prefix="/api/migration", include_in_schema=False)
        self.router.add_api_route("/import", self.import_batch, methods=["POST"])
        self.router.add_api_route("/export", self.export_database, methods=["POST"])

    @staticmethod
    def authorized(request: Request) -> bool:
        expected = os.environ.get("DATA_MIGRATION_TOKEN", "")
        provided = request.headers.get("x-bachescan-migration", "")
        return bool(expected) and hmac.compare_digest(expected, provided)


    @staticmethod
    def require_enabled(request: Request) -> None:
        if not MigrationController.authorized(request):
            raise HTTPException(404, "No se pudo completar la operación.")


    @staticmethod
    def unique_column_sets(table):
        sets = SinglyLinkedList[tuple]()
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                names = tuple(column.name for column in constraint.columns)
                if names:
                    sets.append(names)
        for index in table.indexes:
            if index.unique:
                names = tuple(column.name for column in index.columns)
                if names:
                    sets.append(names)
        return sets


    @staticmethod
    def matching_existing(conn, table, row):
        primary = tuple(column.name for column in table.primary_key.columns)
        candidates = MigrationController.unique_column_sets(table)
        candidates.prepend(primary)
        for columns in candidates:
            if not all(name in row and row[name] is not None for name in columns):
                continue
            conditions = [table.c[name] == row[name] for name in columns]
            if table.name == "trips" and columns == ("user_id",) and row.get("ended_at") is None:
                conditions.append(table.c.ended_at.is_(None))
            existing = conn.execute(select(table.c.id).where(*conditions).limit(1)).scalar_one_or_none()
            if existing:
                return existing
        return None


    def import_batch(self, batch: ImportBatch, request: Request):
        MigrationController.require_enabled(request)
        table = s.metadata.tables.get(batch.table)
        if table is None or table.name in SKIP_TABLES:
            raise HTTPException(400, "No se pudo completar la operación.")

        if batch.mode == "preflight":
            with request.app.state.engine.connect() as conn:
                counts = {
                    item.name: conn.execute(select(func.count()).select_from(item)).scalar_one()
                    for item in s.metadata.sorted_tables if item.name not in SKIP_TABLES
                }
            return {"counts": counts}

        vault = request.app.state.vault
        mapped = HashMap[str, str]()
        inserted = 0
        with request.app.state.engine.begin() as conn:
            for source in batch.rows:
                row = dict(source)
                source_id = str(row.get("id", ""))
                if not source_id:
                    raise HTTPException(400, "No se pudo completar la operación.")

                plain = row.pop("__plain", {})
                if table.name == "users":
                    email = str(plain.get("email", "")).strip().lower()
                    display_name = str(plain.get("display_name", "")).strip()
                    if not email or not display_name or not row.get("password_hash"):
                        raise HTTPException(400, "No se pudo completar la operación.")
                    row["email"] = vault.encrypt(email)
                    row["display_name"] = vault.encrypt(display_name)
                    row["email_lookup"] = vault.lookup("email:" + email)
                    match = conn.execute(select(table.c.id).where(table.c.email_lookup == row["email_lookup"])).scalar_one_or_none()
                    if match:
                        conn.execute(update(table).where(table.c.id == match).values(
                            email=row["email"], display_name=row["display_name"],
                            password_hash=row["password_hash"], created_at=row["created_at"],
                        ))
                        mapped.put(source_id, str(match))
                        inserted += 1
                        continue
                elif table.name in PLAIN_FIELDS:
                    field = PLAIN_FIELDS[table.name][0]
                    value = plain.get(field)
                    if not isinstance(value, str):
                        raise HTTPException(400, "No se pudo completar la operación.")
                    row[field] = vault.encrypt(value)

                try:
                    result = conn.execute(pg_insert(table).values(row).on_conflict_do_nothing())
                except Exception:
                    raise HTTPException(409, "No se pudo completar la operación. Revisa la base de destino.") from None
                if result.rowcount:
                    mapped.put(source_id, source_id)
                    inserted += 1
                    continue

                existing_id = MigrationController.matching_existing(conn, table, row)
                if existing_id is None:
                    raise HTTPException(409, "No se pudo completar la operación. Revisa la base de destino.")
                if table.name == "trips" and row.get("ended_at") is None:
                    raise HTTPException(409, "No se pudo completar la operación. Revisa la base de destino.")
                mapped.put(source_id, str(existing_id))

        return {"table": batch.table, "inserted": inserted, "idMap": dict(mapped.items())}


    async def export_database(self, request: Request):
        MigrationController.require_enabled(request)
        target = os.environ.get("DATA_MIGRATION_TARGET", "").rstrip("/")
        parsed_target = urlsplit(target)
        if (parsed_target.scheme != "https" or
                parsed_target.hostname != "bachescanai-app.wittyhill-59fbb47a.westus.azurecontainerapps.io" or
                parsed_target.path != "/api/migration/import" or parsed_target.query or parsed_target.fragment):
            raise HTTPException(404, "No se pudo completar la operación.")
        token = os.environ["DATA_MIGRATION_TOKEN"]
        vault = request.app.state.vault
        id_maps = HashMap[str, str]()
        totals = HashMap[str, int]()

        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
            preflight = await client.post(target, headers={"x-bachescan-migration": token},
                                         json={"table": "countries", "rows": [], "mode": "preflight"})
            if preflight.status_code != 200:
                raise HTTPException(502, "No se pudo validar la base de destino.")
            target_counts = preflight.json().get("counts", {})

            for table in s.metadata.sorted_tables:
                if table.name in SKIP_TABLES:
                    continue
                with request.app.state.engine.connect() as conn:
                    rows = SinglyLinkedList[dict](dict(row) for row in conn.execute(select(table)).mappings())
                totals.put(table.name, len(rows))
                batch_rows = DynamicArray[dict](capacity=40)
                for row in rows:
                    for field in table.c:
                        if field.foreign_keys and row.get(field.name) is not None:
                            row[field.name] = id_maps.get(str(row[field.name]), str(row[field.name]))
                    if table.name == "users":
                        row["__plain"] = {"email": vault.decrypt(row.pop("email")),
                                           "display_name": vault.decrypt(row.pop("display_name"))}
                        row.pop("email_lookup", None)
                    elif table.name in PLAIN_FIELDS:
                        field = PLAIN_FIELDS[table.name][0]
                        row["__plain"] = {field: vault.decrypt(row.pop(field))}
                    elif table.name == "sessions":
                        row["expires_at"] = 0
                    if table.name == "trips" and row.get("ended_at") is None:
                        row["ended_at"] = s.Clock.now()
                    batch_rows.append(row)
                    if len(batch_rows) == 40:
                        await MigrationController.send_batch(client, target, token, table.name, list(batch_rows), id_maps)
                        batch_rows = DynamicArray[dict](capacity=40)
                if batch_rows:
                    await MigrationController.send_batch(client, target, token, table.name, list(batch_rows), id_maps)

        return {"status": "complete", "rows": dict(totals.items()), "destinationRowsBefore": target_counts}


    @staticmethod
    async def send_batch(client, target, token, table_name, rows, id_maps):
        try:
            response = await client.post(target, headers={"x-bachescan-migration": token},
                                         json={"table": table_name, "rows": rows})
        except httpx.HTTPError:
            raise HTTPException(502, "No se pudo enviar un lote a Azure.") from None
        if response.status_code != 200:
            raise HTTPException(502, "Azure rechazó un lote; la migración quedó detenida.")
        mapped = response.json().get("idMap", {})
        for source_id, target_id in mapped.items():
            id_maps.put(str(source_id), str(target_id))
