import sqlite3

from alembic import command

from app.data.migrate import _build_config, run_migrations


def _tables(db_path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_run_migrations_creates_full_schema_from_scratch(tmp_path):
    db_path = tmp_path / "inventory.db"
    assert not db_path.exists()

    run_migrations(str(db_path))

    tables = _tables(db_path)
    assert "alembic_version" in tables
    for expected in ("users", "products", "stock_transactions", "audit_logs"):
        assert expected in tables


def test_run_migrations_is_idempotent(tmp_path):
    db_path = tmp_path / "inventory.db"
    run_migrations(str(db_path))
    run_migrations(str(db_path))  # must not raise on an already-current DB

    assert "alembic_version" in _tables(db_path)


def test_run_migrations_adopts_a_pre_alembic_database(tmp_path):
    """A database created by an older version of the app (before Alembic
    was introduced) has all the application tables from create_all but no
    alembic_version table. Migrations must adopt it in place rather than
    trying to re-create tables that already exist.

    Such a database reflects the schema as of the first migration (not the
    current models, which may have moved on since), so it's built by running
    just that first migration and then dropping its version tracking.
    """
    db_path = tmp_path / "inventory.db"
    config = _build_config(db_path)
    initial_revision = "fe4783f90f4f"
    command.upgrade(config, initial_revision)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE alembic_version")
        conn.commit()
    finally:
        conn.close()

    tables_before = _tables(db_path)
    assert "users" in tables_before
    assert "alembic_version" not in tables_before

    run_migrations(str(db_path))

    tables_after = _tables(db_path)
    assert "alembic_version" in tables_after
    assert tables_after >= tables_before



def test_user_attribution_columns_are_added(tmp_path):
    db_path = tmp_path / "inventory.db"
    run_migrations(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        expected_columns = {
            "stock_transactions": "user_id",
            "purchases": "created_by_user_id",
            "sales": "created_by_user_id",
            "stock_adjustments": "created_by_user_id",
        }
        for table, column in expected_columns.items():
            columns = {
                row[1]: row for row in conn.execute(f"PRAGMA table_info({table})")
            }
            assert column in columns
            assert columns[column][3] == 0, (
                f"{table}.{column} must remain nullable for historical records"
            )
        transaction_columns = {
            row[1]: row
            for row in conn.execute("PRAGMA table_info(stock_transactions)")
        }
        for column in ("party_type", "party_name"):
            assert column in transaction_columns
            assert transaction_columns[column][3] == 0, (
                f"stock_transactions.{column} must remain nullable for historical records"
            )
    finally:
        conn.close()

def test_purchase_order_database_constraints_are_created(tmp_path):
    db_path = tmp_path / "inventory.db"
    run_migrations(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        expected_constraints = {
            "purchase_order_items": (
                "ck_po_item_ordered_quantity_positive",
                "ck_po_item_unit_price_nonnegative",
            ),
            "purchase_order_receipt_items": (
                "ck_po_receipt_item_quantity_positive",
            ),
            "purchase_order_closure_items": (
                "ck_po_closure_item_quantity_positive",
                "ck_po_closure_reason_code",
                "ck_po_closure_other_explanation",
            ),
        }

        for table, constraints in expected_constraints.items():
            row = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()

            assert row is not None, f"Missing table: {table}"
            table_sql = row[0].lower()

            for constraint in constraints:
                assert constraint.lower() in table_sql, (
                    f"Missing database constraint {constraint} on {table}"
                )
    finally:
        conn.close()

def test_purchase_order_numeric_constraints_reject_invalid_values(tmp_path):
    db_path = tmp_path / "inventory.db"
    run_migrations(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, role, is_active) "
            "VALUES ('constraint-test', 'hash', 'salt', 'admin', 1)"
        )
        conn.execute(
            "INSERT INTO products "
            "(sku, name, price, reorder_level, current_stock, is_active) "
            "VALUES ('CONSTRAINT-TEST', 'Constraint Test', '10', '0', '0', 1)"
        )
        conn.execute(
            "INSERT INTO purchase_orders "
            "(supplier_id, reference, status, created_by_user_id, created_at) "
            "VALUES (NULL, 'PO-CONSTRAINT-TEST', 'open', 1, '2026-01-01 00:00:00')"
        )

        def assert_rejected(sql, params):
            try:
                conn.execute(sql, params)
            except sqlite3.IntegrityError:
                return
            raise AssertionError(f"SQLite accepted invalid data: {params}")

        # Ordered quantity must be positive; unit cost cannot be negative.
        assert_rejected(
            "INSERT INTO purchase_order_items "
            "(purchase_order_id, product_id, ordered_quantity, unit_price) "
            "VALUES (1, 1, ?, '10')",
            ("0",),
        )
        assert_rejected(
            "INSERT INTO purchase_order_items "
            "(purchase_order_id, product_id, ordered_quantity, unit_price) "
            "VALUES (1, 1, ?, '10')",
            ("-2",),
        )
        assert_rejected(
            "INSERT INTO purchase_order_items "
            "(purchase_order_id, product_id, ordered_quantity, unit_price) "
            "VALUES (1, 1, '5', ?)",
            ("-0.01",),
        )

        # Create valid parent records for receipt and closure item tests.
        conn.execute(
            "INSERT INTO purchase_order_items "
            "(purchase_order_id, product_id, ordered_quantity, unit_price) "
            "VALUES (1, 1, '10', '10')"
        )
        conn.execute(
            "INSERT INTO purchase_order_receipts "
            "(purchase_order_id, created_by_user_id, received_at) "
            "VALUES (1, 1, '2026-01-01 00:00:00')"
        )
        conn.execute(
            "INSERT INTO purchase_order_closures "
            "(purchase_order_id, closed_by_user_id, closed_at) "
            "VALUES (1, 1, '2026-01-01 00:00:00')"
        )

        assert_rejected(
            "INSERT INTO purchase_order_receipt_items "
            "(receipt_id, purchase_order_item_id, quantity) "
            "VALUES (1, 1, ?)",
            ("0",),
        )
        assert_rejected(
            "INSERT INTO purchase_order_receipt_items "
            "(receipt_id, purchase_order_item_id, quantity) "
            "VALUES (1, 1, ?)",
            ("-3",),
        )
        assert_rejected(
            "INSERT INTO purchase_order_closure_items "
            "(closure_id, purchase_order_item_id, quantity, reason_code) "
            "VALUES (1, 1, ?, 'supplier_out_of_stock')",
            ("0",),
        )
        assert_rejected(
            "INSERT INTO purchase_order_closure_items "
            "(closure_id, purchase_order_item_id, quantity, reason_code) "
            "VALUES (1, 1, ?, 'supplier_out_of_stock')",
            ("-4",),
        )

        # Zero unit cost is valid.
        conn.execute(
            "INSERT INTO purchase_order_items "
            "(purchase_order_id, product_id, ordered_quantity, unit_price) "
            "VALUES (1, 1, '1', '0')"
        )
        conn.commit()
    finally:
        conn.close()



def test_damaged_goods_table_is_created(tmp_path):
    db_path = tmp_path / "inventory.db"
    run_migrations(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        columns = {
            row[1]: row for row in conn.execute("PRAGMA table_info(damaged_goods)")
        }
        expected = {
            "id", "unit_name", "quantity", "supplier_name",
            "date_brought", "recorded_by_user_id", "recorded_at",
        }
        assert expected <= set(columns)
        assert columns["recorded_by_user_id"][3] == 1
        foreign_keys = conn.execute("PRAGMA foreign_key_list(damaged_goods)").fetchall()
        assert len(foreign_keys) == 1
        assert foreign_keys[0][2] == "users"
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'damaged_goods'"
        ).fetchone()[0].lower()
        assert "quantity > 0" in table_sql
    finally:
        conn.close()
