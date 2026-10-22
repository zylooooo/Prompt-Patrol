from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def test_revision_ids_fit_alembic_version_column():
    # alembic_version.version_num is varchar(32). SQLite ignores the length, so
    # an over-long id only fails on Postgres, mid-deploy.
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    too_long = [rev.revision for rev in script.walk_revisions() if len(rev.revision) > 32]
    assert too_long == []
