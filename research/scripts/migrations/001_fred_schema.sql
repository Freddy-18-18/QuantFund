-- FRED Database Schema for PostgreSQL/TimescaleDB
-- Migration: 001_fred_schema.sql
-- Created: 2026-03-08

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ============================================
-- ENUM TYPES
-- ============================================

CREATE TYPE fred_frequency AS ENUM (
    'd',   -- Daily
    'w',   -- Weekly
    'bw',  -- Biweekly
    'm',   -- Monthly
    'q',   -- Quarterly
    'sa',  -- Semiannual
    'a'    -- Annual
);

CREATE TYPE fred_units AS ENUM (
    'percent',           -- Percent
    'percent_change',   -- Percent Change
    'chained_dollars',  -- Chained Dollars
    'dollars',          -- Dollars
    'index',            -- Index
    'millions',         -- Millions
    'billions',         -- Billions
    'number',           -- Number
    'ratio'             -- Ratio
);

CREATE TYPE fred_seasonal_adjustment AS ENUM (
    'not_seasonally_adjusted',
    'seasonally_adjusted',
    'not_seasonally_adjusted_daily',
    'seasonally_adjusted_annual_rate'
);

CREATE TYPE anomaly_severity AS ENUM (
    'low',
    'medium',
    'high',
    'critical'
);

