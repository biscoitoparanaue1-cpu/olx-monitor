"""Modelo de dados (fonte da verdade; schema.sql é gerado a partir daqui)."""
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint, and_, func, select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ProductCategory(Base):
    """Grupo de comparação de preço: marca + linha/modelo + tamanho.

    Ex.: ("LG", "OLED C1", 55) -> "LG OLED C1 55". Quando o modelo não é
    identificado, model_line fica NULL e o grupo vira "LG OLED 55".
    """
    __tablename__ = "product_categories"
    __table_args__ = (UniqueConstraint("brand", "model_line", "screen_size"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    brand: Mapped[str | None] = mapped_column(String(40))
    model_line: Mapped[str | None] = mapped_column(String(40))
    screen_size: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SearchTerm(Base):
    __tablename__ = "search_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(String(200))
    region: Mapped[str] = mapped_column(String(80), default="brasil")
    min_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    max_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    max_pages: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    search_term_id: Mapped[int] = mapped_column(ForeignKey("search_terms.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|ok|blocked|error
    fetch_mode: Mapped[str | None] = mapped_column(String(20))
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    ads_found: Mapped[int] = mapped_column(Integer, default=0)
    ads_new: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(primary_key=True)
    olx_seller_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    is_professional: Mapped[bool | None] = mapped_column(Boolean)
    location: Mapped[str | None] = mapped_column(String(200))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        Index("ix_listings_cat_cond", "category_id", "condition"),
        Index("ix_listings_first_seen", "first_seen_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    olx_id: Mapped[str] = mapped_column(String(40), unique=True)
    search_term_id: Mapped[int | None] = mapped_column(ForeignKey("search_terms.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"))
    seller_id: Mapped[int | None] = mapped_column(ForeignKey("sellers.id"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(500))
    current_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    location: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str | None] = mapped_column(String(2))  # UF
    image_url: Mapped[str | None] = mapped_column(String(500))
    # Atributos extraídos do título/descrição
    brand: Mapped[str | None] = mapped_column(String(40))
    model_line: Mapped[str | None] = mapped_column(String(40))
    model_code: Mapped[str | None] = mapped_column(String(40))
    screen_size: Mapped[int | None] = mapped_column(Integer)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # novo|usado_bom|usado_com_avaria|defeito|para_pecas (preenchido pelo categorizador)
    condition: Mapped[str | None] = mapped_column(String(30))
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    category: Mapped[ProductCategory | None] = relationship()
    seller: Mapped[Seller | None] = relationship()
    prices: Mapped[list["PriceHistory"]] = relationship(
        back_populates="listing", cascade="all, delete-orphan", order_by="PriceHistory.observed_at"
    )
    rule_matches: Mapped[list["ListingRuleMatch"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin")
    evaluations: Mapped[list["PriceEvaluation"]] = relationship(
        cascade="all, delete-orphan", order_by="PriceEvaluation.id")
    score: Mapped["ListingScore | None"] = relationship(
        cascade="all, delete-orphan", lazy="selectin")
    feedback: Mapped["Feedback | None"] = relationship(
        cascade="all, delete-orphan", lazy="selectin")
    note: Mapped["FeedbackNote | None"] = relationship(
        cascade="all, delete-orphan", lazy="selectin")

    @property
    def latest_evaluation(self) -> "PriceEvaluation | None":
        if "evaluations" in self.__dict__:  # histórico já carregado (ex.: avaliação recém-feita)
            return self.evaluations[-1] if self.evaluations else None
        return self.last_evaluation


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (Index("ix_price_history_listing", "listing_id", "observed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    observed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    scrape_run_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_runs.id"))

    listing: Mapped[Listing] = relationship(back_populates="prices")


class FilterRule(Base):
    """Filtro configurável sobre título+descrição ("desliga a cada 40min")."""
    __tablename__ = "filter_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    pattern: Mapped[str] = mapped_column(Text)
    pattern_type: Mapped[str] = mapped_column(String(20), default="regex")  # regex|keywords|fuzzy
    action: Mapped[str] = mapped_column(String(20), default="tag")  # tag|include|exclude
    sets_condition: Mapped[str | None] = mapped_column(String(30))
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ListingRuleMatch(Base):
    __tablename__ = "listing_rule_matches"

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("filter_rules.id", ondelete="CASCADE"), primary_key=True)
    matched_text: Mapped[str | None] = mapped_column(Text)

    rule: Mapped[FilterRule] = relationship(lazy="joined")


class PriceEvaluation(Base):
    __tablename__ = "price_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    group_level: Mapped[str | None] = mapped_column(String(20))  # modelo+tamanho|tamanho|marca
    group_median: Mapped[float | None] = mapped_column(Numeric(12, 2))
    group_mean: Mapped[float | None] = mapped_column(Numeric(12, 2))
    group_stddev: Mapped[float | None] = mapped_column(Numeric(12, 2))
    sample_size: Mapped[int | None] = mapped_column(Integer)
    z_score: Mapped[float | None] = mapped_column(Float)
    price_label: Mapped[str] = mapped_column(String(20))  # otimo_negocio|preco_justo|caro|sem_base


class ListingScore(Base):
    __tablename__ = "listing_scores"
    __table_args__ = (Index("ix_scores_score", "score"),)

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True)
    score: Mapped[float] = mapped_column(Float)
    model_version: Mapped[int] = mapped_column(Integer)
    features_json: Mapped[dict | None] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("value IN (-1, 1)", name="ck_feedback_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), unique=True)
    value: Mapped[int] = mapped_column(Integer)
    score_at_time: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FeedbackNote(Base):
    """O que você escreveu que gostou / não gostou num anúncio (alimenta o aprendizado)."""
    __tablename__ = "feedback_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), unique=True)
    liked: Mapped[str | None] = mapped_column(Text)
    disliked: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ModelVersion(Base):
    __tablename__ = "model_versions"

    version: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    algorithm: Mapped[str] = mapped_column(String(40))  # weighted_rules|logistic_regression
    trained_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    n_samples: Mapped[int | None] = mapped_column(Integer)
    metrics_json: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


class FeatureWeight(Base):
    __tablename__ = "feature_weights"

    model_version: Mapped[int] = mapped_column(
        ForeignKey("model_versions.version"), primary_key=True)
    feature: Mapped[str] = mapped_column(String(120), primary_key=True)
    weight: Mapped[float] = mapped_column(Float)


# Só a avaliação mais recente de cada anúncio, carregada numa consulta para a
# lista toda (antes era uma consulta por anúncio: lento com o banco na nuvem).
_latest_eval_ids = (select(func.max(PriceEvaluation.id))
                    .group_by(PriceEvaluation.listing_id).scalar_subquery())
Listing.last_evaluation = relationship(
    PriceEvaluation, uselist=False, viewonly=True, lazy="selectin",
    primaryjoin=and_(PriceEvaluation.listing_id == Listing.id,
                     PriceEvaluation.id.in_(_latest_eval_ids)))
