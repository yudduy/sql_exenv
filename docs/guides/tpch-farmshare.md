# TPC-H “Gym” on Farmshare (No Docker, No Root)

This guide sets up a local PostgreSQL 15+ cluster in your home directory on Farmshare and loads the TPC-H 1GB dataset (SF=1). It also enables HypoPG for hypothetical index proof. All steps are non-root and safe for shared environments.

---

## Overview

- Option A: Use Farmshare’s prebuilt PostgreSQL via `module`.
- Option B: Build PostgreSQL from source into `$HOME/postgres` (fallback if no module).
- Load TPC-H SF=1 using `tpch-kit/dbgen` and `\copy`.
- Enable `hypopg` extension and analyze the database.

At the end, you’ll have a connection string like:

```bash
export TEST_DB_URL="postgresql://$USER@localhost:5432/tpch_test"
```

---

## Option A (Preferred): Farmshare Modules

1) Check for available modules

```bash
module avail postgresql
```

2) Load a recent module (e.g., PostgreSQL 15.x)

```bash
module load postgresql/15.2
which psql
psql --version
```

3) Initialize a local cluster in your home directory

```bash
mkdir -p $HOME/pgdata-tpch
initdb -D $HOME/pgdata-tpch
pg_ctl -D $HOME/pgdata-tpch -l $HOME/pgdata-tpch/logfile start
createdb tpch_test
```

If the server is already running, `pg_ctl` will report it.

---

## Option B (Fallback): Build PostgreSQL from Source

1) Download and unpack

```bash
wget https://ftp.postgresql.org/pub/source/v15.5/postgresql-15.5.tar.gz
tar -zxvf postgresql-15.5.tar.gz
cd postgresql-15.5
```

2) Configure, build, and install to `$HOME/postgres`

```bash
./configure --prefix=$HOME/postgres --without-readline
make -j
make install
```

3) Add to your PATH (add to ~/.bashrc for persistence)

```bash
export PATH="$HOME/postgres/bin:$PATH"
```

4) Initialize and start the server, create DB

```bash
mkdir -p $HOME/pgdata-tpch
initdb -D $HOME/pgdata-tpch
pg_ctl -D $HOME/pgdata-tpch -l $HOME/pgdata-tpch/logfile start
createdb tpch_test
```

---

## Load TPC-H SF=1

1) Clone and build dbgen

```bash
git clone https://github.com/gregrahn/tpch-kit.git
cd tpch-kit/dbgen
make MACHINE=LINUX DATABASE=POSTGRESQL
```

2) Generate data (about 1GB for SF=1)

```bash
./dbgen -vf -s 1
# Produces: customer.tbl, orders.tbl, lineitem.tbl, nation.tbl, region.tbl, partsupp.tbl, part.tbl, supplier.tbl
```

3) Create schema

```bash
psql -d tpch_test -f dss.ddl
```

4) Load data with \copy (run these inside psql)

```sql
\copy nation    FROM '/path/to/tpch-kit/dbgen/nation.tbl'    WITH (FORMAT text, DELIMITER '|');
\copy region    FROM '/path/to/tpch-kit/dbgen/region.tbl'    WITH (FORMAT text, DELIMITER '|');
\copy part      FROM '/path/to/tpch-kit/dbgen/part.tbl'      WITH (FORMAT text, DELIMITER '|');
\copy supplier  FROM '/path/to/tpch-kit/dbgen/supplier.tbl'  WITH (FORMAT text, DELIMITER '|');
\copy partsupp  FROM '/path/to/tpch-kit/dbgen/partsupp.tbl'  WITH (FORMAT text, DELIMITER '|');
\copy customer  FROM '/path/to/tpch-kit/dbgen/customer.tbl'  WITH (FORMAT text, DELIMITER '|');
\copy orders    FROM '/path/to/tpch-kit/dbgen/orders.tbl'    WITH (FORMAT text, DELIMITER '|');
\copy lineitem  FROM '/path/to/tpch-kit/dbgen/lineitem.tbl'  WITH (FORMAT text, DELIMITER '|');
```

Tip: If you prefer a shell loop (outside psql), remember to strip trailing pipes. Example:

```bash
for i in nation region part supplier partsupp customer orders lineitem; do \
  sed 's/|$//' tpch-kit/dbgen/$i.tbl > /tmp/$i.cleaned && \
  psql -d tpch_test -c "COPY $i FROM '/tmp/$i.cleaned' WITH (FORMAT csv, DELIMITER '|')"; \
  rm /tmp/$i.cleaned; \
done
```

---

## Enable HypoPG and Analyze

### If HypoPG is already available

```sql
psql -d tpch_test -c "CREATE EXTENSION IF NOT EXISTS hypopg;"
```

### If you need to build HypoPG (no root)

1) Ensure your `pg_config` is on PATH (from your module or $HOME/postgres/bin)

```bash
which pg_config
```

2) Build and install via PGXS

```bash
git clone https://github.com/HypoPG/hypopg.git
cd hypopg
make
make install
```

3) Enable extension

```bash
psql -d tpch_test -c "CREATE EXTENSION IF NOT EXISTS hypopg;"
```

(Optional) `pg_stat_statements` requires `shared_preload_libraries` and a server restart, so skip unless you need it.

### Analyze statistics

```bash
psql -d tpch_test -c "ANALYZE;"
```

---

## Verify and Export URL

```bash
psql -d tpch_test -c "\dt"  # should list 8 TPC-H tables
export TEST_DB_URL="postgresql://$USER@localhost:5432/tpch_test"
```

You can now run the CLI:

```bash
python exev.py \
  -q "SELECT * FROM orders WHERE o_custkey = 123 AND o_orderstatus = 'F';" \
  -d "$TEST_DB_URL" \
  --max-cost 1000 \
  --max-time-ms 60000 \
  --analyze-cost-threshold 10000000 \
  --use-hypopg \
  -o output.json
```

If `hypopg` isn’t available, the CLI still works and will simply omit the proof block.

---

## Troubleshooting

- `psql: command not found` — Ensure module is loaded or `$HOME/postgres/bin` is on PATH.
- `permission denied creating extension hypopg` — Build via PGXS into your user space, then `CREATE EXTENSION`.
- `server not running` — Check `pg_ctl -D $HOME/pgdata-tpch status` and review `$HOME/pgdata-tpch/logfile`.
- Slow queries on first run — Run `ANALYZE;` once after data load.