-- ============================================
-- FRED SERIES TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fred_series (
    id SERIAL PRIMARY KEY,
    series_id VARCHAR(50) NOT NULL UNIQUE,
    title TEXT NOT NULL,
    frequency fred_frequency DEFAULT 'm',
    units fred_units DEFAULT 'percent',
    seasonal_adjustment fred_seasonal_adjustment DEFAULT 'seasonally_adjusted',
    popularity INTEGER DEFAULT 0,
    notes TEXT,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fred_series_series_id ON fred_series(series_id);
CREATE INDEX idx_fred_series_frequency ON fred_series(frequency);
CREATE INDEX idx_fred_series_popularity ON fred_series(popularity DESC);
CREATE INDEX idx_fred_series_last_updated ON fred_series(last_updated DESC);

-- ============================================
-- FRED OBSERVATIONS TABLE (TimescaleDB Hypertable)
-- ============================================

CREATE TABLE IF NOT EXISTS fred_observations (
    id BIGSERIAL,
    series_id VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    value DOUBLE PRECISION,
    realtime_start DATE NOT NULL,
    realtime_end DATE NOT NULL DEFAULT '9999-12-31',
    PRIMARY KEY (id, date)
);

SELECT create_hypertable(
    'fred_observations',
    'date',
    chunk_time_interval => INTERVAL '1 year',
    if_not_exists => TRUE
);

CREATE INDEX idx_fred_observations_series_date ON fred_observations(series_id, date DESC);
CREATE INDEX idx_fred_observations_realtime ON fred_observations(realtime_start, realtime_end);
CREATE UNIQUE INDEX idx_fred_observations_unique ON fred_observations(series_id, date, realtime_start, realtime_end);

-- Foreign key constraint (created after fred_series exists)
-- ALTER TABLE fred_observations 
--     ADD CONSTRAINT fk_observations_series 
--     FOREIGN KEY (series_id) REFERENCES fred_series(series_id) ON DELETE CASCADE;

-- ============================================
-- FRED TAGS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fred_tags (
    name VARCHAR(50) NOT NULL PRIMARY KEY,
    group_id VARCHAR(50),
    notes TEXT,
    popularity INTEGER DEFAULT 0,
    series_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fred_tags_group_id ON fred_tags(group_id);
CREATE INDEX idx_fred_tags_popularity ON fred_tags(popularity DESC);
CREATE INDEX idx_fred_tags_series_count ON fred_tags(series_count DESC);

-- ============================================
-- FRED SERIES TAGS JUNCTION TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fred_series_tags (
    series_id VARCHAR(50) NOT NULL,
    tag_name VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (series_id, tag_name)
);

CREATE INDEX idx_fred_series_tags_series_id ON fred_series_tags(series_id);
CREATE INDEX idx_fred_series_tags_tag_name ON fred_series_tags(tag_name);

-- ============================================
-- FRED CATEGORIES TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fred_categories (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    parent_id INTEGER REFERENCES fred_categories(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fred_categories_parent_id ON fred_categories(parent_id);
CREATE INDEX idx_fred_categories_name ON fred_categories(name);

-- ============================================
-- FRED SERIES CATEGORIES JUNCTION TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fred_series_categories (
    series_id VARCHAR(50) NOT NULL,
    category_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (series_id, category_id)
);

CREATE INDEX idx_fred_series_categories_series_id ON fred_series_categories(series_id);
CREATE INDEX idx_fred_series_categories_category_id ON fred_series_categories(category_id);

-- ============================================
-- FRED RELEASES TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fred_releases (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    press_release BOOLEAN DEFAULT FALSE,
    link TEXT,
    realtime_start DATE NOT NULL DEFAULT CURRENT_DATE,
    realtime_end DATE NOT NULL DEFAULT '9999-12-31',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fred_releases_name ON fred_releases(name);
CREATE INDEX idx_fred_releases_press_release ON fred_releases(press_release);

-- ============================================
-- FRED SERIES RELEASES JUNCTION TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fred_series_releases (
    series_id VARCHAR(50) NOT NULL,
    release_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (series_id, release_id)
);

CREATE INDEX idx_fred_series_releases_series_id ON fred_series_releases(series_id);
CREATE INDEX idx_fred_series_releases_release_id ON fred_series_releases(release_id);

-- ============================================
-- FRED RELEASE DATES TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fred_release_dates (
    release_id INTEGER NOT NULL,
    date DATE NOT NULL,
    release_type VARCHAR(50),
    PRIMARY KEY (release_id, date)
);

CREATE INDEX idx_fred_release_dates_date ON fred_release_dates(date DESC);

-- ============================================
-- FRED ANOMALIES TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fred_anomalies (
    id SERIAL PRIMARY KEY,
    series_id VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    method VARCHAR(50) NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    severity anomaly_severity NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fred_anomalies_series_id_date ON fred_anomalies(series_id, date DESC);
CREATE INDEX idx_fred_anomalies_severity ON fred_anomalies(severity);
CREATE INDEX idx_fred_anomalies_created_at ON fred_anomalies(created_at DESC);

-- ============================================
-- FRED FEATURES TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fred_features (
    id SERIAL PRIMARY KEY,
    series_id VARCHAR(50) NOT NULL,
    feature_name VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    value DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(series_id, feature_name, date)
);

CREATE INDEX idx_fred_features_series_date ON fred_features(series_id, date DESC);
CREATE INDEX idx_fred_features_feature_name ON fred_features(feature_name);
CREATE INDEX idx_fred_features_series_feature ON fred_features(series_id, feature_name, date);

-- ============================================
-- FOREIGN KEY CONSTRAINTS (after all tables exist)
-- ============================================

ALTER TABLE fred_observations 
    ADD CONSTRAINT fk_observations_series 
    FOREIGN KEY (series_id) REFERENCES fred_series(series_id) ON DELETE CASCADE;

ALTER TABLE fred_series_tags 
    ADD CONSTRAINT fk_series_tags_series 
    FOREIGN KEY (series_id) REFERENCES fred_series(series_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_series_tags_tag 
    FOREIGN KEY (tag_name) REFERENCES fred_tags(name) ON DELETE CASCADE;

ALTER TABLE fred_series_categories 
    ADD CONSTRAINT fk_series_categories_series 
    FOREIGN KEY (series_id) REFERENCES fred_series(series_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_series_categories_category 
    FOREIGN KEY (category_id) REFERENCES fred_categories(id) ON DELETE CASCADE;

ALTER TABLE fred_series_releases 
    ADD CONSTRAINT fk_series_releases_series 
    FOREIGN KEY (series_id) REFERENCES fred_series(series_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_series_releases_release 
    FOREIGN KEY (release_id) REFERENCES fred_releases(id) ON DELETE CASCADE;

ALTER TABLE fred_release_dates 
    ADD CONSTRAINT fk_release_dates_release 
    FOREIGN KEY (release_id) REFERENCES fred_releases(id) ON DELETE CASCADE;

ALTER TABLE fred_anomalies 
    ADD CONSTRAINT fk_anomalies_series 
    FOREIGN KEY (series_id) REFERENCES fred_series(series_id) ON DELETE CASCADE;

ALTER TABLE fred_features 
    ADD CONSTRAINT fk_features_series 
    FOREIGN KEY (series_id) REFERENCES fred_series(series_id) ON DELETE CASCADE;

-- ============================================
-- COMPRESSION SETTINGS (TimescaleDB)
-- ============================================

ALTER TABLE fred_observations SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'series_id'
);

SELECT add_retention_policy('fred_observations', INTERVAL '2 years');

-- ============================================
-- SAMPLE DATA FOR TESTING
-- ============================================

INSERT INTO fred_series (series_id, title, frequency, units, seasonal_adjustment, popularity, last_updated) VALUES
    ('GDP', 'Gross Domestic Product', 'q', 'billions', 'seasonally_adjusted', 100, NOW()),
    ('CPIAUCSL', 'Consumer Price Index for All Urban Consumers', 'm', 'index', 'seasonally_adjusted', 99, NOW()),
    ('UNRATE', 'Unemployment Rate', 'm', 'percent', 'seasonally_adjusted', 98, NOW()),
    ('FEDFUNDS', 'Federal Funds Rate', 'm', 'percent', 'not_seasonally_adjusted', 97, NOW()),
    ('M2SL', 'M2 Money Supply', 'w', 'billions', 'seasonally_adjusted', 85, NOW())
ON CONFLICT (series_id) DO NOTHING;

INSERT INTO fred_tags (name, group_id, notes, popularity, series_count) VALUES
    ('gdp', 'national', 'Gross Domestic Product', 100, 1),
    ('price-index', 'price', 'Price Index related', 95, 1),
    ('employment', 'labor', 'Employment related', 90, 1),
    ('money-supply', 'financial', 'Money Supply related', 85, 1),
    ('interest-rate', 'financial', 'Interest Rate related', 88, 1)
ON CONFLICT (name) DO NOTHING;

INSERT INTO fred_categories (id, name, parent_id) VALUES
    (1, 'National Income', NULL),
    (2, 'GDP', 1),
    (3, 'Prices', NULL),
    (4, 'Consumer Prices', 3),
    (5, 'Employment', NULL),
    (6, 'Unemployment', 5),
    (7, 'Money', NULL),
    (8, 'Money Supply', 7),
    (9, 'Interest Rates', NULL)
ON CONFLICT (id) DO NOTHING;

INSERT INTO fred_releases (id, name, press_release, link) VALUES
    (1, 'Gross Domestic Product', TRUE, 'https://fred.stlouisfed.org/release/tables?rid=53&eid=149'),
    (2, 'Consumer Price Index', TRUE, 'https://fred.stlouisfed.org/release/tables?rid=296&eid=149'),
    (3, 'Employment Situation', TRUE, 'https://fred.stlouisfed.org/release/tables?rid=295&eid=149'),
    (4, 'H.4.1 Weekly Release', TRUE, 'https://fred.stlouisfed.org/release/tables?rid=441&eid=149')
ON CONFLICT (id) DO NOTHING;

INSERT INTO fred_series_tags (series_id, tag_name) VALUES
    ('GDP', 'gdp'),
    ('CPIAUCSL', 'price-index'),
    ('UNRATE', 'employment'),
    ('FEDFUNDS', 'interest-rate'),
    ('M2SL', 'money-supply')
ON CONFLICT (series_id, tag_name) DO NOTHING;

INSERT INTO fred_series_categories (series_id, category_id) VALUES
    ('GDP', 2),
    ('CPIAUCSL', 4),
    ('UNRATE', 6),
    ('M2SL', 8)
ON CONFLICT (series_id, category_id) DO NOTHING;

INSERT INTO fred_series_releases (series_id, release_id) VALUES
    ('GDP', 1),
    ('CPIAUCSL', 2),
    ('UNRATE', 3),
    ('M2SL', 4)
ON CONFLICT (series_id, release_id) DO NOTHING;

INSERT INTO fred_observations (series_id, date, value, realtime_start, realtime_end) VALUES
    ('GDP', '2024-01-01', 26984.8, '2024-03-27', '9999-12-31'),
    ('GDP', '2024-04-01', 27380.8, '2024-06-26', '9999-12-31'),
    ('GDP', '2024-07-01', 27734.1, '2024-09-25', '9999-12-31'),
    ('GDP', '2024-10-01', 28118.3, '2024-12-20', '9999-12-31'),
    ('CPIAUCSL', '2024-01-01', 310.175, '2024-02-13', '9999-12-31'),
    ('CPIAUCSL', '2024-02-01', 310.593, '2024-03-12', '9999-12-31'),
    ('CPIAUCSL', '2024-03-01', 312.230, '2024-04-10', '9999-12-31'),
    ('UNRATE', '2024-01-01', 3.7, '2024-02-02', '9999-12-31'),
    ('UNRATE', '2024-02-01', 3.9, '2024-03-05', '9999-12-31'),
    ('UNRATE', '2024-03-01', 3.8, '2024-04-05', '9999-12-31'),
    ('FEDFUNDS', '2024-01-01', 5.33, '2024-02-01', '9999-12-31'),
    ('FEDFUNDS', '2024-02-01', 5.33, '2024-03-01', '9999-12-31'),
    ('FEDFUNDS', '2024-03-01', 5.33, '2024-04-01', '9999-12-31'),
    ('M2SL', '2024-01-22', 20920.0, '2024-01-29', '9999-12-31'),
    ('M2SL', '2024-01-29', 20960.0, '2024-02-05', '9999-12-31'),
    ('M2SL', '2024-02-05', 21010.0, '2024-02-12', '9999-12-31')
ON CONFLICT DO NOTHING;

INSERT INTO fred_anomalies (series_id, date, method, score, severity, notes) VALUES
    ('GDP', '2020-04-01', 'zscore', 4.2, 'high', 'COVID-19 pandemic impact'),
    ('UNRATE', '2020-04-01', 'zscore', 5.8, 'critical', 'Massive unemployment spike')
ON CONFLICT DO NOTHING;

INSERT INTO fred_features (series_id, feature_name, date, value) VALUES
    ('GDP', 'growth_rate', '2024-01-01', 3.4),
    ('GDP', 'volatility', '2024-01-01', 0.8),
    ('CPIAUCSL', 'yoy_change', '2024-01-01', 3.1),
    ('CPIAUCSL', 'volatility', '2024-01-01', 0.5),
    ('UNRATE', 'mean', '2024-01-01', 3.8),
    ('UNRATE', 'std', '2024-01-01', 0.2)
ON CONFLICT DO NOTHING;

-- ============================================
-- GRANT PERMISSIONS
-- ============================================

-- Grant read access to readonly role
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly;
-- GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO readonly;

-- Grant read-write access to app role
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app;

-- ============================================
-- COMMENTS
-- ============================================

COMMENT ON TABLE fred_series IS 'FRED economic time series metadata';
COMMENT ON TABLE fred_observations IS 'FRED economic time series observations (TimescaleDB hypertable)';
COMMENT ON TABLE fred_tags IS 'FRED tags for categorizing series';
COMMENT ON TABLE fred_series_tags IS 'Junction table for series-tag relationships';
COMMENT ON TABLE fred_categories IS 'FRED category hierarchy';
COMMENT ON TABLE fred_series_categories IS 'Junction table for series-category relationships';
COMMENT ON TABLE fred_releases IS 'FRED data releases';
COMMENT ON TABLE fred_series_releases IS 'Junction table for series-release relationships';
COMMENT ON TABLE fred_release_dates IS 'Release dates for FRED data';
COMMENT ON TABLE fred_anomalies IS 'Detected anomalies in FRED data';
COMMENT ON TABLE fred_features IS 'Calculated features for FRED series';
