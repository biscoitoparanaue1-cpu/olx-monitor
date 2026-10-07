-- GERADO a partir de app/models.py (fonte da verdade). Não edite à mão.
-- SQLite local; no Neon (PostgreSQL) as tabelas são criadas por init_db().
PRAGMA foreign_keys = ON;

CREATE TABLE filter_rules (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	pattern TEXT NOT NULL, 
	pattern_type VARCHAR(20) NOT NULL, 
	action VARCHAR(20) NOT NULL, 
	sets_condition VARCHAR(30), 
	weight FLOAT NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE model_versions (
	version INTEGER NOT NULL, 
	algorithm VARCHAR(40) NOT NULL, 
	trained_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	n_samples INTEGER, 
	metrics_json JSON, 
	is_active BOOLEAN NOT NULL, 
	PRIMARY KEY (version)
);

CREATE TABLE product_categories (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	brand VARCHAR(40), 
	model_line VARCHAR(40), 
	screen_size INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (brand, model_line, screen_size), 
	UNIQUE (name)
);

CREATE TABLE search_terms (
	id INTEGER NOT NULL, 
	"query" VARCHAR(200) NOT NULL, 
	region VARCHAR(80) NOT NULL, 
	min_price NUMERIC(12, 2), 
	max_price NUMERIC(12, 2), 
	max_pages INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE sellers (
	id INTEGER NOT NULL, 
	olx_seller_id VARCHAR(80), 
	name VARCHAR(200), 
	is_professional BOOLEAN, 
	location VARCHAR(200), 
	first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (olx_seller_id)
);

CREATE TABLE feature_weights (
	model_version INTEGER NOT NULL, 
	feature VARCHAR(120) NOT NULL, 
	weight FLOAT NOT NULL, 
	PRIMARY KEY (model_version, feature), 
	FOREIGN KEY(model_version) REFERENCES model_versions (version)
);

CREATE TABLE listings (
	id INTEGER NOT NULL, 
	olx_id VARCHAR(40) NOT NULL, 
	search_term_id INTEGER, 
	category_id INTEGER, 
	seller_id INTEGER, 
	title VARCHAR(300) NOT NULL, 
	description TEXT, 
	url VARCHAR(500) NOT NULL, 
	current_price NUMERIC(12, 2), 
	location VARCHAR(200), 
	state VARCHAR(2), 
	image_url VARCHAR(500), 
	brand VARCHAR(40), 
	model_line VARCHAR(40), 
	model_code VARCHAR(40), 
	screen_size INTEGER, 
	posted_at DATETIME, 
	first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	condition VARCHAR(30), 
	raw_json JSON, 
	PRIMARY KEY (id), 
	UNIQUE (olx_id), 
	FOREIGN KEY(search_term_id) REFERENCES search_terms (id), 
	FOREIGN KEY(category_id) REFERENCES product_categories (id), 
	FOREIGN KEY(seller_id) REFERENCES sellers (id)
);
CREATE INDEX ix_listings_first_seen ON listings (first_seen_at);
CREATE INDEX ix_listings_cat_cond ON listings (category_id, condition);

CREATE TABLE scrape_runs (
	id INTEGER NOT NULL, 
	search_term_id INTEGER NOT NULL, 
	started_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	finished_at DATETIME, 
	status VARCHAR(20) NOT NULL, 
	fetch_mode VARCHAR(20), 
	pages_fetched INTEGER NOT NULL, 
	ads_found INTEGER NOT NULL, 
	ads_new INTEGER NOT NULL, 
	error_message TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(search_term_id) REFERENCES search_terms (id)
);

CREATE TABLE feedback (
	id INTEGER NOT NULL, 
	listing_id INTEGER NOT NULL, 
	value INTEGER NOT NULL, 
	score_at_time FLOAT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_feedback_value CHECK (value IN (-1, 1)), 
	UNIQUE (listing_id), 
	FOREIGN KEY(listing_id) REFERENCES listings (id) ON DELETE CASCADE
);

CREATE TABLE listing_rule_matches (
	listing_id INTEGER NOT NULL, 
	rule_id INTEGER NOT NULL, 
	matched_text TEXT, 
	PRIMARY KEY (listing_id, rule_id), 
	FOREIGN KEY(listing_id) REFERENCES listings (id) ON DELETE CASCADE, 
	FOREIGN KEY(rule_id) REFERENCES filter_rules (id) ON DELETE CASCADE
);

CREATE TABLE listing_scores (
	listing_id INTEGER NOT NULL, 
	score FLOAT NOT NULL, 
	model_version INTEGER NOT NULL, 
	features_json JSON, 
	computed_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (listing_id), 
	FOREIGN KEY(listing_id) REFERENCES listings (id) ON DELETE CASCADE
);
CREATE INDEX ix_scores_score ON listing_scores (score);

CREATE TABLE price_evaluations (
	id INTEGER NOT NULL, 
	listing_id INTEGER NOT NULL, 
	evaluated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	price NUMERIC(12, 2) NOT NULL, 
	group_level VARCHAR(20), 
	group_median NUMERIC(12, 2), 
	group_mean NUMERIC(12, 2), 
	group_stddev NUMERIC(12, 2), 
	sample_size INTEGER, 
	z_score FLOAT, 
	price_label VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(listing_id) REFERENCES listings (id) ON DELETE CASCADE
);

CREATE TABLE price_history (
	id INTEGER NOT NULL, 
	listing_id INTEGER NOT NULL, 
	price NUMERIC(12, 2) NOT NULL, 
	observed_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	scrape_run_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(listing_id) REFERENCES listings (id) ON DELETE CASCADE, 
	FOREIGN KEY(scrape_run_id) REFERENCES scrape_runs (id)
);
CREATE INDEX ix_price_history_listing ON price_history (listing_id, observed_at);
