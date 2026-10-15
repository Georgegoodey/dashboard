"""The SQL guard: what the console, charts and chat agent may run. (The database role is the second layer.)"""
import pytest

from app.db import sqlguard
from app.db.sqlguard import SqlRejected, validate

ACCEPTED = [
    "SELECT * FROM v_properties",
    "select id, rent_pcm from v_properties where bedrooms = 2 order by rent_pcm limit 20;",
    "SELECT borough, round(avg(rent_pcm)) AS avg_rent FROM v_properties GROUP BY borough",
    "WITH cheap AS (SELECT * FROM v_properties WHERE rent_pcm < 2000) SELECT count(*) FROM cheap",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY rent_pcm) AS median FROM v_properties",
    "SELECT count(*) FILTER (WHERE bedrooms = 1) AS one_beds, rent_pcm::numeric FROM v_properties GROUP BY rent_pcm",
    "SELECT p.id, t.description FROM v_properties p JOIN v_property_text t ON t.property_id = p.id WHERE t.description ILIKE '%garden%'",
    "SELECT job_id, max(finished_at) FROM v_job_runs WHERE status = 'ok' GROUP BY job_id",
    "SELECT date_trunc('week', observed_at) AS week, avg(change_pct) FROM v_price_changes GROUP BY 1 ORDER BY 1",
    "SELECT id FROM v_properties UNION ALL SELECT property_id FROM v_price_changes",
    "SELECT * FROM public.v_properties",
    "SELECT n FROM generate_series(1, 3) AS n",
    "SELECT id, rank() OVER (PARTITION BY borough ORDER BY rent_pcm) FROM v_properties",
]

REJECTED = [
    ("DELETE FROM listings", "Only SELECT"),
    ("DROP TABLE properties", "Only SELECT"),
    ("UPDATE v_properties SET rent_pcm = 0", "Only SELECT"),
    ("INSERT INTO listings (id) VALUES (1)", "Only SELECT"),
    ("SELECT 1; SELECT 2", "single statement"),
    ("SELECT 1; DROP TABLE properties", "single statement"),
    ("SELECT * FROM listings", "not available"),
    ("SELECT * FROM properties p JOIN v_properties v ON v.id = p.id", "not available"),
    ("SELECT * FROM pg_catalog.pg_roles", "not available"),
    ("SELECT * FROM information_schema.tables", "not available"),
    ("SELECT * FROM v_properties, listings", "not available"),
    ("SELECT id FROM v_properties WHERE id IN (SELECT id FROM properties)", "not available"),
    ("SELECT pg_sleep(30)", "not allowed"),
    ("SELECT pg_read_file('/etc/passwd')", "not allowed"),
    ("SELECT set_config('default_transaction_read_only', 'off', false)", "not allowed"),
    ("SELECT current_setting('server_version')", "not allowed"),
    ("SELECT query_to_xml('select * from listings', true, true, '')", "not allowed"),
    ("SELECT * INTO newtable FROM v_properties", "Only"),
    ("SELECT * FROM v_properties FOR UPDATE", "Only"),
    ("COPY v_properties TO STDOUT", "Only"),
    ("SET statement_timeout = 0", "Only"),
    ("EXPLAIN ANALYZE SELECT 1", "Only"),
    ("SELEC nonsense (", "parse"),
    ("", "single statement"),
]


@pytest.mark.parametrize("sql", ACCEPTED)
def test_accepts_reads_of_the_curated_views(sql: str) -> None:
    assert validate(sql)


@pytest.mark.parametrize(("sql", "reason"), REJECTED)
def test_rejects_everything_else(sql: str, reason: str) -> None:
    with pytest.raises(SqlRejected, match=reason):
        validate(sql)


def test_a_cte_may_not_hide_a_real_table() -> None:
    with pytest.raises(SqlRejected):
        validate("WITH v_properties AS (SELECT 1) SELECT * FROM listings")


def test_comments_do_not_smuggle_a_second_statement() -> None:
    with pytest.raises(SqlRejected):
        validate("SELECT 1 /* ; */; DELETE FROM listings")


def test_relations_are_the_four_views() -> None:
    assert sqlguard.ALLOWED_RELATIONS == {"v_properties", "v_price_changes", "v_property_text", "v_job_runs"}
