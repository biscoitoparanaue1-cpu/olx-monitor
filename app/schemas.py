"""Modelos Pydantic de entrada e saída da API."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ anúncios
class PricePoint(ORM):
    price: float
    observed_at: datetime


class RuleMatchOut(BaseModel):
    rule_id: int
    name: str
    matched_text: str | None


class PriceEvalOut(ORM):
    price_label: str
    group_level: str | None = None
    group_median: float | None = None
    sample_size: int | None = None
    z_score: float | None = None


class ListingOut(ORM):
    id: int
    olx_id: str
    title: str
    url: str
    current_price: float | None
    location: str | None
    state: str | None
    image_url: str | None
    brand: str | None
    model_line: str | None
    model_code: str | None
    screen_size: int | None
    category: str | None = None
    condition: str | None
    posted_at: datetime | None
    first_seen_at: datetime
    is_active: bool
    score: float | None = None
    price_evaluation: PriceEvalOut | None = None
    feedback: Literal[-1, 1] | None = None
    rule_matches: list[RuleMatchOut] = []


class ListingDetail(ListingOut):
    description: str | None
    seller_name: str | None = None
    seller_is_professional: bool | None = None
    price_history: list[PricePoint] = []
    score_features: dict | None = None


class ListingPage(BaseModel):
    total: int
    items: list[ListingOut]


class IngestAd(BaseModel):
    """Anúncio enviado por um scraper externo (ex.: rodando na sua máquina)."""
    olx_id: str
    title: str
    url: str
    price: float | None = None
    description: str | None = None
    posted_at: datetime | None = None
    location: str | None = None
    state: str | None = None
    image_url: str | None = None
    is_professional: bool | None = None
    seller_id: str | None = None
    seller_name: str | None = None


class IngestIn(BaseModel):
    search_query: str = Field(examples=["TV LG OLED"])
    ads: list[IngestAd]


class IngestOut(BaseModel):
    received: int
    new: int
    scrape_run_id: int


# ------------------------------------------------------------------ feedback
class FeedbackIn(BaseModel):
    listing_id: int
    value: Literal[-1, 1]  # 1 = Gostei, -1 = Não gostei


class FeedbackOut(ORM):
    listing_id: int
    value: int
    created_at: datetime


# -------------------------------------------------------------- configuração
class SearchTermIn(BaseModel):
    query: str
    region: str = "brasil"
    min_price: float | None = None
    max_price: float | None = None
    max_pages: int = Field(3, ge=1, le=20)
    is_active: bool = True


class SearchTermOut(ORM, SearchTermIn):
    id: int
    created_at: datetime


class FilterRuleIn(BaseModel):
    name: str = Field(examples=["Desliga sozinha"])
    pattern: str = Field(examples=[r"deslig\w*\s+(sozinh\w*|a cada \d+\s*min)"])
    pattern_type: Literal["regex", "keywords", "fuzzy"] = "regex"
    action: Literal["tag", "include", "exclude"] = "tag"
    sets_condition: Literal["novo", "usado_bom", "usado_com_avaria", "defeito", "para_pecas"] | None = None
    weight: float = 0.0
    is_active: bool = True


class FilterRuleOut(ORM, FilterRuleIn):
    id: int
    created_at: datetime


class CategoryOut(ORM):
    id: int
    name: str
    brand: str | None
    model_line: str | None
    screen_size: int | None
    listings: int = 0


class ScrapeRunOut(ORM):
    id: int
    search_term_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    fetch_mode: str | None
    ads_found: int
    ads_new: int
    error_message: str | None


class StatsOut(BaseModel):
    listings_total: int
    listings_active: int
    listings_today: int
    feedback_likes: int
    feedback_dislikes: int
    active_model_version: int | None
    last_runs: list[ScrapeRunOut]
