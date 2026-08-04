from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import quote

import duckdb


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
COMPRESSION = {"uncompressed", "snappy", "gzip", "zstd", "lz4", "brotli"}


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--:--"
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def log(message: str, level: str = "INFO") -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {message}", flush=True)


def progress_line(index: int, total: int, started: float, symbol: str, action: str) -> None:
    completed = index - 1
    percent = (completed / total * 100) if total else 100.0
    elapsed = time.monotonic() - started
    eta = (elapsed / completed * (total - completed)) if completed else None
    log(
        f"[PROGRESS {percent:6.2f}%] [{index:,}/{total:,}] "
        f"[elapsed {duration(elapsed)}] [ETA {duration(eta)}] "
        f"symbol={symbol!r} action={action}"
    )


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export every equity in a Citus/PostgreSQL table to an individual Parquet file"
    )
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--refresh", action="store_true", help="replace existing equity files")
    parser.add_argument(
        "--recreate", action="store_true",
        help="delete the configured output directory and rebuild every file",
    )
    parser.add_argument(
        "--incremental", action="store_true",
        help="append source rows newer than each file's latest incremental column",
    )
    parser.add_argument("--equity", action="append", help="export only this equity (repeatable)")
    parser.add_argument("--limit-equities", type=int, help="limit exports for a test run")
    parser.add_argument("--verify-only", action="store_true")
    result = parser.parse_args()
    if result.recreate:
        result.refresh = True
    if result.refresh and result.incremental:
        parser.error("--refresh/--recreate and --incremental cannot be used together")
    return result


