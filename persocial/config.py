"""All runtime configuration comes from env (.env in dev). Nothing points back into any
other workspace — the only code that reads outside this repo is the backfill CLI, and it
takes those paths as arguments."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore",
                                      populate_by_name=True)

    # Local Supabase (the processing hub). Defaults match `supabase start`.
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:55322/postgres"
    supabase_url: str = "http://127.0.0.1:55321"
    supabase_service_key: str = ""          # `supabase status` -> service_role / secret key

    # Cloud Supabase (the reviewer side). Empty = sync disabled.
    cloud_database_url: str = ""            # session pooler URI, port 5432
    cloud_supabase_url: str = ""
    cloud_service_key: str = ""
    sync_score_distributions: bool = False  # push full score JSON to cloud (bigger) or top only

    storage_root: Path = REPO_ROOT / "storage"   # raw uploads kept as raw/{sha256}.csv
    datasets_root: Path = REPO_ROOT / "storage" / "datasets"

    # Scoring
    model_version: str = "persocial-v1"
    sentiment_model: str = "cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual"
    emotion_model: str = "AnasAlokla/multilingual_go_emotions"
    emotion_threshold: float = 0.45
    scoring_device: str = "auto"            # auto | cuda | mps | cpu
    scoring_batch_size: int = 0             # 0 = per-device default
    claim_ttl_hours: int = 24
    auto_score_local: bool = False          # new raw uploads go straight to the local worker

    # Judge
    judge_base_url: str = Field(default="http://127.0.0.1:1234/v1",
                                validation_alias=AliasChoices("PERSOCIAL_JUDGE_BASE_URL"))
    judge_model: str = Field(default="",        # empty = the DB default model
                             validation_alias=AliasChoices("PERSOCIAL_JUDGE_MODEL"))
    audit_rate: float = 0.10                # random audit share of non-candidates
    audit_min: int = 2
    auto_judge: bool = True                 # judge a sheet as soon as it's fully scored
    persocial_packs: str = Field(default="generic",
                                 validation_alias=AliasChoices("PERSOCIAL_PACKS"))

    # Ops API
    api_host: str = "127.0.0.1"
    api_port: int = 8440
    web_origin: str = "http://127.0.0.1:5180"
    dev_no_auth: bool = False               # tests/dev only: skip the admin token check
    persocial_tz: str = Field(default="UTC", validation_alias=AliasChoices("PERSOCIAL_TZ"))


@lru_cache
def settings() -> Settings:
    return Settings()
