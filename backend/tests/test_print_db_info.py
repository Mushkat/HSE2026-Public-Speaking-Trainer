from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'print_db_info.py'
SPEC = spec_from_file_location('print_db_info', SCRIPT_PATH)
MODULE = module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_mask_url_hides_password() -> None:
    masked = MODULE.mask_url('postgresql+psycopg2://postgres:secret@db:5432/speech_trainer')
    assert 'secret' not in masked
    assert '***' in masked


def test_describe_database_url_extracts_runtime_target() -> None:
    details = MODULE.describe_database_url('postgresql+psycopg2://postgres:postgres@db:5432/speech_trainer?sslmode=disable')
    assert details['drivername'] == 'postgresql+psycopg2'
    assert details['host'] == 'db'
    assert details['port'] == 5432
    assert details['database'] == 'speech_trainer'
    assert details['query'] == {'sslmode': 'disable'}