def identifier(value: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return '"' + value.replace('"', '""') + '"'


def load_configuration(path: Path) -> dict:
    path = path.resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    for section in ("database", "source", "output", "duckdb"):
        if section not in config or not isinstance(config[section], dict):
            raise ValueError(f"Missing configuration section: {section}")

    source = config["source"]
    for key in ("schema", "table", "equity_column"):
        identifier(source[key])
    columns = source.get("columns", ["*"])
    if columns != ["*"]:
        if not columns or not all(isinstance(column, str) for column in columns):
            raise ValueError("source.columns must be [\"*\"] or a non-empty identifier list")
        for column in columns:
            identifier(column)
    for column in source.get("order_by", []):
        identifier(column)
    if source.get("incremental_column"):
        identifier(source["incremental_column"])
    normalize_to_date = source.get("normalize_to_date", [])
    if not isinstance(normalize_to_date, list):
        raise ValueError("source.normalize_to_date must be an identifier list")
    for column in normalize_to_date:
        identifier(column)
    if columns != ["*"] and any(column not in columns for column in normalize_to_date):
        raise ValueError("Every source.normalize_to_date column must also appear in source.columns")
    if source.get("eligibility_column"):
        identifier(source["eligibility_column"])
        minimum = source.get("eligibility_min_exclusive", 0)
        if not isinstance(minimum, (int, float)) or isinstance(minimum, bool):
            raise ValueError("source.eligibility_min_exclusive must be numeric")
    where = source.get("where")
    if where is not None and (not isinstance(where, str) or ";" in where):
        raise ValueError("source.where must be one SQL expression without a semicolon")

    output = config["output"]
    directory = Path(output.get("directory", "database"))
    output["directory"] = (path.parent / directory).resolve() if not directory.is_absolute() else directory.resolve()
    output.setdefault("filename", "tl.parquet")
    if Path(output["filename"]).name != output["filename"] or not output["filename"].endswith(".parquet"):
        raise ValueError("output.filename must be a plain .parquet filename")
    output.setdefault("compression", "zstd")
    if output["compression"].lower() not in COMPRESSION:
        raise ValueError(f"Unsupported compression: {output['compression']}")
    output.setdefault("row_group_size", 122880)

    duck = config["duckdb"]
    temporary = Path(duck.get("temp_directory", output["directory"] / "_temp"))
    duck["temp_directory"] = ((path.parent / temporary).resolve()
                                 if not temporary.is_absolute() else temporary.resolve())
    duck.setdefault("memory_limit", "8GB")
    duck.setdefault("threads", max(1, (os.cpu_count() or 2) // 2))
    return config


def env_value(database: dict, key: str, default: str | None = None) -> str:
    env_name = database.get(f"{key}_env")
    value = os.environ.get(env_name, "") if env_name else str(database.get(key, ""))
    value = value or (default or "")
    if not value:
        raise ValueError(f"Database setting {key!r} is missing (expected environment variable {env_name!r})")
    return value


def pg_connection_string(database: dict) -> str:
    values = {
        "host": env_value(database, "host"),
        "port": env_value(database, "port", "5432"),
        "dbname": env_value(database, "name"),
        "user": env_value(database, "user"),
        "password": env_value(database, "password"),
        "sslmode": str(database.get("sslmode", "require")),
    }

    def escape(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    return " ".join(f"{key}={escape(value)}" for key, value in values.items())


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def safe_symbol(symbol: str) -> str:
    return quote(symbol, safe="-_.&()")


def symbol_group(symbol: str) -> str:
    first = symbol[:1].lower()
    return first if first.isascii() and first.isalnum() else "_"


def source_sql(config: dict) -> tuple[str, str, str]:
    source = config["source"]
    table = f"citus.{identifier(source['schema'])}.{identifier(source['table'])}"
    equity = identifier(source["equity_column"])
    selected = source.get("columns", ["*"])
    normalized_columns = source.get("normalize_to_date", [])
    normalized = set(normalized_columns)
    if selected == ["*"]:
        columns = "*" if not normalized else (
            f"* EXCLUDE ({', '.join(identifier(column) for column in normalized_columns)}), "
            + ", ".join(
                f"CAST(CAST({identifier(column)} AS DATE) AS TIMESTAMP) AS {identifier(column)}"
                for column in normalized_columns
            )
        )
    else:
        columns = ", ".join(
            (f"CAST(CAST({identifier(column)} AS DATE) AS TIMESTAMP) AS {identifier(column)}"
             if column in normalized else identifier(column))
            for column in selected
        )
    return table, equity, columns


def configure_duckdb(config: dict):
    output = config["output"]["directory"]
    temporary = config["duckdb"]["temp_directory"]
    output.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(parents=True, exist_ok=True)
    log(
        f"Configuring DuckDB: memory_limit={config['duckdb']['memory_limit']}, "
        f"threads={config['duckdb']['threads']}, temp_directory={temporary}"
    )
    connection = duckdb.connect()
    connection.execute(f"SET memory_limit = {sql_literal(str(config['duckdb']['memory_limit']))}")
    connection.execute(f"SET threads = {int(config['duckdb']['threads'])}")
    connection.execute(f"SET temp_directory = {sql_literal(str(temporary))}")
    log("Loading DuckDB PostgreSQL extension")
    connection.execute("INSTALL postgres; LOAD postgres")
    dsn = pg_connection_string(config["database"])
    log("Connecting read-only to the configured Citus coordinator")
    try:
        connection.execute(f"ATTACH {sql_literal(dsn)} AS citus (TYPE POSTGRES, READ_ONLY)")
    except duckdb.Error as error:
        password = env_value(config["database"], "password")
        message = str(error).replace(password, "***").replace(password.replace("'", "\\'"), "***")
        connection.close()
        raise RuntimeError(f"Could not connect to the Citus coordinator: {message}") from None
    log("Citus connection established")
    return connection


def output_path(config: dict, symbol: str) -> Path:
    return (config["output"]["directory"] / symbol_group(symbol) /
            safe_symbol(symbol) / config["output"]["filename"])


def clear_output_directory(config: dict, config_path: Path) -> None:
    output = config["output"]["directory"].resolve()
    project = Path(__file__).resolve().parent
    drive_root = Path(output.anchor).resolve()
    forbidden = {drive_root, project, config_path.resolve().parent}
    if output in forbidden or output.parent == drive_root:
        raise ValueError(f"Refusing to recursively delete unsafe output directory: {output}")
    if output.exists():
        log(f"RECREATE requested: deleting generated output directory {output}", "WARNING")
        shutil.rmtree(output)
        log(f"Deleted generated output directory {output}", "SUCCESS")
    else:
        log(f"RECREATE requested: output directory does not yet exist: {output}")


def list_equities(connection, config: dict, selected: list[str] | None, limit: int | None) -> list[str]:
    source = config["source"]
    remote_table = f"{identifier(source['schema'])}.{identifier(source['table'])}"
    equity = identifier(source["equity_column"])
    where = config["source"].get("where")
    clauses = [f"{equity} IS NOT NULL", f"trim(CAST({equity} AS VARCHAR)) <> ''"]
    if where:
        clauses.append(f"({where})")
    if selected:
        clauses.append(f"CAST({equity} AS VARCHAR) IN ({','.join(sql_literal(item) for item in selected)})")
    equity_expression = f"CAST({equity} AS VARCHAR)"
    eligibility_column = source.get("eligibility_column")
    if eligibility_column:
        minimum = source.get("eligibility_min_exclusive", 0)
        remote_sql = (
            f"SELECT {equity_expression} AS equity FROM {remote_table} "
            f"WHERE {' AND '.join(clauses)} GROUP BY {equity_expression} "
            f"HAVING max({identifier(eligibility_column)}) > {minimum!r} ORDER BY equity"
        )
    else:
        remote_sql = (
            f"SELECT DISTINCT {equity_expression} AS equity FROM {remote_table} "
            f"WHERE {' AND '.join(clauses)} ORDER BY equity"
        )
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit-equities must be positive")
        remote_sql += f" LIMIT {limit}"
    # postgres_query executes aggregation on Citus instead of transferring every
    # source equity value into DuckDB before applying DISTINCT.
    sql = f"SELECT equity FROM postgres_query('citus', {sql_literal(remote_sql)})"
    return [row[0] for row in connection.execute(sql).fetchall()]


def export_equity(connection, config: dict, symbol: str, destination: Path,
                  start_after=None) -> int:
    table, equity, columns = source_sql(config)
    where = config["source"].get("where")
    order = config["source"].get("order_by", [])
    predicate = f"CAST({equity} AS VARCHAR) = {sql_literal(symbol)}"
    if where:
        predicate += f" AND ({where})"
    incremental_column = config["source"].get("incremental_column")
    if start_after is not None:
        if not incremental_column:
            raise ValueError("source.incremental_column is required for incremental exports")
        value = start_after.isoformat(sep=" ") if hasattr(start_after, "isoformat") else str(start_after)
        if incremental_column in config["source"].get("normalize_to_date", []):
            predicate += (
                f" AND CAST({identifier(incremental_column)} AS DATE) > "
                f"CAST({sql_literal(value)} AS DATE)"
            )
        else:
            predicate += f" AND {identifier(incremental_column)} > {sql_literal(value)}"
    order_sql = f" ORDER BY {', '.join(identifier(column) for column in order)}" if order else ""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.parquet")
    delta = destination.with_suffix(".delta.parquet") if start_after is not None else temporary
    temporary.unlink(missing_ok=True)
    delta.unlink(missing_ok=True)
    compression = config["output"]["compression"].upper()
    row_group = int(config["output"]["row_group_size"])
    try:
        connection.execute(
            f"COPY (SELECT {columns} FROM {table} WHERE {predicate}{order_sql}) "
            f"TO {sql_literal(str(delta))} (FORMAT PARQUET, COMPRESSION {compression}, "
            f"ROW_GROUP_SIZE {row_group})"
        )
        rows = connection.execute(
            "SELECT coalesce(sum(num_rows), 0) FROM parquet_file_metadata(?)", [str(delta)]
        ).fetchone()[0]
        if start_after is not None:
            if rows == 0:
                return 0
            order_sql = (f" ORDER BY {', '.join(identifier(column) for column in order)}"
                         if order else "")
            connection.execute(
                f"COPY (SELECT * FROM read_parquet({sql_literal(str(destination))}) "
                f"UNION ALL SELECT * FROM read_parquet({sql_literal(str(delta))}){order_sql}) "
                f"TO {sql_literal(str(temporary))} (FORMAT PARQUET, COMPRESSION {compression}, "
                f"ROW_GROUP_SIZE {row_group})"
            )
        os.replace(temporary, destination)
        return int(rows)
    finally:
        temporary.unlink(missing_ok=True)
        delta.unlink(missing_ok=True)


def latest_incremental_value(connection, config: dict, destination: Path):
    column = config["source"].get("incremental_column")
    if not column:
        raise ValueError("source.incremental_column is required for --incremental")
    return connection.execute(
        f"SELECT max({identifier(column)}) FROM read_parquet(?)", [str(destination)]
    ).fetchone()[0]


def verify(config: dict) -> tuple[int, int]:
    root = config["output"]["directory"]
    filename = config["output"]["filename"]
    log(f"Scanning completed Parquet files under {root}")
    files = list(root.glob(f"*/*/{filename}"))
    if not files:
        raise RuntimeError(f"No {filename} files found in {root}")
    connection = duckdb.connect()
    rows, file_count = connection.execute(
        "SELECT sum(num_rows), count(*) FROM parquet_file_metadata(?)",
        [[str(path) for path in files]],
    ).fetchone()
    connection.close()
    return int(rows), int(file_count)


def main() -> int:
    args = arguments()
    config = load_configuration(args.config)
    mode = ("recreate" if args.recreate else "refresh" if args.refresh else
            "incremental" if args.incremental else "missing-files-only")
    source = config["source"]
    log("=" * 78)
    log("Citus to Parquet export started")
    log(f"Mode: {mode}")
    log(f"Source: {source['schema']}.{source['table']}")
    log(f"Equity column: {source['equity_column']}")
    if source.get("eligibility_column"):
        log(
            f"Symbol eligibility: at least one row with "
            f"{source['eligibility_column']} > {source.get('eligibility_min_exclusive', 0)}"
        )
    log(f"Selected columns: {len(source.get('columns', ['*']))}")
    log(f"Output directory: {config['output']['directory']}")
    log(f"Output filename: {config['output']['filename']}")
    log(f"Compression: {config['output']['compression']}")
    log("=" * 78)
    if args.verify_only:
        rows, files = verify(config)
        log(f"Verified {files:,} Parquet files containing {rows:,} rows", "SUCCESS")
        return 0

    if args.recreate:
        clear_output_directory(config, args.config)

    started = time.monotonic()
    connection = configure_duckdb(config)
    try:
        log("Querying Citus for the distinct equity universe")
        equities = list_equities(connection, config, args.equity, args.limit_equities)
        if not equities:
            raise RuntimeError("The equity query returned no values")
        log(f"Equity discovery complete: found {len(equities):,} equities", "SUCCESS")
        exported = skipped = total_rows = 0
        for index, symbol in enumerate(equities, 1):
            destination = output_path(config, symbol)
            if destination.exists() and not args.refresh and not args.incremental:
                progress_line(index, len(equities), started, symbol, "checking existing file")
                skipped += 1
                log(f"SKIP symbol={symbol!r}; completed file already exists: {destination}")
                continue
            if destination.exists() and args.incremental:
                progress_line(index, len(equities), started, symbol, "reading incremental watermark")
                start_after = latest_incremental_value(connection, config, destination)
                log(f"Incremental watermark for symbol={symbol!r}: {start_after}")
                log(f"Querying source rows newer than {start_after} for symbol={symbol!r}")
            else:
                start_after = None
                action = "refreshing complete file" if args.refresh else "creating missing file"
                progress_line(index, len(equities), started, symbol, action)
                log(f"Querying all configured source columns for symbol={symbol!r}")
            rows = export_equity(connection, config, symbol, destination, start_after)
            if args.incremental and start_after is not None and rows == 0:
                skipped += 1
                log(f"CURRENT symbol={symbol!r}; no rows newer than {start_after}")
                continue
            exported += 1
            total_rows += rows
            action = "added" if start_after is not None else "wrote"
            log(
                f"OK symbol={symbol!r}; {action} {rows:,} rows; output={destination}",
                "SUCCESS",
            )
    finally:
        log("Closing DuckDB and Citus connections")
        connection.close()
    elapsed = time.monotonic() - started
    log("=" * 78)
    log(
        f"Export complete: exported={exported:,}, current/skipped={skipped:,}, "
        f"new rows written={total_rows:,}, elapsed={duration(elapsed)}",
        "SUCCESS",
    )
    log("Overall progress: 100.00%")
    log("=" * 78)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (duckdb.Error, OSError, ValueError, RuntimeError) as error:
        print(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ERROR] Export failed: {error}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)
