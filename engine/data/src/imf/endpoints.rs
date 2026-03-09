//! IMF API Endpoint Helpers
//!
//! High-level functions for common operations

use super::client::ImfClient;
use super::error::ImfResult;
use super::models::*;

/// Commodity codes for PCPS dataset
pub mod commodities {
    pub const GOLD: &str = "PGold.PP0000";
    pub const SILVER: &str = "PSilver.PP0000";
    pub const PLATINUM: &str = "PPlatinum.PP0000";
    pub const COPPER: &str = "PCopper.PP0000";
    pub const CRUDE_OIL: &str = "POilCrude.PP0000";
    pub const NATURAL_GAS: &str = "PNaturalGas.PP0000";
    pub const WHEAT: &str = "PWheat.PP0000";
    pub const CORN: &str = "PCorn.PP0000";
}

/// Frequency codes
pub mod frequency {
    pub const ANNUAL: &str = "A";
    pub const QUARTERLY: &str = "Q";
    pub const MONTHLY: &str = "M";
    pub const WEEKLY: &str = "W";
    pub const DAILY: &str = "D";
}

/// Popular datasets
pub mod datasets {
    pub const COMMODITY_PRICES: &str = "PCPS";
    pub const INT_FINANCIAL_STATS: &str = "IFS";
    pub const DIRECTION_OF_TRADE: &str = "DOT";
    pub const WEO: &str = "WEO";
    pub const BALANCE_OF_PAYMENTS: &str = "BOP";
    pub const CONSUMER_PRICE_INDEX: &str = "CPI";
    pub const INTEREST_RATES: &str = "IR";
}

impl ImfClient {
    /// Get gold price data
    pub async fn get_gold_price(
        &self,
        start: Option<&str>,
        end: Option<&str>,
    ) -> ImfResult<DataResponse> {
        self.get_data(datasets::COMMODITY_PRICES, commodities::GOLD, start, end).await
    }

    /// Get silver price data
    pub async fn get_silver_price(
        &self,
        start: Option<&str>,
        end: Option<&str>,
    ) -> ImfResult<DataResponse> {
        self.get_data(datasets::COMMODITY_PRICES, commodities::SILVER, start, end).await
    }

    /// Get crude oil price data
    pub async fn get_oil_price(
        &self,
        start: Option<&str>,
        end: Option<&str>,
    ) -> ImfResult<DataResponse> {
        self.get_data(datasets::COMMODITY_PRICES, commodities::CRUDE_OIL, start, end).await
    }

    /// Get multiple commodity prices at once
    pub async fn get_commodity_prices(
        &self,
        commodities: &[&str],
        start: Option<&str>,
        end: Option<&str>,
    ) -> ImfResult<Vec<DataResponse>> {
        let mut results = Vec::new();
        
        for commodity in commodities {
            let result = self.get_data(
                datasets::COMMODITY_PRICES,
                commodity,
                start,
                end,
            ).await?;
            results.push(result);
        }
        
        Ok(results)
    }

    /// Get International Financial Statistics for a country
    pub async fn get_ifs_data(
        &self,
        indicator: &str,
        country: &str,
        start: Option<&str>,
        end: Option<&str>,
    ) -> ImfResult<DataResponse> {
        let key = format!("{}.{}", country, indicator);
        self.get_data(datasets::INT_FINANCIAL_STATS, &key, start, end).await
    }

    /// Get inflation data (CPI) for a country
    pub async fn get_inflation(
        &self,
        country: &str,
        start: Option<&str>,
        end: Option<&str>,
    ) -> ImfResult<DataResponse> {
        // CPI indicator format varies by dataset
        let key = format!("{}CPI.PCPI_IX", country);
        self.get_data(datasets::CONSUMER_PRICE_INDEX, &key, start, end).await
    }

    /// Get interest rate data for a country
    pub async fn get_interest_rate(
        &self,
        country: &str,
        start: Option<&str>,
        end: Option<&str>,
    ) -> ImfResult<DataResponse> {
        let key = format!("{}.IR.TOTL", country);
        self.get_data(datasets::INT_FINANCIAL_STATS, &key, start, end).await
    }

    /// Get Balance of Payments data
    pub async fn get_bop_data(
        &self,
        country: &str,
        indicator: Option<&str>,
        start: Option<&str>,
        end: Option<&str>,
    ) -> ImfResult<DataResponse> {
        let indicator = indicator.unwrap_or("BOPCA.BXR");
        let key = format!("{}.{}.current.{}.A", country, datasets::BALANCE_OF_PAYMENTS, indicator);
        self.get_data(datasets::BALANCE_OF_PAYMENTS, &key, start, end).await
    }

    /// Get Direction of Trade data
    pub async fn get_trade_data(
        &self,
        reporter: &str,
        partner: &str,
        indicator: Option<&str>,
        start: Option<&str>,
        end: Option<&str>,
    ) -> ImfResult<DataResponse> {
        let indicator = indicator.unwrap_or("TXG_FOB_USD");
        let key = format!("{}.{}.{}", reporter, partner, indicator);
        self.get_data(datasets::DIRECTION_OF_TRADE, &key, start, end).await
    }

    /// List all available datasets
    pub async fn list_datasets(&self) -> ImfResult<Vec<DataflowInfo>> {
        let response = self.get_dataflows().await?;
        
        let dataflows = response
            .data
            .data_flows
            .into_iter()
            .map(|df| DataflowInfo {
                id: df.id,
                name: df.name.unwrap_or_default(),
                description: df.description,
                version: df.version.unwrap_or_default(),
            })
            .collect();
        
        Ok(dataflows)
    }

    /// Check data availability for a series
    pub async fn check_availability(
        &self,
        dataset: &str,
        key: &str,
    ) -> ImfResult<AvailabilityInfo> {
        let response = self.get_availability(dataset, key).await?;
        
        let data_constraint = response
            .data
            .data_constraints
            .into_iter()
            .next()
            .ok_or_else(|| super::error::ImfError::NotFound("No data constraint found".to_string()))?;
        
        let mut series_count = 0;
        let mut start_date = None;
        let mut end_date = None;
        let mut frequencies = Vec::new();
        
        for annotation in &data_constraint.annotations {
            match annotation.id.as_deref() {
                Some("series_count") => {
                    series_count = annotation.title.as_ref()
                        .and_then(|s: &String| s.parse::<usize>().ok())
                        .unwrap_or(0);
                }
                Some("time_period_start") => {
                    start_date = annotation.title.clone();
                }
                Some("time_period_end") => {
                    end_date = annotation.title.clone();
                }
                _ => {}
            }
        }
        
        // Extract frequencies from cube regions
        for region in &data_constraint.cube_regions {
            for component in &region.components {
                if component.id == "FREQ" {
                    for value in &component.values {
                        let v = &value.value;
                        if !frequencies.contains(v) {
                            frequencies.push(v.clone());
                        }
                    }
                }
            }
        }
        
        Ok(AvailabilityInfo {
            series_count,
            start_date,
            end_date,
            frequencies,
        })
    }
}
