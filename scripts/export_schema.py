from pathlib import Path
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects import postgresql
from app.schema import metadata

if __name__ == '__main__':
    dialect = postgresql.dialect()
    sql = []
    for table in metadata.sorted_tables:
        sql.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ';')
        sql.extend(str(CreateIndex(index).compile(dialect=dialect)) + ';' for index in sorted(table.indexes, key=lambda x: x.name))
    Path('migrations/0001_schema.sql').write_text('\n\n'.join(sql) + '\n', encoding='utf-8')
    print(f'{len(metadata.tables)} tablas exportadas')
